import json

import pytest

from state.msk_consumer import BrokerMessage, DurableEventConsumer


def event(**changes):
    value = {
        "event_id": "event-1", "tenant_id": "airline-1", "aggregate_type": "recovery",
        "aggregate_id": "REC-1", "aggregate_version": 1,
        "partition_key": "airline-1:DEL:REC-1", "event_type": "RecoveryCreated",
        "schema_version": "recovery.v1", "occurred_at": "2026-08-01T00:00:00+00:00",
        "correlation_id": "correlation-1", "causation_id": None,
        "actor_subject": "scheduler-1", "payload": {"status": "solving"},
    }
    value.update(changes)
    return value


class Consumer:
    def __init__(self, messages):
        self.messages = list(messages); self.committed = []; self.closed = False
    def poll(self, _timeout): return self.messages.pop(0) if self.messages else None
    def commit(self, message): self.committed.append((message.partition, message.offset))
    def close(self): self.closed = True


class Projection:
    def __init__(self, result=True, error=None): self.result=result; self.error=error; self.calls=[]
    def apply(self, **values):
        self.calls.append(values)
        if self.error: raise self.error
        values["projection"]("database-cursor")
        return self.result


class Producer:
    def __init__(self, error=None): self.calls=[]; self.error=error
    def publish(self, topic, key, value, headers):
        self.calls.append((topic,key,json.loads(value),headers))
        if self.error: raise self.error
        return "broker-ack"


def message(value=None, **changes):
    values = dict(topic="recovery.events.v1", partition=2, offset=41,
                  key=b"airline-1:DEL:REC-1",
                  value=json.dumps(value or event()).encode(), lag=7)
    values.update(changes)
    return BrokerMessage(**values)


def build(messages, projection=None, producer=None, observed=None, handled=None):
    consumer=Consumer(messages); projection=projection or Projection(); producer=producer or Producer()
    worker=DurableEventConsumer(consumer=consumer,projection=projection,dlq_producer=producer,
        handler=lambda cursor,envelope:(handled if handled is not None else []).append((cursor,envelope)),
        consumer_group="recovery-overview-v1",
        lag_observer=(lambda topic,partition,lag:(observed if observed is not None else []).append((topic,partition,lag))))
    return worker,consumer,projection,producer


def test_offset_commits_only_after_projection_transaction_succeeds():
    handled=[]; observed=[]
    worker,consumer,projection,_=build([message()],observed=observed,handled=handled)
    assert worker.process_one()=="applied"
    assert consumer.committed==[(2,41)] and handled[0][0]=="database-cursor"
    assert observed==[("recovery.events.v1",2,7)]
    assert projection.calls[0]["event_id"]=="event-1"


def test_projection_failure_leaves_offset_uncommitted_for_safe_retry():
    worker,consumer,_,_=build([message()],projection=Projection(error=RuntimeError("aurora unavailable")))
    with pytest.raises(RuntimeError,match="aurora unavailable"):worker.process_one()
    assert consumer.committed==[]


def test_duplicate_event_commits_without_applying_twice():
    handled=[]
    worker,consumer,_,_=build([message()],projection=Projection(result=False),handled=handled)
    assert worker.process_one()=="duplicate" and consumer.committed==[(2,41)]


def test_poison_event_is_committed_only_after_dlq_ack():
    worker,consumer,_,producer=build([message(value={"not":"an envelope"})])
    assert worker.process_one()=="dead_lettered" and consumer.committed==[(2,41)]
    topic,_,body,_=producer.calls[0]
    assert topic=="recovery.events.v1.dlq" and body["source_offset"]==41
    assert "payload_sha256" in body and "not an envelope" not in json.dumps(body)


def test_dlq_failure_leaves_poison_offset_uncommitted():
    worker,consumer,_,_=build([message(value={"bad":True})],producer=Producer(error=RuntimeError("msk unavailable")))
    with pytest.raises(RuntimeError,match="msk unavailable"):worker.process_one()
    assert consumer.committed==[]


def test_partition_key_mismatch_is_dead_lettered():
    worker,consumer,_,producer=build([message(key=b"wrong-partition")])
    assert worker.process_one()=="dead_lettered" and consumer.committed==[(2,41)]
    assert "partition_key" in producer.calls[0][2]["detail"]
