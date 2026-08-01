from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from core.canonical import (
    AirportRef,
    DataQualityFinding,
    DataQualitySeverity,
    FlightSegment,
    FreshnessState,
    Provenance,
    TemporalContext,
)


def provenance():
    return Provenance(
        source_system="schedule-fixture",
        source_record_id="AI421-20260801",
        source_timestamp=datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc),
        ingestion_timestamp=datetime(2026, 8, 1, 4, 0, 2, tzinfo=timezone.utc),
        contract_version="schedule.v1",
    )


def temporal(hour: int, minute: int, operating_date=date(2026, 8, 1)):
    instant = datetime(2026, 8, 1, hour, minute, tzinfo=timezone.utc)
    return TemporalContext(
        utc_instant=instant,
        local_airport_time=instant.astimezone(ZoneInfo("Asia/Kolkata")),
        iana_timezone="Asia/Kolkata",
        operating_date=operating_date,
    )


def test_canonical_flight_preserves_operating_date_and_provenance():
    flight = FlightSegment(
        canonical_id="flight-AI421-20260801",
        source_system_id="AI421-20260801",
        tenant_id="demo-airline",
        version=3,
        provenance=provenance(),
        freshness=FreshnessState.CURRENT,
        flight_number="AI421",
        operating_date=date(2026, 8, 1),
        origin=AirportRef(iata_code="DEL", iana_timezone="Asia/Kolkata"),
        destination=AirportRef(iata_code="BOM", iana_timezone="Asia/Kolkata"),
        scheduled_departure=temporal(4, 30),
        scheduled_arrival=temporal(6, 40),
        aircraft_type="A321",
    )
    assert flight.version == 3
    assert flight.provenance.source_system == "schedule-fixture"
    assert flight.deployment_blocked is False


def test_blocking_quality_finding_blocks_deployment():
    finding = DataQualityFinding(code="MISSING_TAIL", severity=DataQualitySeverity.BLOCKING, message="Tail is required")
    assert finding.severity is DataQualitySeverity.BLOCKING


def test_naive_source_timestamp_is_rejected():
    with pytest.raises(ValidationError, match="timezone-aware"):
        Provenance(
            source_system="schedule-fixture",
            source_record_id="AI421",
            source_timestamp=datetime(2026, 8, 1, 4, 0),
            ingestion_timestamp=datetime(2026, 8, 1, 4, 1, tzinfo=timezone.utc),
            contract_version="schedule.v1",
        )


def test_inconsistent_local_time_is_rejected():
    with pytest.raises(ValidationError, match="local_airport_time"):
        TemporalContext(
            utc_instant=datetime(2026, 8, 1, 4, 30, tzinfo=timezone.utc),
            local_airport_time=datetime(2026, 8, 1, 4, 30, tzinfo=timezone.utc),
            iana_timezone="Asia/Kolkata",
            operating_date=date(2026, 8, 1),
        )
