"""Atomic Aurora persistence boundary for recovery workflow mutations.

This repository persists an already-authorized transition as one transaction:
the idempotency receipt, aggregate event, MSK outbox record, and rebuildable
workflow snapshot either commit together or all roll back.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Callable

from state.postgres_event_store import OptimisticConcurrencyError


class IdempotencyConflict(RuntimeError):
    """The same idempotency key was reused for a different command."""


class MutationInProgress(RuntimeError):
    """A matching command exists but has not completed."""


@dataclass(frozen=True)
class WorkflowMutation:
    tenant_id: str
    recovery_id: str
    expected_version: int
    idempotency_key: str
    command_type: str
    event_type: str
    actor_subject: str
    correlation_id: str
    causation_id: str | None
    partition_id: str
    request: dict[str, Any]
    snapshot: dict[str, Any]
    response: dict[str, Any]
    topic: str = "recovery.events.v1"
    schema_version: str = "recovery.v1"
    occurred_at: datetime | None = None

    def validate(self) -> None:
        if not self.tenant_id or not self.recovery_id:
            raise ValueError("tenant_id and recovery_id are required")
        if self.expected_version < 0:
            raise ValueError("expected_version cannot be negative")
        if len(self.idempotency_key) < 8:
            raise ValueError("idempotency_key must contain at least 8 characters")
        if self.occurred_at is not None and self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")


@dataclass(frozen=True)
class MutationReceipt:
    event_id: str
    state_version: int
    response: dict[str, Any]
    replayed: bool


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class DurableRecoveryRepository:
    """Persists workflow commands and projections in a single transaction."""

    durable_authoritative = True

    def __init__(self, connection_factory: Callable[[], Any]):
        self._connection_factory = connection_factory

    def mutate(self, mutation: WorkflowMutation) -> MutationReceipt:
        mutation.validate()
        command_hash = _digest({
            "command_type": mutation.command_type,
            "expected_version": mutation.expected_version,
            "recovery_id": mutation.recovery_id,
            "request": mutation.request,
        })
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)", (mutation.tenant_id,))
            cursor.execute(
                "INSERT INTO workflow_command "
                "(tenant_id,idempotency_key,recovery_id,command_type,command_sha256,status) "
                "VALUES (%s,%s,%s,%s,%s,'processing') ON CONFLICT DO NOTHING RETURNING idempotency_key",
                (mutation.tenant_id, mutation.idempotency_key, mutation.recovery_id,
                 mutation.command_type, command_hash),
            )
            if cursor.fetchone() is None:
                receipt = self._existing_receipt(cursor, mutation, command_hash)
                connection.commit()
                return receipt

            cursor.execute(
                "INSERT INTO aggregate_stream (tenant_id,aggregate_type,aggregate_id,current_version) "
                "VALUES (%s,'recovery',%s,0) ON CONFLICT DO NOTHING",
                (mutation.tenant_id, mutation.recovery_id),
            )
            cursor.execute(
                "SELECT current_version FROM aggregate_stream WHERE tenant_id=%s "
                "AND aggregate_type='recovery' AND aggregate_id=%s FOR UPDATE",
                (mutation.tenant_id, mutation.recovery_id),
            )
            version_row = cursor.fetchone()
            current_version = int(version_row[0]) if version_row else 0
            if current_version != mutation.expected_version:
                raise OptimisticConcurrencyError(
                    f"expected aggregate version {mutation.expected_version}, found {current_version}"
                )

            new_version = current_version + 1
            event_id = str(uuid.uuid4())
            occurred_at = mutation.occurred_at or datetime.now(timezone.utc)
            event_payload = {
                "command_type": mutation.command_type,
                "request": mutation.request,
                "snapshot": mutation.snapshot,
                "response": mutation.response,
            }
            partition_key = f"{mutation.tenant_id}:{mutation.partition_id}:{mutation.recovery_id}"
            envelope = {
                "event_id": event_id, "tenant_id": mutation.tenant_id,
                "aggregate_type": "recovery", "aggregate_id": mutation.recovery_id,
                "aggregate_version": new_version, "partition_key": partition_key,
                "event_type": mutation.event_type, "schema_version": mutation.schema_version,
                "occurred_at": occurred_at.isoformat(), "correlation_id": mutation.correlation_id,
                "causation_id": mutation.causation_id, "actor_subject": mutation.actor_subject,
                "payload": event_payload,
            }
            response = {**mutation.response, "state_version": new_version}

            cursor.execute(
                "INSERT INTO operational_event "
                "(event_id,tenant_id,aggregate_type,aggregate_id,aggregate_version,partition_key,event_type,"
                "schema_version,occurred_at,correlation_id,causation_id,actor_subject,payload,payload_sha256) "
                "VALUES (%s,%s,'recovery',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (event_id, mutation.tenant_id, mutation.recovery_id, new_version, partition_key,
                 mutation.event_type, mutation.schema_version, occurred_at, mutation.correlation_id,
                 mutation.causation_id, mutation.actor_subject, _canonical(event_payload), _digest(event_payload)),
            )
            cursor.execute(
                "UPDATE aggregate_stream SET current_version=%s,updated_at=clock_timestamp() "
                "WHERE tenant_id=%s AND aggregate_type='recovery' AND aggregate_id=%s AND current_version=%s",
                (new_version, mutation.tenant_id, mutation.recovery_id, current_version),
            )
            if cursor.rowcount != 1:
                raise OptimisticConcurrencyError("aggregate version changed during mutation")
            cursor.execute(
                "INSERT INTO transactional_outbox (event_id,tenant_id,topic,partition_key,envelope) "
                "VALUES (%s,%s,%s,%s,%s::jsonb)",
                (event_id, mutation.tenant_id, mutation.topic, partition_key, _canonical(envelope)),
            )
            cursor.execute(
                "INSERT INTO recovery_workflow_snapshot "
                "(tenant_id,recovery_id,state_version,snapshot,last_event_id,updated_at) "
                "VALUES (%s,%s,%s,%s::jsonb,%s,clock_timestamp()) "
                "ON CONFLICT (tenant_id,recovery_id) DO UPDATE SET "
                "state_version=EXCLUDED.state_version,snapshot=EXCLUDED.snapshot,last_event_id=EXCLUDED.last_event_id,"
                "updated_at=EXCLUDED.updated_at WHERE recovery_workflow_snapshot.state_version=%s",
                (mutation.tenant_id, mutation.recovery_id, new_version,
                 _canonical(mutation.snapshot), event_id, current_version),
            )
            cursor.execute(
                "UPDATE workflow_command SET status='completed',event_id=%s,state_version=%s,response=%s::jsonb,"
                "completed_at=clock_timestamp() WHERE tenant_id=%s AND idempotency_key=%s AND status='processing'",
                (event_id, new_version, _canonical(response), mutation.tenant_id, mutation.idempotency_key),
            )
            if cursor.rowcount != 1:
                raise MutationInProgress("idempotency reservation was lost")
            connection.commit()
            return MutationReceipt(event_id, new_version, response, False)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _existing_receipt(cursor: Any, mutation: WorkflowMutation, command_hash: str) -> MutationReceipt:
        cursor.execute(
            "SELECT command_sha256,status,event_id,state_version,response FROM workflow_command "
            "WHERE tenant_id=%s AND idempotency_key=%s FOR UPDATE",
            (mutation.tenant_id, mutation.idempotency_key),
        )
        row = cursor.fetchone()
        if row is None:
            raise MutationInProgress("idempotency reservation disappeared")
        existing_hash, status, event_id, state_version, response = row
        if existing_hash != command_hash:
            raise IdempotencyConflict("idempotency key was already used for a different command")
        if status != "completed":
            raise MutationInProgress("matching workflow command is still processing")
        decoded = response if isinstance(response, dict) else json.loads(response)
        return MutationReceipt(str(event_id), int(state_version), decoded, True)

    def get_snapshot(self, tenant_id: str, recovery_id: str) -> dict[str, Any] | None:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)", (tenant_id,))
            cursor.execute(
                "SELECT state_version,snapshot,last_event_id,updated_at FROM recovery_workflow_snapshot "
                "WHERE tenant_id=%s AND recovery_id=%s", (tenant_id, recovery_id),
            )
            row = cursor.fetchone()
            connection.commit()
            if row is None:
                return None
            snapshot = row[1] if isinstance(row[1], dict) else json.loads(row[1])
            return {"state_version": int(row[0]), "snapshot": snapshot,
                    "last_event_id": str(row[2]), "updated_at": row[3]}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def replay(self, tenant_id: str, recovery_id: str,
               reducer: Callable[[dict[str, Any], str, dict[str, Any]], dict[str, Any]],
               initial: dict[str, Any] | None = None) -> dict[str, Any]:
        """Rebuild a recovery deterministically from ordered immutable events."""
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)", (tenant_id,))
            cursor.execute(
                "SELECT event_type,payload,aggregate_version FROM operational_event "
                "WHERE tenant_id=%s AND aggregate_type='recovery' AND aggregate_id=%s "
                "ORDER BY aggregate_version", (tenant_id, recovery_id),
            )
            state = dict(initial or {})
            version = 0
            for event_type, payload, aggregate_version in cursor.fetchall():
                decoded = payload if isinstance(payload, dict) else json.loads(payload)
                state = reducer(state, str(event_type), decoded)
                version = int(aggregate_version)
            connection.commit()
            return {"state_version": version, "snapshot": state}
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
