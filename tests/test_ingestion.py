from datetime import datetime, timedelta, timezone

from integrations.ingestion import ContractError, IngestionEngine, IngestionStatus, SourceRecord


def mapper(record):
    if "flight_number" not in record.payload:
        raise ContractError("MISSING_FLIGHT_NUMBER", "flight_number is required")
    return {"canonical_id": f"flight:{record.payload['flight_number']}", "payload": record.payload}


def record(event_id="E1", timestamp=None, cursor="1", payload=None, version="schedule.v1"):
    return SourceRecord(event_id, "airline", "schedule", version, "flight", "AI421",
                        timestamp or datetime(2026, 8, 1, tzinfo=timezone.utc), cursor,
                        payload if payload is not None else {"flight_number": "AI421", "passenger_name": "must-not-cross-boundary"})


def test_ingestion_is_idempotent_and_minimizes_fields():
    engine = IngestionEngine({"schedule.v1"}, mapper, {"flight_number"})
    first = engine.ingest(record())
    duplicate = engine.ingest(record())
    assert first.status is IngestionStatus.ACCEPTED
    assert first.canonical_record["payload"] == {"flight_number": "AI421"}
    assert duplicate.status is IngestionStatus.DUPLICATE
    assert engine.cursor("airline", "schedule") == "1"


def test_out_of_order_event_is_retained_but_flagged():
    engine = IngestionEngine({"schedule.v1"}, mapper)
    current = datetime(2026, 8, 1, 10, tzinfo=timezone.utc)
    engine.ingest(record("E2", current, "2"))
    older = engine.ingest(record("E1", current - timedelta(minutes=5), "3"))
    assert older.status is IngestionStatus.OUT_OF_ORDER
    assert older.findings[0]["code"] == "OUT_OF_ORDER_SOURCE_EVENT"


def test_invalid_schema_routes_to_dead_letter_without_cursor_advance():
    engine = IngestionEngine({"schedule.v1"}, mapper)
    result = engine.ingest(record(payload={"tail": "VT-EXA"}))
    assert result.status is IngestionStatus.DEAD_LETTER
    assert result.findings[0]["severity"] == "blocking"
    assert engine.cursor("airline", "schedule") is None
    assert engine.dead_letters()[0].payload_sha256


def test_contract_negotiation_rejects_unsupported_version():
    engine = IngestionEngine({"schedule.v2"}, mapper)
    result = engine.ingest(record(version="schedule.v1"))
    assert result.status is IngestionStatus.DEAD_LETTER
    assert result.findings[0]["code"] == "UNSUPPORTED_CONTRACT"


def test_event_id_collision_is_blocking():
    engine = IngestionEngine({"schedule.v1"}, mapper)
    engine.ingest(record(payload={"flight_number": "AI421"}))
    collision = engine.ingest(record(payload={"flight_number": "AI422"}))
    assert collision.status is IngestionStatus.DEAD_LETTER
    assert collision.findings[0]["code"] == "EVENT_ID_COLLISION"


def test_reconciliation_reports_both_directions():
    engine = IngestionEngine({"schedule.v1"}, mapper)
    engine.ingest(record())
    assert engine.reconcile({"flight:AI422"}) == {"missing_locally": ["flight:AI422"], "missing_at_source": ["flight:AI421"]}
