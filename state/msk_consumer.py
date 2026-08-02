"""Resilient MSK consumer loop for operational events.

Offsets are committed only after the idempotent Aurora projection transaction
commits. Poison messages are committed only after their DLQ publication is
acknowledged, so a broker or database failure cannot silently lose work.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import signal
import threading
from typing import Any, Callable, Protocol


@dataclass(frozen=True)
class BrokerMessage:
    topic: str
    partition: int
    offset: int
    key: bytes | str | None
    value: bytes
    lag: int | None = None


class ConsumerClient(Protocol):
    def poll(self, timeout_seconds: float) -> BrokerMessage | None: ...
    def commit(self, message: BrokerMessage) -> None: ...
    def close(self) -> None: ...


class ProducerClient(Protocol):
    def publish(self, topic: str, key: str, value: bytes, headers: dict[str, str]) -> str: ...


class ProjectionApplier(Protocol):
    def apply(self, *, tenant_id: str, topic: str, partition: int, offset: int,
              event_id: str, projection: Callable[[Any], None]) -> bool: ...


class EventSchemaError(ValueError):
    pass


REQUIRED_FIELDS = {
    "event_id", "tenant_id", "aggregate_type", "aggregate_id", "aggregate_version",
    "partition_key", "event_type", "schema_version", "occurred_at", "correlation_id",
    "actor_subject", "payload",
}


def decode_event(value: bytes) -> dict[str, Any]:
    try:
        envelope = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EventSchemaError("event is not valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict):
        raise EventSchemaError("event envelope must be an object")
    missing = sorted(REQUIRED_FIELDS.difference(envelope))
    if missing:
        raise EventSchemaError("event envelope is missing: " + ", ".join(missing))
    if not isinstance(envelope["aggregate_version"], int) or envelope["aggregate_version"] <= 0:
        raise EventSchemaError("aggregate_version must be a positive integer")
    if not isinstance(envelope["payload"], dict):
        raise EventSchemaError("payload must be an object")
    return envelope


class DurableEventConsumer:
    def __init__(self, *, consumer: ConsumerClient, projection: ProjectionApplier,
                 dlq_producer: ProducerClient,
                 handler: Callable[[Any, dict[str, Any]], None],
                 consumer_group: str,
                 lag_observer: Callable[[str, int, int], None] | None = None):
        self.consumer = consumer
        self.projection = projection
        self.dlq_producer = dlq_producer
        self.handler = handler
        self.consumer_group = consumer_group
        self.lag_observer = lag_observer
        self._draining = threading.Event()

    def request_drain(self) -> None:
        self._draining.set()

    def install_signal_handlers(self) -> None:
        signal.signal(signal.SIGTERM, lambda *_: self.request_drain())
        if hasattr(signal, "SIGINT"):
            signal.signal(signal.SIGINT, lambda *_: self.request_drain())

    @staticmethod
    def _message_key(message: BrokerMessage) -> str:
        if isinstance(message.key, bytes):
            return message.key.decode("utf-8", errors="strict")
        return message.key or ""

    def process_one(self, timeout_seconds: float = 1.0) -> str:
        message = self.consumer.poll(timeout_seconds)
        if message is None:
            return "idle"
        if self.lag_observer is not None and message.lag is not None:
            self.lag_observer(message.topic, message.partition, message.lag)
        try:
            envelope = decode_event(message.value)
            key = self._message_key(message)
            if key and key != envelope["partition_key"]:
                raise EventSchemaError("broker key does not match envelope partition_key")
        except (EventSchemaError, UnicodeDecodeError) as exc:
            self._publish_dlq(message, exc)
            self.consumer.commit(message)
            return "dead_lettered"

        applied = self.projection.apply(
            tenant_id=envelope["tenant_id"], topic=message.topic,
            partition=message.partition, offset=message.offset,
            event_id=envelope["event_id"],
            projection=lambda cursor: self.handler(cursor, envelope),
        )
        self.consumer.commit(message)
        return "applied" if applied else "duplicate"

    def _publish_dlq(self, message: BrokerMessage, error: Exception) -> None:
        digest = hashlib.sha256(message.value).hexdigest()
        body = {
            "source_topic": message.topic,
            "source_partition": message.partition,
            "source_offset": message.offset,
            "consumer_group": self.consumer_group,
            "reason": type(error).__name__,
            "detail": str(error),
            "payload_sha256": digest,
        }
        self.dlq_producer.publish(
            f"{message.topic}.dlq", self._message_key(message) or digest,
            json.dumps(body, sort_keys=True).encode("utf-8"),
            {"source_topic": message.topic, "payload_sha256": digest},
        )

    def run(self, timeout_seconds: float = 1.0) -> None:
        try:
            while not self._draining.is_set():
                self.process_one(timeout_seconds)
        finally:
            self.consumer.close()
