from datetime import datetime

from core.domain import RuleViolation
from rules.engine import Assignment, CrewMember, FlightLeg, Qualification, validate


def _crew(location="DFW"):
    return CrewMember("C1", "DFW", {Qualification.B737}, current_location=location)


def test_violations_are_structured_and_auditable():
    leg = FlightLeg("F1", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 20), "B737")
    violations = validate(_crew(), Assignment("C1", [leg], leg.scheduled_dep, leg.scheduled_arr))
    assert violations and isinstance(violations[0], RuleViolation)
    assert violations[0].code and violations[0].rule_ref


def test_unknown_aircraft_is_a_violation_not_an_exception():
    leg = FlightLeg("F1", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 9), "A999")
    assert any(v.code == "UNKNOWN_AIRCRAFT" for v in validate(_crew(), Assignment("C1", [leg], leg.scheduled_dep, leg.scheduled_arr)))


def test_location_discontinuity_and_overlap_are_rejected():
    legs = [
        FlightLeg("F1", "DFW", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10), "B737"),
        FlightLeg("F2", "ORD", "DEN", datetime(2024, 1, 1, 9), datetime(2024, 1, 1, 11), "B737"),
    ]
    codes = {v.code for v in validate(_crew(), Assignment("C1", legs, legs[0].scheduled_dep, legs[1].scheduled_arr))}
    assert {"LOCATION_DISCONTINUITY", "CONNECTION_TIME"} <= codes
