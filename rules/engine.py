"""
FAR 117-style crew duty-time and qualification rules engine.

Tests serve as the primary specification. All rules must be independently
testable and called by every solver tier.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from enum import Enum
from core.domain import RuleViolation


class Qualification(Enum):
    B737 = "B737"
    B777 = "B777"
    A320 = "A320"
    A321 = "A321"
    B787 = "B787"
    NIGHT_FLYING = "NIGHT_FLYING"
    ICU_WX = "ICAO_WX"
    ETOPS = "ETOPS"


@dataclass
class CrewMember:
    crew_id: str
    base_hub: str
    qualifications: set[Qualification]
    duty_clock_start: Optional[datetime] = None
    current_location: str = ""
    last_rest_end: Optional[datetime] = None


@dataclass
class FlightLeg:
    flight_id: str
    origin: str
    destination: str
    scheduled_dep: datetime
    scheduled_arr: datetime
    aircraft_type: str
    is_deadhead: bool = False


@dataclass
class Assignment:
    crew_id: str
    flight_legs: list[FlightLeg]
    duty_start: datetime
    duty_end: datetime


class RulesEngine:
    """FAR 117 compliant rules engine. All methods are pure functions."""

    # FAR 117 limits (simplified for synthetic data)
    MAX_DUTY_HOURS = 14
    MAX_FLIGHT_HOURS = 9
    MIN_REST_HOURS = 10
    MAX_DEADHEAD_HOURS = 8
    MAX_CONSECUTIVE_DAYS = 6
    MAX_DUTY_EXTENSION = 2  # hours beyond max for operational necessity

    RULESET_VERSION = "synthetic-far117-v2"
    MIN_CONNECTION_MINUTES = 30

    @staticmethod
    def _violation(code, message, rule_ref, entity_id=None, **details):
        return RuleViolation(code, message, rule_ref, entity_id=entity_id, details=details)

    @classmethod
    def validate_assignment(cls, crew: CrewMember, assignment: Assignment) -> list[RuleViolation]:
        """Return list of violations. Empty = legal."""
        violations = []

        violations.extend(cls._check_duty_time(assignment))
        violations.extend(cls._check_flight_time(assignment))
        violations.extend(cls._check_rest_period(crew, assignment))
        violations.extend(cls._check_qualifications(crew, assignment))
        violations.extend(cls._check_deadhead_limits(assignment))
        violations.extend(cls._check_consecutive_days(crew, assignment))
        violations.extend(cls._check_no_deadhead_loops(assignment))
        violations.extend(cls._check_temporal_and_geographic_continuity(crew, assignment))

        return violations

    @classmethod
    def _check_duty_time(cls, assignment: Assignment) -> list[str]:
        duty_hours = (assignment.duty_end - assignment.duty_start).total_seconds() / 3600
        if duty_hours > cls.MAX_DUTY_HOURS + cls.MAX_DUTY_EXTENSION:
            return [cls._violation("DUTY_LIMIT", f"Duty time {duty_hours:.1f}h exceeds max {cls.MAX_DUTY_HOURS + cls.MAX_DUTY_EXTENSION}h", "FAR-117.13", assignment.crew_id, actual_hours=duty_hours)]
        return []

    @classmethod
    def _check_flight_time(cls, assignment: Assignment) -> list[str]:
        flight_hours = sum(
            (leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 3600
            for leg in assignment.flight_legs if not leg.is_deadhead
        )
        if flight_hours > cls.MAX_FLIGHT_HOURS:
            return [cls._violation("FLIGHT_TIME_LIMIT", f"Flight time {flight_hours:.1f}h exceeds max {cls.MAX_FLIGHT_HOURS}h", "FAR-117.11", assignment.crew_id, actual_hours=flight_hours)]
        return []

    @classmethod
    def _check_rest_period(cls, crew: CrewMember, assignment: Assignment) -> list[str]:
        if crew.last_rest_end is None:
            return []
        rest_hours = (assignment.duty_start - crew.last_rest_end).total_seconds() / 3600
        if rest_hours < cls.MIN_REST_HOURS:
            return [cls._violation("MIN_REST", f"Rest period {rest_hours:.1f}h below minimum {cls.MIN_REST_HOURS}h", "FAR-117.25", assignment.crew_id, actual_hours=rest_hours)]
        return []

    @classmethod
    def _check_qualifications(cls, crew: CrewMember, assignment: Assignment) -> list[str]:
        violations = []
        for leg in assignment.flight_legs:
            if not leg.is_deadhead:
                try:
                    required = Qualification[leg.aircraft_type]
                except KeyError:
                    violations.append(cls._violation("UNKNOWN_AIRCRAFT", f"Unknown aircraft type {leg.aircraft_type} for flight {leg.flight_id}", "COMPANY-AOM", leg.flight_id))
                    continue
                if required not in crew.qualifications:
                    violations.append(cls._violation("MISSING_QUALIFICATION", f"Missing qualification {required.value} for flight {leg.flight_id}", "FAR-121-QUAL", leg.flight_id, required=required.value))
        return violations

    @classmethod
    def _check_deadhead_limits(cls, assignment: Assignment) -> list[str]:
        deadhead_hours = sum(
            (leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 3600
            for leg in assignment.flight_legs if leg.is_deadhead
        )
        if deadhead_hours > cls.MAX_DEADHEAD_HOURS:
            return [cls._violation("DEADHEAD_LIMIT", f"Deadhead time {deadhead_hours:.1f}h exceeds max {cls.MAX_DEADHEAD_HOURS}h", "COMPANY-DEADHEAD", assignment.crew_id)]
        return []

    @classmethod
    def _check_consecutive_days(cls, crew: CrewMember, assignment: Assignment) -> list[str]:
        # Simplified: would track in real implementation
        return []

    @classmethod
    def _check_no_deadhead_loops(cls, assignment: Assignment) -> list[str]:
        """Prevent deadheading crews in circles (SkySolver v1 failure mode)."""
        locations = []
        for leg in assignment.flight_legs:
            if leg.is_deadhead:
                locations.append(leg.origin)
                locations.append(leg.destination)

        # Check for repeated location in deadhead sequence
        seen = set()
        for loc in locations:
            if loc in seen:
                return [cls._violation("DEADHEAD_LOOP", f"Deadhead loop detected: {loc} appears twice in deadhead sequence", "SKYSOLVER-SAFETY-001", assignment.crew_id)]
            seen.add(loc)
        return []

    @classmethod
    def _check_temporal_and_geographic_continuity(cls, crew, assignment):
        violations = []
        legs = sorted(assignment.flight_legs, key=lambda leg: leg.scheduled_dep)
        for leg in legs:
            if leg.scheduled_arr <= leg.scheduled_dep:
                violations.append(cls._violation("INVALID_LEG_TIME", f"Flight {leg.flight_id} arrives before it departs", "DATA-QUALITY", leg.flight_id))
        if legs and crew.current_location and legs[0].origin != crew.current_location:
            violations.append(cls._violation("CREW_POSITION", f"Crew {crew.crew_id} is at {crew.current_location}, not {legs[0].origin}", "OPERATIONAL-CONTINUITY", crew.crew_id))
        for previous, current in zip(legs, legs[1:]):
            if previous.destination != current.origin:
                violations.append(cls._violation("LOCATION_DISCONTINUITY", f"Flight sequence jumps from {previous.destination} to {current.origin}", "OPERATIONAL-CONTINUITY", current.flight_id))
            connection = (current.scheduled_dep - previous.scheduled_arr).total_seconds() / 60
            if connection < cls.MIN_CONNECTION_MINUTES:
                violations.append(cls._violation("CONNECTION_TIME", f"Connection before {current.flight_id} is {connection:.0f}m; minimum is {cls.MIN_CONNECTION_MINUTES}m", "COMPANY-CONNECTION", current.flight_id))
        return violations

    @classmethod
    def can_assign(cls, crew: CrewMember, assignment: Assignment) -> bool:
        """Quick boolean check for solvers."""
        return len(cls.validate_assignment(crew, assignment)) == 0

    @classmethod
    def max_extended_duty(cls, assignment: Assignment) -> float:
        """Return max allowed duty hours for this assignment type."""
        base = cls.MAX_DUTY_HOURS
        # Could add complexity: augmented crew, time of day, etc.
        return base + cls.MAX_DUTY_EXTENSION


# Convenience function for solver integration
def validate(crew: CrewMember, assignment: Assignment) -> list[RuleViolation]:
    """Entry point used by all solver tiers."""
    return RulesEngine.validate_assignment(crew, assignment)
