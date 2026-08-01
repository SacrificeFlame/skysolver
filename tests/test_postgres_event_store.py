from datetime import datetime, timezone

import pytest

from state.postgres_event_store import OptimisticConcurrencyError, OutboxPublisher, PostgresEventRepository, ProjectionConsumer


class Cursor:
    def __init__(self, fetchone_values=None, fetchall_value=None, rowcount=1):
        self.fetchone_values = list(fetchone_values or [])
        self.fetchall_value = fetchall_value or []
        self.rowcount = rowcount
        self.executed = []

    def execute(self, sql, parameters=()):
        self.executed.append((" ".join(sql.split()), parameters))

    def fetchone(self):
        return self.fetchone_values.pop(0) if self.fetchone_values else None

    def fetchall(self):
        return self.fetchall_value


class Connection:
    def __init__(self, cursor):
        self._cursor = cursor; self.commits = 0; self.rollbacks = 0; self.closed = 0

    def cursor(self): return self._cursor
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def close(self): self.closed += 1


def append_args():
    return dict(tenant_id="airline", aggregate_type="recovery", aggregate_id="R1", expected_version=0,
                partition_key="airline:DEL:R1", event_type="RecoveryCreated", schema_version="recovery.v1",
                occurred_at=datetime(2026, 8, 1, tzinfo=timezone.utc), correlation_id="correlation-1",
                causation_id=None, actor_subject="scheduler", payload={"status": "created"}, topic="recovery.events.v1")


def test_append_commits_stream_event_and_outbox_atomically():
    cursor = Cursor(fetchone_values=[(0,)]); connection = Connection(cursor)
    event = PostgresEventRepository(lambda: connection).append(**append_args())
    assert event.aggregate_version == 1
    assert connection.commits == 1 and connection.rollbacks == 0 and connection.closed == 1
    sql = " ".join(statement for statement, _ in cursor.executed)
    assert "FOR UPDATE" in sql
    assert "INSERT INTO operational_event" in sql
    assert "INSERT INTO transactional_outbox" in sql
    assert sql.index("INSERT INTO operational_event") < sql.index("INSERT INTO transactional_outbox")


def test_stale_append_rolls_back_without_event_or_outbox():
    cursor = Cursor(fetchone_values=[(4,)]); connection = Connection(cursor)
    with pytest.raises(OptimisticConcurrencyError):
        PostgresEventRepository(lambda: connection).append(**append_args())
    assert connection.rollbacks == 1 and connection.commits == 0
    assert not any("operational_event" in statement for statement, _ in cursor.executed)


class RepositoryStub:
    def __init__(self):
        self.rows = [{"event_id": "E1", "tenant_id": "airline", "topic": "events", "partition_key": "DEL",
                      "envelope": {"correlation_id": "C1"}, "attempt_count": 0},
                     {"event_id": "E2", "tenant_id": "airline", "topic": "events", "partition_key": "BOM",
                      "envelope": {"correlation_id": "C2"}, "attempt_count": 2}]
        self.published = []; self.failed = []

    def claim_outbox(self, worker_id, batch_size): return self.rows
    def mark_published(self, event_id, worker_id): self.published.append((event_id, worker_id))
    def mark_publish_failed(self, event_id, worker_id, error, attempt): self.failed.append((event_id, worker_id, attempt))


class ProducerStub:
    def publish(self, topic, key, value, headers):
        if headers["event_id"] == "E2": raise RuntimeError("broker unavailable")
        return "broker-ack"


def test_outbox_marks_only_broker_acked_events_published():
    repository = RepositoryStub()
    result = OutboxPublisher(repository, ProducerStub(), "publisher-1").publish_batch()
    assert result == {"claimed": 2, "published": 1, "failed": 1}
    assert repository.published == [("E1", "publisher-1")]
    assert repository.failed == [("E2", "publisher-1", 2)]


def test_projection_and_checkpoint_commit_together():
    cursor = Cursor(fetchone_values=[("E1",)]); connection = Connection(cursor); projected = []
    applied = ProjectionConsumer(lambda: connection, "overview-v1").apply(tenant_id="airline", topic="events",
        partition=0, offset=42, event_id="E1", projection=lambda tx: projected.append(tx))
    assert applied is True and projected == [cursor] and connection.commits == 1
    assert any("consumer_checkpoint" in statement for statement, _ in cursor.executed)


def test_duplicate_event_skips_projection_but_commits_idempotency_check():
    cursor = Cursor(fetchone_values=[None]); connection = Connection(cursor); projected = []
    applied = ProjectionConsumer(lambda: connection, "overview-v1").apply(tenant_id="airline", topic="events",
        partition=0, offset=42, event_id="E1", projection=lambda tx: projected.append(tx))
    assert applied is False and projected == [] and connection.commits == 1
