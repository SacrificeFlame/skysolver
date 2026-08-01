from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from state.durable_recovery_store import DurableRecoveryRepository, IdempotencyConflict, WorkflowMutation
from state.postgres_event_store import OptimisticConcurrencyError


class Cursor:
    def __init__(self, fetchone_values=None, fetchall_value=None):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_value = list(fetchall_value or [])
        self.executed = []
        self.rowcount = 1

    def execute(self, sql, parameters=()):
        self.executed.append((" ".join(sql.split()), parameters))

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return self.fetchall_value


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = self.rollbacks = self.closed = 0

    def cursor(self): return self._cursor
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): self.closed += 1


def mutation(**changes):
    values = dict(
        tenant_id="airline-1", recovery_id="REC-1", expected_version=0,
        idempotency_key="create-rec-1", command_type="create_recovery",
        event_type="RecoveryCreated", actor_subject="scheduler-1",
        correlation_id="00000000-0000-4000-8000-000000000001", causation_id=None,
        partition_id="DEL", request={"disruption_id": "DSP-1"},
        snapshot={"id": "REC-1", "status": "solving"},
        response={"action_status": "accepted"},
        occurred_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    values.update(changes)
    return WorkflowMutation(**values)


def test_mutation_commits_event_outbox_snapshot_and_receipt_atomically():
    cursor = Cursor(fetchone_values=[("create-rec-1",), (0,)])
    connection = Connection(cursor)
    receipt = DurableRecoveryRepository(lambda: connection).mutate(mutation())
    assert receipt.state_version == 1 and receipt.response["state_version"] == 1
    assert receipt.replayed is False
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed == 1
    sql = " ".join(statement for statement, _ in cursor.executed)
    expected_order = ["INSERT INTO workflow_command", "FOR UPDATE", "INSERT INTO operational_event",
                      "INSERT INTO transactional_outbox", "INSERT INTO recovery_workflow_snapshot",
                      "UPDATE workflow_command SET status='completed'"]
    positions = [sql.index(item) for item in expected_order]
    assert positions == sorted(positions)


def test_stale_version_rolls_back_before_event_or_projection_write():
    cursor = Cursor(fetchone_values=[("create-rec-1",), (3,)])
    connection = Connection(cursor)
    with pytest.raises(OptimisticConcurrencyError):
        DurableRecoveryRepository(lambda: connection).mutate(mutation())
    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("INSERT INTO operational_event" in sql for sql, _ in cursor.executed)
    assert not any("recovery_workflow_snapshot" in sql for sql, _ in cursor.executed)


def test_completed_idempotent_retry_returns_original_response_without_new_event():
    command = {"command_type": "create_recovery", "expected_version": 0,
               "recovery_id": "REC-1", "request": {"disruption_id": "DSP-1"}}
    command_hash = hashlib.sha256(json.dumps(command, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    original = {"action_status": "accepted", "state_version": 1}
    cursor = Cursor(fetchone_values=[None, (command_hash, "completed", "event-1", 1, original)])
    connection = Connection(cursor)
    receipt = DurableRecoveryRepository(lambda: connection).mutate(mutation())
    assert receipt.replayed is True and receipt.response == original
    assert not any("INSERT INTO operational_event" in sql for sql, _ in cursor.executed)


def test_reusing_idempotency_key_for_different_command_is_rejected():
    cursor = Cursor(fetchone_values=[None, ("different-hash", "completed", "event-1", 1, {})])
    connection = Connection(cursor)
    with pytest.raises(IdempotencyConflict):
        DurableRecoveryRepository(lambda: connection).mutate(mutation())
    assert connection.rollbacks == 1


def test_replay_reduces_events_in_aggregate_version_order():
    events = [("RecoveryCreated", {"snapshot": {"status": "solving"}}, 1),
              ("CandidateSelected", {"snapshot": {"status": "awaiting_validation"}}, 2)]
    cursor = Cursor(fetchall_value=events)
    connection = Connection(cursor)
    result = DurableRecoveryRepository(lambda: connection).replay(
        "airline-1", "REC-1",
        lambda state, _event_type, payload: {**state, **payload["snapshot"]},
    )
    assert result == {"state_version": 2, "snapshot": {"status": "awaiting_validation"}}
    assert "ORDER BY aggregate_version" in cursor.executed[-1][0]


def test_migration_enforces_rls_and_completed_receipt_invariant():
    migration = Path("infrastructure/migrations/004_durable_workflow_commands.sql").read_text(encoding="utf-8")
    assert "ENABLE ROW LEVEL SECURITY" in migration and "WITH CHECK" in migration
    assert "status = 'completed'" in migration
    assert "PRIMARY KEY (tenant_id, idempotency_key)" in migration
