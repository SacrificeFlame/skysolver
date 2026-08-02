"""Deployment command and acknowledgement state machine.

This module has no carrier transport dependencies. Adapters may only advance a
command through these transitions after receiving attributable source-system
evidence. A deployment is complete only when every required command is ACKed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import threading
import uuid


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeploymentConflict(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class CommandStatus(str, Enum):
    QUEUED = "queued"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    REJECTED = "rejected"
    TIMED_OUT = "timed_out"
    COMPENSATION_QUEUED = "compensation_queued"
    COMPENSATED = "compensated"
    IRREVERSIBLE = "irreversible"


class DeploymentStatus(str, Enum):
    QUEUED = "queued"
    PUBLISHING = "publishing"
    PARTIAL = "partial"
    COMPLETE = "complete"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"
    REQUIRES_NEW_RECOVERY = "requires_new_recovery"


TERMINAL_FAILURES = {CommandStatus.REJECTED, CommandStatus.TIMED_OUT}


@dataclass
class ResourceCommand:
    command_id: str
    resource_type: str
    resource_id: str
    target_system: str
    action: str
    required: bool = True
    reversible: bool = True
    status: CommandStatus = CommandStatus.QUEUED
    attempts: int = 0
    adapter_reference: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    last_updated_at: str = field(default_factory=now)


@dataclass
class DeploymentAggregate:
    deployment_id: str
    tenant_id: str
    recovery_id: str
    candidate_id: str
    candidate_version: int
    idempotency_key: str
    correlation_id: str
    requested_by: str
    commands: list[ResourceCommand]
    state_version: int = 1
    status: DeploymentStatus = DeploymentStatus.QUEUED
    created_at: str = field(default_factory=now)
    updated_at: str = field(default_factory=now)

    def to_dict(self):
        value = asdict(self)
        value["status"] = self.status.value
        for command in value["commands"]:
            command["status"] = command["status"].value
        value["complete"] = self.status is DeploymentStatus.COMPLETE
        value["partial"] = self.status is DeploymentStatus.PARTIAL
        return value


class DeploymentRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._deployments: dict[str, DeploymentAggregate] = {}
        self._idempotency: dict[tuple[str, str], str] = {}

    def create(self, *, tenant_id: str, recovery_id: str, candidate_id: str, candidate_version: int,
               idempotency_key: str, correlation_id: str, requested_by: str, resources: list[dict]) -> DeploymentAggregate:
        with self._lock:
            key = (tenant_id, idempotency_key)
            if key in self._idempotency:
                return self._deployments[self._idempotency[key]]
            if not resources:
                raise DeploymentConflict("commands_required", "Deployment requires at least one resource command")
            commands = [ResourceCommand(
                command_id=f"CMD-{uuid.uuid4().hex[:12].upper()}",
                resource_type=str(item["resource_type"]),
                resource_id=str(item["resource_id"]),
                target_system=str(item["target_system"]),
                action=str(item["action"]),
                required=bool(item.get("required", True)),
                reversible=bool(item.get("reversible", True)),
            ) for item in resources]
            deployment = DeploymentAggregate(
                deployment_id=f"DPL-{uuid.uuid4().hex[:12].upper()}", tenant_id=tenant_id,
                recovery_id=recovery_id, candidate_id=candidate_id, candidate_version=candidate_version,
                idempotency_key=idempotency_key, correlation_id=correlation_id,
                requested_by=requested_by, commands=commands,
            )
            self._deployments[deployment.deployment_id] = deployment
            self._idempotency[key] = deployment.deployment_id
            return deployment

    def get(self, deployment_id: str) -> DeploymentAggregate:
        try:
            return self._deployments[deployment_id]
        except KeyError as exc:
            raise DeploymentConflict("deployment_not_found", "Deployment not found") from exc

    @staticmethod
    def _version(deployment: DeploymentAggregate, expected_version: int):
        if deployment.state_version != expected_version:
            raise DeploymentConflict("stale_state", f"Expected deployment version {deployment.state_version}")

    @staticmethod
    def _command(deployment: DeploymentAggregate, command_id: str) -> ResourceCommand:
        command = next((item for item in deployment.commands if item.command_id == command_id), None)
        if command is None:
            raise DeploymentConflict("command_not_found", "Resource command not found")
        return command

    @staticmethod
    def _recompute(deployment: DeploymentAggregate):
        required = [item for item in deployment.commands if item.required]
        statuses = {item.status for item in required}
        if required and all(item.status is CommandStatus.ACKNOWLEDGED for item in required):
            deployment.status = DeploymentStatus.COMPLETE
        elif any(item.status in TERMINAL_FAILURES for item in required):
            deployment.status = DeploymentStatus.PARTIAL if any(item.status is CommandStatus.ACKNOWLEDGED for item in required) else DeploymentStatus.FAILED
        elif any(item.status is CommandStatus.SENT for item in required):
            deployment.status = DeploymentStatus.PUBLISHING
        elif statuses == {CommandStatus.COMPENSATED}:
            deployment.status = DeploymentStatus.COMPENSATED

    @staticmethod
    def _advance(deployment: DeploymentAggregate):
        deployment.state_version += 1
        deployment.updated_at = now()

    def mark_sent(self, deployment_id: str, command_id: str, expected_version: int, adapter_reference: str) -> DeploymentAggregate:
        with self._lock:
            deployment = self.get(deployment_id); self._version(deployment, expected_version)
            command = self._command(deployment, command_id)
            if command.status is not CommandStatus.QUEUED:
                raise DeploymentConflict("invalid_transition", "Only queued commands can be sent")
            command.status = CommandStatus.SENT; command.attempts += 1
            command.adapter_reference = adapter_reference; command.last_updated_at = now()
            self._recompute(deployment); self._advance(deployment); return deployment

    def acknowledge(self, deployment_id: str, command_id: str, expected_version: int, *, accepted: bool,
                    adapter_reference: str, failure_code: str | None = None, failure_detail: str | None = None) -> DeploymentAggregate:
        with self._lock:
            deployment = self.get(deployment_id); self._version(deployment, expected_version)
            command = self._command(deployment, command_id)
            if command.status is not CommandStatus.SENT:
                raise DeploymentConflict("invalid_transition", "Only sent commands can receive an acknowledgement")
            command.status = CommandStatus.ACKNOWLEDGED if accepted else CommandStatus.REJECTED
            command.adapter_reference = adapter_reference
            command.failure_code = None if accepted else (failure_code or "SOURCE_SYSTEM_REJECTED")
            command.failure_detail = None if accepted else failure_detail
            command.last_updated_at = now()
            self._recompute(deployment); self._advance(deployment); return deployment

    def timeout(self, deployment_id: str, command_id: str, expected_version: int) -> DeploymentAggregate:
        with self._lock:
            deployment = self.get(deployment_id); self._version(deployment, expected_version)
            command = self._command(deployment, command_id)
            if command.status is not CommandStatus.SENT:
                raise DeploymentConflict("invalid_transition", "Only sent commands can time out")
            command.status = CommandStatus.TIMED_OUT; command.failure_code = "ACK_TIMEOUT"; command.last_updated_at = now()
            self._recompute(deployment); self._advance(deployment); return deployment

    def retry(self, deployment_id: str, command_id: str, expected_version: int) -> DeploymentAggregate:
        with self._lock:
            deployment = self.get(deployment_id); self._version(deployment, expected_version)
            command = self._command(deployment, command_id)
            if command.status not in TERMINAL_FAILURES:
                raise DeploymentConflict("retry_not_allowed", "Only rejected or timed-out commands are retryable")
            command.status = CommandStatus.QUEUED; command.failure_code = None; command.failure_detail = None
            command.adapter_reference = None; command.last_updated_at = now()
            deployment.status = DeploymentStatus.QUEUED; self._advance(deployment); return deployment

    def compensate(self, deployment_id: str, expected_version: int) -> DeploymentAggregate:
        with self._lock:
            deployment = self.get(deployment_id); self._version(deployment, expected_version)
            acknowledged = [item for item in deployment.commands if item.status is CommandStatus.ACKNOWLEDGED]
            if not acknowledged:
                raise DeploymentConflict("compensation_not_required", "No acknowledged command requires compensation")
            irreversible = [item for item in acknowledged if not item.reversible]
            for command in acknowledged:
                command.status = CommandStatus.IRREVERSIBLE if not command.reversible else CommandStatus.COMPENSATION_QUEUED
                command.last_updated_at = now()
            deployment.status = DeploymentStatus.REQUIRES_NEW_RECOVERY if irreversible else DeploymentStatus.COMPENSATING
            self._advance(deployment); return deployment

    def acknowledge_compensation(self, deployment_id: str, command_id: str, expected_version: int, adapter_reference: str) -> DeploymentAggregate:
        with self._lock:
            deployment = self.get(deployment_id); self._version(deployment, expected_version)
            command = self._command(deployment, command_id)
            if command.status is not CommandStatus.COMPENSATION_QUEUED:
                raise DeploymentConflict("invalid_transition", "Command has no pending compensation")
            command.status = CommandStatus.COMPENSATED; command.adapter_reference = adapter_reference; command.last_updated_at = now()
            if all(item.status in {CommandStatus.COMPENSATED, CommandStatus.REJECTED, CommandStatus.TIMED_OUT} for item in deployment.commands):
                deployment.status = DeploymentStatus.COMPENSATED
            self._advance(deployment); return deployment
