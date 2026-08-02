from datetime import datetime, timedelta
from rules.engine import Assignment,CrewMember,FlightLeg,Qualification,RulesEngine

def assignment(hours=5,start_hour=8):
    start=datetime(2026,8,1,start_hour);leg=FlightLeg("AI421","DEL","BOM",start+timedelta(hours=1),start+timedelta(hours=4),"A321")
    crew=CrewMember("IC-927","DEL",{Qualification.A321},current_location="DEL",last_rest_end=start-timedelta(hours=10))
    return crew,Assignment(crew.crew_id,[leg],start,start+timedelta(hours=hours))

def test_ruleset_identifies_dgca_car_revision():
    assert RulesEngine.RULESET_VERSION=="dgca-car-sec7-serj-ptiii-2024.1"

def test_wocl_duty_limit_is_conservatively_reduced():
    crew,duty=assignment(14,3)
    findings=RulesEngine.validate_assignment(crew,duty)
    assert any(x.code=="FDP_LIMIT" and x.rule_ref.startswith("DGCA-CAR") for x in findings)

def test_qualification_and_position_are_hard_constraints():
    crew,duty=assignment();crew.qualifications={Qualification.B737};crew.current_location="HYD"
    codes={x.code for x in RulesEngine.validate_assignment(crew,duty)}
    assert {"MISSING_QUALIFICATION","CREW_POSITION"} <= codes
