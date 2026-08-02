"""
Legacy boundary corpus retained for the DGCA-oriented demo rules profile.

These tests define the legal behavior. All solver tiers must pass these tests.
"""

import pytest
from datetime import datetime, timedelta
from rules.engine import (
    RulesEngine, CrewMember, FlightLeg, Assignment, Qualification, validate
)


class TestDutyTimeLimits:
    """Demo maximum duty-period boundary."""

    def test_legal_duty_within_14_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737"),
            FlightLeg("AA200", "LAX", "DFW", datetime(2024, 1, 1, 13), datetime(2024, 1, 1, 18), "B737"),
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 19))
        assert validate(crew, assignment) == []

    def test_illegal_duty_exceeds_14_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737"),
            FlightLeg("AA200", "LAX", "JFK", datetime(2024, 1, 1, 13), datetime(2024, 1, 1, 20), "B737"),
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 2, 0))  # 17h duty
        violations = validate(crew, assignment)
        assert any("Duty time" in v for v in violations)

    def test_legal_duty_extension_up_to_2_hours(self):
        """Operational necessity extension up to 2h beyond 14h."""
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 16), "B737")]  # 8h flight
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 21))  # 14h
        assert validate(crew, assignment) == []  # Exactly 14h is legal

        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 2, 0))  # 17h (> 16h max)
        violations = validate(crew, assignment)
        assert any("Duty time" in v and "17.0h" in v for v in violations)


class TestFlightTimeLimits:
    """Demo maximum flight-time boundary."""

    def test_legal_flight_time_under_9_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737"),  # 3h
            FlightLeg("AA200", "LAX", "DFW", datetime(2024, 1, 1, 13), datetime(2024, 1, 1, 17), "B737"),  # 4h
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 19))
        assert validate(crew, assignment) == []

    def test_illegal_flight_time_exceeds_9_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 12), "B737"),  # 4h
            FlightLeg("AA200", "LAX", "JFK", datetime(2024, 1, 1, 14), datetime(2024, 1, 1, 20), "B737"),  # 6h
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 21))
        violations = validate(crew, assignment)
        assert any("Flight time" in v and "10.0h" in v for v in violations)


class TestRestPeriods:
    """Demo minimum-rest boundary."""

    def test_legal_rest_10_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 17), datetime(2024, 1, 1, 20), "B737")]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 16), datetime(2024, 1, 1, 21))
        assert validate(crew, assignment) == []

    def test_illegal_rest_below_10_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2024, 1, 1, 8))
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 17), datetime(2024, 1, 1, 20), "B737")]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 16), datetime(2024, 1, 1, 21))
        violations = validate(crew, assignment)
        assert any("Rest period" in v and "8.0h" in v for v in violations)


class TestQualifications:
    """FAR 61/121 - Crew qualification matching."""

    def test_legal_qualified_for_aircraft(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737, Qualification.B777}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B777")]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 12))
        assert validate(crew, assignment) == []

    def test_illegal_unqualified_for_aircraft(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B777")]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 12))
        violations = validate(crew, assignment)
        assert any("Missing qualification B777" in v for v in violations)


class TestDeadheadLimits:
    """Deadhead positioning flights count differently."""

    def test_legal_deadhead_under_8_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("DH100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 12), "B737", is_deadhead=True),  # 4h
            FlightLeg("AA200", "LAX", "DFW", datetime(2024, 1, 1, 14), datetime(2024, 1, 1, 17), "B737"),  # 3h flying
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 18))
        assert validate(crew, assignment) == []

    def test_illegal_deadhead_exceeds_8_hours(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("DH100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 12), "B737", is_deadhead=True),
            FlightLeg("DH200", "LAX", "JFK", datetime(2024, 1, 1, 14), datetime(2024, 1, 1, 20), "B737", is_deadhead=True),  # 6h deadhead
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 21))
        violations = validate(crew, assignment)
        assert any("Deadhead time" in v and "10.0h" in v for v in violations)


class TestDeadheadLoopPrevention:
    """SkySolver v1 failure mode: deadheading crews in circles."""

    def test_legal_no_deadhead_loop(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("DH100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737", is_deadhead=True),
            FlightLeg("AA200", "LAX", "DFW", datetime(2024, 1, 1, 13), datetime(2024, 1, 1, 18), "B737"),
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 19))
        assert validate(crew, assignment) == []

    def test_illegal_deadhead_loop_detected(self):
        """DFW -> LAX -> DFW -> LAX deadhead loop."""
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("DH100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737", is_deadhead=True),
            FlightLeg("DH200", "LAX", "DFW", datetime(2024, 1, 1, 12), datetime(2024, 1, 1, 15), "B737", is_deadhead=True),
            FlightLeg("DH300", "DFW", "LAX", datetime(2024, 1, 1, 16), datetime(2024, 1, 1, 19), "B737", is_deadhead=True),
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 20))
        violations = validate(crew, assignment)
        assert any("Deadhead loop detected" in v for v in violations)

    def test_legal_repeated_location_not_deadhead(self):
        """Returning to hub on revenue flight is legal."""
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [
            FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737"),
            FlightLeg("AA200", "LAX", "DFW", datetime(2024, 1, 1, 13), datetime(2024, 1, 1, 18), "B737"),
        ]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 19))
        assert validate(crew, assignment) == []


class TestCanAssign:
    """Quick boolean check for solver integration."""

    def test_can_assign_returns_true_for_legal(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2023, 12, 31, 20))  # rested >=10h before 07:00 duty start
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 11), "B737")]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 7), datetime(2024, 1, 1, 12))
        assert RulesEngine.can_assign(crew, assignment) is True

    def test_can_assign_returns_false_for_illegal(self):
        crew = CrewMember("C001", "DFW", {Qualification.B737}, last_rest_end=datetime(2024, 1, 1, 8))
        legs = [FlightLeg("AA100", "DFW", "LAX", datetime(2024, 1, 1, 17), datetime(2024, 1, 1, 20), "B737")]
        assignment = Assignment("C001", legs, datetime(2024, 1, 1, 16), datetime(2024, 1, 1, 21))
        assert RulesEngine.can_assign(crew, assignment) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
