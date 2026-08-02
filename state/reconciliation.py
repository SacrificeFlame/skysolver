"""Cross-partition reservation, commit and compensation saga."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import threading
import uuid


class SagaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code


class SagaStatus(str, Enum):
    REQUESTED = "requested"
    SOURCE_RESERVED = "source_reserved"
    DESTINATION_RESERVED = "destination_reserved"
    VALIDATED = "validated"
    COMMITTING = "committing"
    PARTIAL = "partial"
    COMPLETE = "complete"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class PartitionMoveSaga:
    saga_id: str
    tenant_id: str
    recovery_id: str
    resource_type: str
    resource_id: str
    source_partition: str
    destination_partition: str
    movement_reference: str
    correlation_id: str
    status: SagaStatus = SagaStatus.REQUESTED
    state_version: int = 1
    source_reservation: str | None = None
    destination_reservation: str | None = None
    legality_certificate_id: str | None = None
    movement_validation_id: str | None = None
    source_ack: bool | None = None
    destination_ack: bool | None = None
    findings: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self):
        value = asdict(self); value["status"] = self.status.value; return value


class PartitionMoveRegistry:
    def __init__(self):
        self._lock = threading.RLock(); self._sagas: dict[str, PartitionMoveSaga] = {}; self._idempotency = {}

    def create(self, *, tenant_id: str, recovery_id: str, resource_type: str, resource_id: str,
               source_partition: str, destination_partition: str, movement_reference: str,
               correlation_id: str, idempotency_key: str) -> PartitionMoveSaga:
        if source_partition == destination_partition:
            raise SagaError("same_partition", "Cross-partition move requires distinct partitions")
        key = (tenant_id, idempotency_key)
        with self._lock:
            if key in self._idempotency: return self._sagas[self._idempotency[key]]
            saga = PartitionMoveSaga(f"SAG-{uuid.uuid4().hex[:12].upper()}", tenant_id, recovery_id, resource_type,
                                     resource_id, source_partition, destination_partition, movement_reference, correlation_id)
            self._sagas[saga.saga_id] = saga; self._idempotency[key] = saga.saga_id; return saga

    def get(self, saga_id: str) -> PartitionMoveSaga:
        try: return self._sagas[saga_id]
        except KeyError as exc: raise SagaError("saga_not_found", "Partition move saga not found") from exc

    @staticmethod
    def _check(saga: PartitionMoveSaga, expected_version: int, expected_status: SagaStatus):
        if saga.state_version != expected_version: raise SagaError("stale_state", f"Expected saga version {saga.state_version}")
        if saga.status is not expected_status: raise SagaError("invalid_transition", f"Expected {expected_status.value}, found {saga.status.value}")

    @staticmethod
    def _advance(saga: PartitionMoveSaga, status: SagaStatus):
        saga.status = status; saga.state_version += 1; saga.updated_at = datetime.now(timezone.utc).isoformat(); return saga

    def reserve_source(self, saga_id: str, expected_version: int, reservation_id: str) -> PartitionMoveSaga:
        with self._lock:
            saga = self.get(saga_id); self._check(saga, expected_version, SagaStatus.REQUESTED)
            saga.source_reservation = reservation_id; return self._advance(saga, SagaStatus.SOURCE_RESERVED)

    def reserve_destination(self, saga_id: str, expected_version: int, reservation_id: str) -> PartitionMoveSaga:
        with self._lock:
            saga = self.get(saga_id); self._check(saga, expected_version, SagaStatus.SOURCE_RESERVED)
            saga.destination_reservation = reservation_id; return self._advance(saga, SagaStatus.DESTINATION_RESERVED)

    def validate(self, saga_id: str, expected_version: int, legality_certificate_id: str,
                 movement_validation_id: str, findings: list[dict]) -> PartitionMoveSaga:
        with self._lock:
            saga = self.get(saga_id); self._check(saga, expected_version, SagaStatus.DESTINATION_RESERVED)
            saga.findings = findings
            if findings: return self._advance(saga, SagaStatus.COMPENSATING)
            saga.legality_certificate_id = legality_certificate_id; saga.movement_validation_id = movement_validation_id
            return self._advance(saga, SagaStatus.VALIDATED)

    def begin_commit(self, saga_id: str, expected_version: int) -> PartitionMoveSaga:
        with self._lock:
            saga = self.get(saga_id); self._check(saga, expected_version, SagaStatus.VALIDATED)
            if not all([saga.source_reservation, saga.destination_reservation, saga.legality_certificate_id, saga.movement_validation_id]):
                raise SagaError("commit_evidence_missing", "Both reservations and validation evidence are required")
            return self._advance(saga, SagaStatus.COMMITTING)

    def acknowledge_partition(self, saga_id: str, expected_version: int, partition: str, accepted: bool) -> PartitionMoveSaga:
        with self._lock:
            saga = self.get(saga_id)
            if saga.state_version != expected_version: raise SagaError("stale_state", f"Expected saga version {saga.state_version}")
            if saga.status not in {SagaStatus.COMMITTING, SagaStatus.PARTIAL}:
                raise SagaError("invalid_transition", "Partition acknowledgement is not expected")
            if partition == saga.source_partition: saga.source_ack = accepted
            elif partition == saga.destination_partition: saga.destination_ack = accepted
            else: raise SagaError("unknown_partition", "Acknowledgement is not from this saga's partitions")
            if accepted is False: return self._advance(saga, SagaStatus.COMPENSATING)
            if saga.source_ack is True and saga.destination_ack is True: return self._advance(saga, SagaStatus.COMPLETE)
            return self._advance(saga, SagaStatus.PARTIAL)

    def complete_compensation(self, saga_id: str, expected_version: int, source_released: bool, destination_released: bool) -> PartitionMoveSaga:
        with self._lock:
            saga = self.get(saga_id); self._check(saga, expected_version, SagaStatus.COMPENSATING)
            if not source_released or not destination_released:
                raise SagaError("compensation_incomplete", "Both partition reservations must be released")
            return self._advance(saga, SagaStatus.COMPENSATED)
