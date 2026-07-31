from datetime import datetime

from core.domain import RecoveryTier
from rules.engine import CrewMember, FlightLeg, Qualification, validate
from solvers.orchestrator import solve_recovery


def test_orchestrator_returns_legal_incumbent():
    crew = [CrewMember("C1", "DEN", {Qualification.B737}, current_location="DEN")]
    flights = [FlightLeg("F1", "DEN", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10), "B737")]
    result = solve_recovery("DEN", crew, flights, .1, .1)
    assert result.complete and result.tier == RecoveryTier.HEURISTIC
    assert not validate(crew[0], result.assignments[0])


def test_orchestrator_escalates_uncovered_work_to_human_assist():
    crew = [CrewMember("C1", "DEN", {Qualification.B737}, current_location="DEN")]
    flights = [FlightLeg("F1", "DEN", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10), "B777")]
    result = solve_recovery("DEN", crew, flights, .01, .01)
    assert result.tier == RecoveryTier.HUMAN_ASSIST and result.uncovered
