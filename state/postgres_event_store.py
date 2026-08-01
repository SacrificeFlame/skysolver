"""Aurora PostgreSQL event store, outbox and projection transaction boundary.

The implementation accepts a DB-API connection factory so production uses
psycopg pools while unit tests can verify transaction behavior without a live
database. MSK transport is injected behind a producer protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import uuid
from typing import Any, Callable, Protocol


class OptimisticConcurrencyError(Exception):
    pass


class OutboxPublishError(Exception):
    pass


@dataclass(frozen=True)
class OperationalEvent:
    event_id: str
    tenant_id: str
    aggregate_type: str
    aggregate_id: str
    aggregate_version: int
    partition_key: str
    event_type: str
    schema_version: str
    occurred_at: datetime
    correlation_id: str
    causation_id: str | None
    actor_subject: str
    payload: dict[str, Any]
    topic: str

    def envelope(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id, "tenant_id": self.tenant_id,
            "aggregate_type": self.aggregate_type, "aggregate_id": self.aggregate_id,
            "aggregate_version": self.aggregate_version, "partition_key": self.partition_key,
            "event_type": self.event_type, "schema_version": self.schema_version,
            "occurred_at": self.occurred_at.isoformat(), "correlation_id": self.correlation_id,
            "causation_id": self.causation_id, "actor_subject": self.actor_subject, "payload": self.payload,
        }


class BrokerProducer(Protocol):
    def publish(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> str: ...


class PostgresEventRepository:
    def __init__(self, connection_factory: Callable[[], Any]):
        self._connection_factory = connection_factory

    @staticmethod
    def _payload(event: OperationalEvent):
        encoded = json.dumps(event.payload, sort_keys=True, separators=(",", ":"), default=str)
        return encoded, hashlib.sha256(encoded.encode()).hexdigest()

    def append(self, *, tenant_id: str, aggregate_type: str, aggregate_id: str, expected_version: int,
               partition_key: str, event_type: str, schema_version: str, occurred_at: datetime,
               correlation_id: str, causation_id: str | None, actor_subject: str, payload: dict[str, Any],
               topic: str) -> OperationalEvent:
        if occurred_at.tzinfo is None:
            raise ValueError("occurred_at must be timezone-aware")
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)", (tenant_id,))
            cursor.execute(
                "INSERT INTO aggregate_stream (tenant_id, aggregate_type, aggregate_id, current_version) VALUES (%s,%s,%s,0) ON CONFLICT DO NOTHING",
                (tenant_id, aggregate_type, aggregate_id),
            )
            cursor.execute(
                "SELECT current_version FROM aggregate_stream WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_id=%s FOR UPDATE",
                (tenant_id, aggregate_type, aggregate_id),
            )
            row = cursor.fetchone()
            current_version = int(row[0]) if row else 0
            if current_version != expected_version:
                raise OptimisticConcurrencyError(f"expected aggregate version {expected_version}, found {current_version}")
            event = OperationalEvent(str(uuid.uuid4()), tenant_id, aggregate_type, aggregate_id, current_version + 1,
                                     partition_key, event_type, schema_version, occurred_at, correlation_id,
                                     causation_id, actor_subject, payload, topic)
            payload_json, digest = self._payload(event)
            cursor.execute(
                "INSERT INTO operational_event (event_id,tenant_id,aggregate_type,aggregate_id,aggregate_version,partition_key,event_type,schema_version,occurred_at,correlation_id,causation_id,actor_subject,payload,payload_sha256) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s)",
                (event.event_id, tenant_id, aggregate_type, aggregate_id, event.aggregate_version, partition_key,
                 event_type, schema_version, occurred_at, correlation_id, causation_id, actor_subject, payload_json, digest),
            )
            cursor.execute(
                "UPDATE aggregate_stream SET current_version=%s, updated_at=clock_timestamp() WHERE tenant_id=%s AND aggregate_type=%s AND aggregate_id=%s AND current_version=%s",
                (event.aggregate_version, tenant_id, aggregate_type, aggregate_id, current_version),
            )
            cursor.execute(
                "INSERT INTO transactional_outbox (event_id,tenant_id,topic,partition_key,envelope) VALUES (%s,%s,%s,%s,%s::jsonb)",
                (event.event_id, tenant_id, topic, partition_key, json.dumps(event.envelope(), sort_keys=True, default=str)),
            )
            connection.commit()
            return event
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_outbox(self, worker_id: str, batch_size: int = 100) -> list[dict[str, Any]]:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor()
            cursor.execute(
                "WITH claimable AS (SELECT event_id FROM transactional_outbox WHERE published_at IS NULL AND claimed_at IS NULL AND next_attempt_at <= clock_timestamp() ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT %s) UPDATE transactional_outbox o SET claimed_at=clock_timestamp(), claimed_by=%s FROM claimable c WHERE o.event_id=c.event_id RETURNING o.event_id,o.tenant_id,o.topic,o.partition_key,o.envelope,o.attempt_count",
                (batch_size, worker_id),
            )
            columns = ["event_id", "tenant_id", "topic", "partition_key", "envelope", "attempt_count"]
            rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
            connection.commit()
            return rows
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()

    def mark_published(self, event_id: str, worker_id: str):
        self._update_claim(event_id, worker_id,
            "UPDATE transactional_outbox SET published_at=clock_timestamp(),claimed_at=NULL,claimed_by=NULL,last_error=NULL WHERE event_id=%s AND claimed_by=%s AND published_at IS NULL")

    def mark_publish_failed(self, event_id: str, worker_id: str, error: str, attempt_count: int):
        delay_seconds = min(300, 2 ** min(attempt_count + 1, 8))
        self._update_claim(event_id, worker_id,
            "UPDATE transactional_outbox SET attempt_count=attempt_count+1,next_attempt_at=clock_timestamp()+(%s * interval '1 second'),claimed_at=NULL,claimed_by=NULL,last_error=%s WHERE event_id=%s AND claimed_by=%s AND published_at IS NULL",
            (delay_seconds, error[:2000], event_id, worker_id))

    def _update_claim(self, event_id: str, worker_id: str, sql: str, parameters=None):
        connection = self._connection_factory()
        try:
            cursor = connection.cursor(); cursor.execute(sql, parameters or (event_id, worker_id))
            if cursor.rowcount != 1:
                raise OutboxPublishError("Outbox claim is missing, stale or owned by another worker")
            connection.commit()
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()


class OutboxPublisher:
    def __init__(self, repository: PostgresEventRepository, producer: BrokerProducer, worker_id: str):
        self.repository = repository; self.producer = producer; self.worker_id = worker_id

    def publish_batch(self, batch_size: int = 100) -> dict[str, int]:
        rows = self.repository.claim_outbox(self.worker_id, batch_size)
        published = failed = 0
        for row in rows:
            envelope = row["envelope"] if isinstance(row["envelope"], dict) else json.loads(row["envelope"])
            try:
                self.producer.publish(row["topic"], row["partition_key"], json.dumps(envelope, sort_keys=True).encode(),
                                      {"event_id": str(row["event_id"]), "tenant_id": row["tenant_id"], "correlation_id": envelope["correlation_id"]})
                self.repository.mark_published(str(row["event_id"]), self.worker_id); published += 1
            except Exception as exc:
                self.repository.mark_publish_failed(str(row["event_id"]), self.worker_id, str(exc), int(row["attempt_count"])); failed += 1
        return {"claimed": len(rows), "published": published, "failed": failed}


class ProjectionConsumer:
    def __init__(self, connection_factory: Callable[[], Any], consumer_group: str):
        self._connection_factory = connection_factory; self.consumer_group = consumer_group

    def apply(self, *, tenant_id: str, topic: str, partition: int, offset: int, event_id: str,
              projection: Callable[[Any], None]) -> bool:
        connection = self._connection_factory()
        try:
            cursor = connection.cursor(); cursor.execute("SELECT set_config('skysolver.tenant_id', %s, true)", (tenant_id,))
            cursor.execute("INSERT INTO consumed_event (tenant_id,consumer_group,event_id) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id", (tenant_id, self.consumer_group, event_id))
            if cursor.fetchone() is None:
                connection.commit(); return False
            projection(cursor)
            cursor.execute("INSERT INTO consumer_checkpoint (tenant_id,consumer_group,topic,partition_number,kafka_offset) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,consumer_group,topic,partition_number) DO UPDATE SET kafka_offset=EXCLUDED.kafka_offset,updated_at=clock_timestamp() WHERE consumer_checkpoint.kafka_offset < EXCLUDED.kafka_offset", (tenant_id, self.consumer_group, topic, partition, offset))
            connection.commit(); return True
        except Exception:
            connection.rollback(); raise
        finally:
            connection.close()
