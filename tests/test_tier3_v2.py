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


def test_generation_has_no_twenty_item_cap_and_never_auto_approves():
    flights=[]; crew=[]
    for index in range(25):
        flight=FlightLeg(f"AI{index}","DEL","BOM",datetime(2026,8,1,8),datetime(2026,8,1,10),"A321")
        flights.append(flight)
        crew.append(CrewMember(f"C{index}","DEL",{Qualification.A321},current_location="DEL"))
    suggestions=generate_suggestions(flights,crew,"DEL",7)
    assert len(suggestions)==625
    assert all(item.status is SuggestionStatus.PENDING for item in suggestions)
    assert all(item.state_version==7 for item in suggestions)
    assert len({item.suggestion_id for item in suggestions})==625


def test_suggestion_ids_are_stable_for_same_state_and_change_with_version():
    flight=FlightLeg("AI421","DEL","BOM",datetime(2026,8,1,8),datetime(2026,8,1,10),"A321")
    crew=CrewMember("C1","DEL",{Qualification.A321},current_location="DEL")
    first=generate_suggestions([flight],[crew],"DEL",3)[0]
    repeated=generate_suggestions([flight],[crew],"DEL",3)[0]
    newer=generate_suggestions([flight],[crew],"DEL",4)[0]
    assert first.suggestion_id==repeated.suggestion_id
    assert first.suggestion_id!=newer.suggestion_id
