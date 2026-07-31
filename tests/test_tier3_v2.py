from datetime import datetime

from rules.engine import CrewMember, FlightLeg, Qualification
from solvers.tier3_api import CrewSuggestion, DecisionRepository, SuggestionStatus, generate_suggestions


def test_suggestions_are_legality_gated():
    flight = FlightLeg("F1", "DEN", "LAX", datetime(2024, 1, 1, 8), datetime(2024, 1, 1, 10), "B777")
    crew = CrewMember("C1", "DEN", {Qualification.B737}, current_location="DEN")
    assert generate_suggestions([flight], [crew], "DEN") == []


def test_decision_repository_is_durable(tmp_path):
    repo = DecisionRepository(str(tmp_path / "decisions.db"))
    suggestion = CrewSuggestion("S1", "C1", [], ["F1"], "legal move", 1, True, 2, .5, .2, status=SuggestionStatus.APPROVED)
    repo.record("DEN", suggestion, "scheduler-7")
    assert repo.list("DEN")[0]["status"] == "approved"
