"""Fail-closed interfaces shared by isolated airline-system adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import time
from typing import Any, Callable, Protocol


class AdapterSecurityError(RuntimeError): pass
class UnsupportedContract(RuntimeError): pass
class AdapterUnavailable(RuntimeError): pass
class SourceTimeout(TimeoutError): pass


class PublishStatus(str, Enum):
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ApprovalEvidence:
    actor_subject: str
    actor_role: str
    approved_at: datetime


@dataclass(frozen=True)
class DeploymentCommand:
    command_id: str
    tenant_id: str
    deployment_id: str
    recovery_id: str
    candidate_id: str
    candidate_version: int
    state_version: int
    target_system: str
    resource_type: str
    resource_id: str
    action: str
    payload: dict[str, Any]
    proposed_by: str
    requested_by: str
    approvals: tuple[ApprovalEvidence, ...]
    correlation_id: str
    idempotency_key: str
    expires_at: datetime
    signing_key_id: str
    signature: str

    def signed_content(self) -> bytes:
        value = asdict(self)
        value.pop("signature")
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


@dataclass(frozen=True)
class PublishResult:
    command_id: str
    status: PublishStatus
    source_system_reference: str | None
    acknowledged_at: datetime | None
    failure_code: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class AdapterCapabilities:
    source_system: str
    supported_read_contracts: frozenset[str]
    supported_write_actions: frozenset[str]


@dataclass(frozen=True)
class AdapterPage:
    records: tuple[dict[str, Any], ...]
    next_cursor: str | None
    source_timestamp: datetime
    contract_version: str


class SignatureVerifier(Protocol):
    def verify(self, key_id: str, content: bytes, signature: str) -> bool: ...


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 3, reset_seconds: float = 30,
                 clock: Callable[[], float] = time.monotonic):
        if failure_threshold < 1 or reset_seconds <= 0:
            raise ValueError("circuit breaker limits must be positive")
        self.failure_threshold = failure_threshold; self.reset_seconds = reset_seconds; self.clock = clock
        self.failures = 0; self.opened_at: float | None = None; self.state = "closed"

    def allow(self) -> bool:
        if self.state != "open": return True
        if self.opened_at is not None and self.clock() - self.opened_at >= self.reset_seconds:
            self.state = "half_open"; return True
        return False

    def success(self) -> None:
        self.failures = 0; self.opened_at = None; self.state = "closed"

    def failure(self) -> None:
        self.failures += 1
        if self.state == "half_open" or self.failures >= self.failure_threshold:
            self.state = "open"; self.opened_at = self.clock()


class CarrierAdapter(ABC):
    """Read/write boundary that rejects unauthorised carrier commands."""

    def __init__(self, capabilities: AdapterCapabilities, verifier: SignatureVerifier,
                 circuit_breaker: CircuitBreaker | None = None):
        self.capabilities = capabilities; self.verifier = verifier
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    def negotiate_contract(self, offered_versions: set[str]) -> str:
        matches = sorted(offered_versions & set(self.capabilities.supported_read_contracts), reverse=True)
        if not matches:
            raise UnsupportedContract(f"{self.capabilities.source_system} has no mutually supported contract")
        return matches[0]

    def fetch(self, contract_version: str, cursor: str | None = None) -> AdapterPage:
        if contract_version not in self.capabilities.supported_read_contracts:
            raise UnsupportedContract(contract_version)
        if not self.circuit_breaker.allow():
            raise AdapterUnavailable("adapter circuit is open")
        try:
            page = self._fetch(contract_version, cursor)
            if page.source_timestamp.tzinfo is None:
                raise ValueError("source timestamp must be timezone-aware")
            self.circuit_breaker.success(); return page
        except Exception:
            self.circuit_breaker.failure(); raise

    def publish(self, command: DeploymentCommand, current_state_version: int) -> PublishResult:
        self._authorize(command, current_state_version)
        if not self.circuit_breaker.allow():
            raise AdapterUnavailable("adapter circuit is open")
        try:
            result = self._publish(command)
            if result.command_id != command.command_id:
                raise AdapterSecurityError("source acknowledgement refers to another command")
            if result.status is PublishStatus.ACKNOWLEDGED and not result.source_system_reference:
                raise AdapterSecurityError("acknowledgement requires a source-system reference")
            self.circuit_breaker.success()
            return result
        except SourceTimeout as exc:
            self.circuit_breaker.failure()
            return PublishResult(command.command_id, PublishStatus.TIMED_OUT, None, None,
                                 "SOURCE_TIMEOUT", str(exc))
        except AdapterSecurityError:
            self.circuit_breaker.failure(); raise
        except Exception as exc:
            self.circuit_breaker.failure()
            return PublishResult(command.command_id, PublishStatus.REJECTED, None, None,
                                 "SOURCE_DEPENDENCY_ERROR", type(exc).__name__)

    def _authorize(self, command: DeploymentCommand, current_state_version: int) -> None:
        now = datetime.now(timezone.utc)
        if command.expires_at.tzinfo is None or command.expires_at <= now:
            raise AdapterSecurityError("deployment command is expired or has a naive expiry")
        if command.target_system != self.capabilities.source_system:
            raise AdapterSecurityError("deployment command targets another source system")
        if command.action not in self.capabilities.supported_write_actions:
            raise AdapterSecurityError("deployment action is not supported")
        if command.state_version != current_state_version:
            raise AdapterSecurityError("deployment command state version is stale")
        if len(command.idempotency_key) < 8:
            raise AdapterSecurityError("deployment command requires an idempotency key")
        if not self.verifier.verify(command.signing_key_id, command.signed_content(), command.signature):
            raise AdapterSecurityError("deployment command signature is invalid")
        duty_managers = {a.actor_subject for a in command.approvals if a.actor_role == "duty-manager"}
        if not duty_managers:
            raise AdapterSecurityError("deployment command lacks duty-manager approval")
        if command.proposed_by in duty_managers or command.requested_by in duty_managers:
            raise AdapterSecurityError("segregation of duties is not satisfied")
        if command.proposed_by == command.requested_by:
            raise AdapterSecurityError("proposer cannot publish the same recovery")

    @abstractmethod
    def _fetch(self, contract_version: str, cursor: str | None) -> AdapterPage: ...

    @abstractmethod
    def _publish(self, command: DeploymentCommand) -> PublishResult: ...


SENSITIVE_KEYS = {"name", "email", "phone", "pnr", "document_number", "medical_detail"}


def redact_for_telemetry(value: Any) -> Any:
    """Remove common PII fields recursively before structured logging."""
    if isinstance(value, dict):
        return {key: "[REDACTED]" if key.lower() in SENSITIVE_KEYS else redact_for_telemetry(item)
                for key, item in value.items()}
    if isinstance(value, list): return [redact_for_telemetry(item) for item in value]
    if isinstance(value, tuple): return tuple(redact_for_telemetry(item) for item in value)
    return value
