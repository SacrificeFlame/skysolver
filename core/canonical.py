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


class Airline(CanonicalRecord):
    legal_name: Identifier
    iata_code: Annotated[str, StringConstraints(pattern=r"^[A-Z0-9]{2}$")]
    icao_code: Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]
    operating_certificate_reference: Identifier


class DutyPeriod(CanonicalRecord):
    crew_id: Identifier
    report: TemporalContext
    release: TemporalContext
    flight_segment_ids: tuple[Identifier, ...] = ()
    positioning_segments: tuple[MovementSegment, ...] = ()
    duty_kind: Literal["flight_duty", "positioning", "standby", "reserve", "training"]

    @model_validator(mode="after")
    def validate_duty(self):
        if self.release.utc_instant <= self.report.utc_instant:
            raise ValueError("duty release must follow report")
        if self.duty_kind == "flight_duty" and not self.flight_segment_ids:
            raise ValueError("flight duty must contain a flight segment")
        return self


class Pairing(CanonicalRecord):
    pairing_number: Identifier
    crew_role: Identifier
    base_airport: AirportRef
    duties: tuple[DutyPeriod, ...]

    @model_validator(mode="after")
    def validate_pairing(self):
        if not self.duties:
            raise ValueError("pairing must contain at least one duty")
        ordered = sorted(self.duties, key=lambda item: item.report.utc_instant)
        for previous, current in zip(ordered, ordered[1:]):
            if current.report.utc_instant < previous.release.utc_instant:
                raise ValueError("pairing duties cannot overlap")
        return self


class ReserveAvailability(CanonicalRecord):
    crew_id: Identifier
    airport: AirportRef
    available_from: TemporalContext
    available_until: TemporalContext
    reserve_kind: Literal["airport_standby", "home_standby", "short_call", "long_call"]
    contact_status: Literal["not_contacted", "contacting", "acknowledged", "unreachable"]

    @model_validator(mode="after")
    def validate_availability(self):
        if self.available_until.utc_instant <= self.available_from.utc_instant:
            raise ValueError("reserve availability period must be positive")
        return self


class MaintenanceRestriction(CanonicalRecord):
    aircraft_id: Identifier
    restriction_type: Literal["maintenance", "mel", "cdl", "route", "airport"]
    code: Identifier
    description: Identifier
    effective_from: datetime
    effective_until: datetime | None = None
    permitted_operations: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def validate_restriction(self):
        if self.effective_from.tzinfo is None or (
            self.effective_until is not None and self.effective_until.tzinfo is None
        ):
            raise ValueError("restriction timestamps must be timezone-aware")
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("restriction end must follow its start")
        return self


class GateResource(CanonicalRecord):
    airport: AirportRef
    terminal: Identifier
    gate: Identifier
    compatible_aircraft_types: tuple[Identifier, ...]
    available_from: TemporalContext
    available_until: TemporalContext

    @model_validator(mode="after")
    def validate_gate_window(self):
        if not self.compatible_aircraft_types:
            raise ValueError("gate must declare compatible aircraft types")
        if self.available_until.utc_instant <= self.available_from.utc_instant:
            raise ValueError("gate availability period must be positive")
        return self


class PassengerParty(CanonicalRecord):
    pnr_reference: Identifier
    passenger_count: Annotated[int, Field(ge=1)]
    itinerary_segment_ids: tuple[Identifier, ...]
    special_service_requests: tuple[Identifier, ...] = ()
    disruption_status: Literal["unaffected", "at_risk", "misconnected", "cancelled", "reaccommodated"]
    inventory_hold_reference: str | None = None

    @model_validator(mode="after")
    def validate_itinerary(self):
        if not self.itinerary_segment_ids:
            raise ValueError("passenger party must contain an itinerary")
        if self.disruption_status == "reaccommodated" and not self.inventory_hold_reference:
            raise ValueError("reaccommodation requires confirmed inventory")
        return self


class Disruption(CanonicalRecord):
    disruption_type: Identifier
    severity: Literal["advisory", "moderate", "high", "critical"]
    source_confidence: Annotated[float, Field(ge=0, le=1)]
    affected_airports: tuple[AirportRef, ...]
    affected_partition_ids: tuple[Identifier, ...]
    starts_at: datetime
    expected_end_at: datetime | None = None

    @model_validator(mode="after")
    def validate_disruption_window(self):
        if self.starts_at.tzinfo is None or (
            self.expected_end_at is not None and self.expected_end_at.tzinfo is None
        ):
            raise ValueError("disruption timestamps must be timezone-aware")
        if self.expected_end_at is not None and self.expected_end_at <= self.starts_at:
            raise ValueError("expected disruption end must follow its start")
        if not self.affected_partition_ids:
            raise ValueError("disruption must identify an affected partition")
        return self


class RecoveryPlan(CanonicalRecord):
    disruption_id: Identifier
    input_snapshot_id: Identifier
    partition_ids: tuple[Identifier, ...]
    candidate_ids: tuple[Identifier, ...] = ()
    selected_candidate_id: str | None = None
    status: Literal["scoped", "solving", "awaiting_review", "validating", "approved", "deploying", "complete", "partial", "failed"]
    state_version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_selection(self):
        if self.selected_candidate_id and self.selected_candidate_id not in self.candidate_ids:
            raise ValueError("selected candidate must belong to the recovery plan")
        if not self.partition_ids:
            raise ValueError("recovery plan must identify a partition")
        return self


class ApprovalRecord(CanonicalRecord):
    recovery_id: Identifier
    candidate_id: Identifier
    candidate_version: Annotated[int, Field(ge=1)]
    actor_subject: Identifier
    actor_role: Identifier
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=1000)]
    approved_at: datetime
    ruleset_version: Identifier
    state_version: Annotated[int, Field(ge=1)]

    @model_validator(mode="after")
    def validate_approval_time(self):
        if self.approved_at.tzinfo is None:
            raise ValueError("approval timestamp must be timezone-aware")
        return self


class DeploymentAcknowledgement(CanonicalRecord):
    deployment_id: Identifier
    command_id: Identifier
    resource_type: Identifier
    resource_id: Identifier
    source_system_reference: str | None = None
    status: Literal["queued", "published", "acknowledged", "rejected", "timed_out", "compensated", "irreversible"]
    acknowledged_at: datetime | None = None
    failure_code: str | None = None

    @model_validator(mode="after")
    def validate_acknowledgement(self):
        if self.acknowledged_at is not None and self.acknowledged_at.tzinfo is None:
            raise ValueError("acknowledgement timestamp must be timezone-aware")
        if self.status == "acknowledged" and (not self.source_system_reference or not self.acknowledged_at):
            raise ValueError("acknowledged command requires source evidence and timestamp")
        if self.status in {"rejected", "timed_out"} and not self.failure_code:
            raise ValueError("failed command requires a failure code")
        return self


class RulesetReference(CanonicalRecord):
    ruleset_name: Identifier
    ruleset_version: Identifier
    effective_from: datetime
    effective_until: datetime | None = None
    package_sha256: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")]
    signing_key_id: Identifier
    approval_references: tuple[Identifier, ...]

    @model_validator(mode="after")
    def validate_ruleset(self):
        if self.effective_from.tzinfo is None or (
            self.effective_until is not None and self.effective_until.tzinfo is None
        ):
            raise ValueError("ruleset timestamps must be timezone-aware")
        if self.effective_until is not None and self.effective_until <= self.effective_from:
            raise ValueError("ruleset effective period must be positive")
        if len(set(self.approval_references)) < 2:
            raise ValueError("ruleset activation requires two distinct approvals")
        return self


class AuditEvent(CanonicalRecord):
    aggregate_type: Identifier
    aggregate_id: Identifier
    action: Identifier
    actor_subject: Identifier
    actor_role: Identifier
    correlation_id: Identifier
    causation_id: str | None = None
    occurred_at: datetime
    state_version: Annotated[int, Field(ge=1)]
    detail: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_audit_time(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("audit timestamp must be timezone-aware")
        return self
