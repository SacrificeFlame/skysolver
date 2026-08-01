"""Versioned canonical airline records used at integration boundaries.

The models preserve source identity, operating-date semantics, provenance and
data-quality evidence. They deliberately contain no solver-specific fields.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]


class FreshnessState(str, Enum):
    CURRENT = "current"
    AGING = "aging"
    STALE = "stale"
    UNKNOWN = "unknown"


class DataQualitySeverity(str, Enum):
    BLOCKING = "blocking"
    WARNING = "warning"
    INFORMATION = "information"


class DataQualityFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: Identifier
    severity: DataQualitySeverity
    message: Identifier
    field: str | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_system: Identifier
    source_record_id: Identifier
    source_timestamp: datetime
    ingestion_timestamp: datetime
    contract_version: Identifier

    @model_validator(mode="after")
    def validate_instants(self):
        if self.source_timestamp.tzinfo is None or self.ingestion_timestamp.tzinfo is None:
            raise ValueError("source and ingestion timestamps must be timezone-aware")
        if self.ingestion_timestamp < self.source_timestamp:
            raise ValueError("ingestion timestamp cannot precede source timestamp")
        return self


class TemporalContext(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    utc_instant: datetime
    local_airport_time: datetime
    iana_timezone: Identifier
    operating_date: date

    @model_validator(mode="after")
    def validate_time_representation(self):
        if self.utc_instant.tzinfo is None or self.local_airport_time.tzinfo is None:
            raise ValueError("operational timestamps must be timezone-aware")
        try:
            timezone = ZoneInfo(self.iana_timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("iana_timezone must identify an installed IANA timezone") from exc
        expected = self.utc_instant.astimezone(timezone)
        expected_wall = expected.replace(tzinfo=None, fold=self.local_airport_time.fold)
        supplied_wall = self.local_airport_time.replace(tzinfo=None)
        supplied_zone = getattr(self.local_airport_time.tzinfo, "key", None)
        if expected_wall != supplied_wall or supplied_zone != self.iana_timezone:
            raise ValueError("local_airport_time must represent utc_instant in iana_timezone")
        if self.local_airport_time.date() != self.operating_date:
            raise ValueError("operating_date must match local airport date")
        return self


class CanonicalRecord(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    canonical_id: Identifier
    source_system_id: Identifier
    tenant_id: Identifier
    version: Annotated[int, Field(ge=1)]
    provenance: Provenance
    freshness: FreshnessState
    data_quality_findings: tuple[DataQualityFinding, ...] = ()

    @property
    def deployment_blocked(self) -> bool:
        return self.freshness in {FreshnessState.STALE, FreshnessState.UNKNOWN} or any(
            finding.severity is DataQualitySeverity.BLOCKING for finding in self.data_quality_findings
        )


class AirportRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    iata_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    iana_timezone: Identifier


class FlightSegment(CanonicalRecord):
    flight_number: Identifier
    operating_date: date
    origin: AirportRef
    destination: AirportRef
    scheduled_departure: TemporalContext
    scheduled_arrival: TemporalContext
    aircraft_type: Identifier

    @model_validator(mode="after")
    def validate_segment(self):
        if self.origin.iata_code == self.destination.iata_code:
            raise ValueError("flight origin and destination must differ")
        if self.scheduled_departure.utc_instant >= self.scheduled_arrival.utc_instant:
            raise ValueError("arrival must be after departure")
        if self.operating_date != self.scheduled_departure.operating_date:
            raise ValueError("flight operating date must match departure operating date")
        return self


class Qualification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    code: Identifier
    valid_from: datetime
    valid_until: datetime
    status: Literal["valid", "suspended", "expired"]

    @model_validator(mode="after")
    def validate_period(self):
        if self.valid_from.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("qualification timestamps must be timezone-aware")
        if self.valid_until <= self.valid_from:
            raise ValueError("qualification validity period must be positive")
        return self


class CrewMember(CanonicalRecord):
    employee_reference: Identifier
    rank: Identifier
    base_airport: AirportRef
    current_airport: AirportRef
    qualifications: tuple[Qualification, ...]
    medical_valid_until: datetime


class Aircraft(CanonicalRecord):
    registration: Identifier
    aircraft_type: Identifier
    subfleet: Identifier
    cabin_configuration: Identifier
    current_airport: AirportRef
    operational_status: Literal["available", "operating", "maintenance", "blocked"]
    restrictions: tuple[Identifier, ...] = ()


class MovementSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["operated_flight", "deadhead", "ground_transport", "hotel", "rest"]
    origin: AirportRef
    destination: AirportRef
    departure: TemporalContext
    arrival: TemporalContext
    inventory_reference: str | None = None

    @model_validator(mode="after")
    def validate_movement(self):
        if self.arrival.utc_instant <= self.departure.utc_instant:
            raise ValueError("movement arrival must follow departure")
        if self.kind in {"operated_flight", "deadhead", "ground_transport"} and self.origin == self.destination:
            raise ValueError("transport movement must change location")
        return self


class InputSnapshot(CanonicalRecord):
    captured_at: datetime
    aggregate_versions: dict[Identifier, Annotated[int, Field(ge=1)]]
    content_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    ruleset_version: Identifier
    objective_version: Identifier
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.captured_at.tzinfo is None:
            raise ValueError("snapshot capture time must be timezone-aware")
        if not self.aggregate_versions:
            raise ValueError("snapshot must identify its aggregate versions")
        return self
