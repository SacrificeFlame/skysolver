"""Idempotent, ordered ingestion primitives for isolated airline adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import threading
from typing import Any, Callable


class IngestionStatus(str, Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    DEAD_LETTER = "dead_letter"


@dataclass(frozen=True)
class SourceRecord:
    event_id: str
    tenant_id: str
    source_system: str
    contract_version: str
    aggregate_type: str
    aggregate_id: str
    source_timestamp: datetime
    cursor: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class IngestionResult:
    event_id: str
    status: IngestionStatus
    canonical_record: dict[str, Any] | None = None
    findings: tuple[dict[str, str], ...] = ()
    content_sha256: str | None = None
    ingested_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True)
class DeadLetter:
    event_id: str
    tenant_id: str
    source_system: str
    code: str
    message: str
    payload_sha256: str
    recorded_at: datetime


class ContractError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class IngestionEngine:
    """Process records without assuming a specific transport or carrier vendor."""

    def __init__(self, supported_contracts: set[str], mapper: Callable[[SourceRecord], dict[str, Any]],
                 allowed_fields: set[str] | None = None):
        self._supported_contracts = supported_contracts
        self._mapper = mapper
        self._allowed_fields = allowed_fields
        self._lock = threading.RLock()
        self._seen: dict[tuple[str, str, str], str] = {}
        self._latest: dict[tuple[str, str, str, str], datetime] = {}
        self._cursors: dict[tuple[str, str], str] = {}
        self._accepted: list[IngestionResult] = []
        self._dead_letters: list[DeadLetter] = []

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()

    def ingest(self, record: SourceRecord) -> IngestionResult:
        if record.source_timestamp.tzinfo is None:
            return self._dead_letter(record, "NAIVE_SOURCE_TIMESTAMP", "Source timestamp must be timezone-aware")
        if record.contract_version not in self._supported_contracts:
            return self._dead_letter(record, "UNSUPPORTED_CONTRACT", f"Unsupported contract version {record.contract_version}")
        digest = self._digest(record.payload)
        event_key = (record.tenant_id, record.source_system, record.event_id)
        aggregate_key = (record.tenant_id, record.source_system, record.aggregate_type, record.aggregate_id)
        with self._lock:
            if event_key in self._seen:
                if self._seen[event_key] != digest:
                    return self._dead_letter(record, "EVENT_ID_COLLISION", "Event ID was reused with different content")
                return IngestionResult(record.event_id, IngestionStatus.DUPLICATE, content_sha256=digest)
            previous = self._latest.get(aggregate_key)
            out_of_order = previous is not None and record.source_timestamp < previous
            try:
                minimized = record
                if self._allowed_fields is not None:
                    minimized = SourceRecord(**{**asdict(record), "payload": {key: value for key, value in record.payload.items() if key in self._allowed_fields}})
                canonical = self._mapper(minimized)
            except (ContractError, KeyError, TypeError, ValueError) as exc:
                return self._dead_letter(record, getattr(exc, "code", "CANONICAL_MAPPING_FAILED"), str(exc))
            self._seen[event_key] = digest
            self._latest[aggregate_key] = max(previous, record.source_timestamp) if previous else record.source_timestamp
            self._cursors[(record.tenant_id, record.source_system)] = record.cursor
            findings = ({"code": "OUT_OF_ORDER_SOURCE_EVENT", "severity": "warning", "message": "Accepted for event history; current projection must retain the newer version."},) if out_of_order else ()
            result = IngestionResult(record.event_id, IngestionStatus.OUT_OF_ORDER if out_of_order else IngestionStatus.ACCEPTED,
                                     canonical, findings, digest)
            self._accepted.append(result)
            return result

    def _dead_letter(self, record: SourceRecord, code: str, message: str) -> IngestionResult:
        digest = self._digest(record.payload)
        with self._lock:
            self._dead_letters.append(DeadLetter(record.event_id, record.tenant_id, record.source_system, code, message, digest, datetime.now(timezone.utc)))
        return IngestionResult(record.event_id, IngestionStatus.DEAD_LETTER, findings=({"code": code, "severity": "blocking", "message": message},), content_sha256=digest)

    def cursor(self, tenant_id: str, source_system: str) -> str | None:
        return self._cursors.get((tenant_id, source_system))

    def dead_letters(self) -> tuple[DeadLetter, ...]:
        return tuple(self._dead_letters)

    def reconcile(self, authoritative_ids: set[str]) -> dict[str, list[str]]:
        accepted_ids = {result.canonical_record["canonical_id"] for result in self._accepted if result.canonical_record and "canonical_id" in result.canonical_record}
        return {"missing_locally": sorted(authoritative_ids - accepted_ids), "missing_at_source": sorted(accepted_ids - authoritative_ids)}
