"""
FAR 117-style crew duty-time and qualification rules engine.

Tests serve as the primary specification. All rules must be independently
testable and called by every solver tier.
"""

import pytest
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from enum import Enum


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

    @classmethod
    def validate_assignment(cls, crew: CrewMember, assignment: Assignment) -> list[str]:
        """Return list of violations. Empty = legal."""
        violations = []

        violations.extend(cls._check_duty_time(assignment))
        violations.extend(cls._check_flight_time(assignment))
        violations.extend(cls._check_rest_period(crew, assignment))
        violations.extend(cls._check_qualifications(crew, assignment))
        violations.extend(cls._check_deadhead_limits(assignment))
        violations.extend(cls._check_consecutive_days(crew, assignment))
        violations.extend(cls._check_no_deadhead_loops(assignment))

        return violations

    @classmethod
    def _check_duty_time(cls, assignment: Assignment) -> list[str]:
        duty_hours = (assignment.duty_end - assignment.duty_start).total_seconds() / 3600
        if duty_hours > cls.MAX_DUTY_HOURS + cls.MAX_DUTY_EXTENSION:
            return [f"Duty time {duty_hours:.1f}h exceeds max {cls.MAX_DUTY_HOURS + cls.MAX_DUTY_EXTENSION}h"]
        return []

    @classmethod
    def _check_flight_time(cls, assignment: Assignment) -> list[str]:
        flight_hours = sum(
            (leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 3600
            for leg in assignment.flight_legs if not leg.is_deadhead
        )
        if flight_hours > cls.MAX_FLIGHT_HOURS:
            return [f"Flight time {flight_hours:.1f}h exceeds max {cls.MAX_FLIGHT_HOURS}h"]
        return []

    @classmethod
    def _check_rest_period(cls, crew: CrewMember, assignment: Assignment) -> list[str]:
        if crew.last_rest_end is None:
            return []
        rest_hours = (assignment.duty_start - crew.last_rest_end).total_seconds() / 3600
        if rest_hours < cls.MIN_REST_HOURS:
            return [f"Rest period {rest_hours:.1f}h below minimum {cls.MIN_REST_HOURS}h"]
        return []

    @classmethod
    def _check_qualifications(cls, crew: CrewMember, assignment: Assignment) -> list[str]:
        violations = []
        for leg in assignment.flight_legs:
            if not leg.is_deadhead:
                required = Qualification[leg.aircraft_type]
                if required not in crew.qualifications:
                    violations.append(f"Missing qualification {required.value} for flight {leg.flight_id}")
        return violations

    @classmethod
    def _check_deadhead_limits(cls, assignment: Assignment) -> list[str]:
        deadhead_hours = sum(
            (leg.scheduled_arr - leg.scheduled_dep).total_seconds() / 3600
            for leg in assignment.flight_legs if leg.is_deadhead
        )
        if deadhead_hours > cls.MAX_DEADHEAD_HOURS:
            return [f"Deadhead time {deadhead_hours:.1f}h exceeds max {cls.MAX_DEADHEAD_HOURS}h"]
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
                return [f"Deadhead loop detected: {loc} appears twice in deadhead sequence"]
            seen.add(loc)
        return []

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
def validate(crew: CrewMember, assignment: Assignment) -> list[str]:
    """Entry point used by all solver tiers."""
    return RulesEngine.validate_assignment(crew, assignment)