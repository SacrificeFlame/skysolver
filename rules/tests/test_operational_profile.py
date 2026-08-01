from datetime import datetime,timedelta,timezone

from rules.engine import Assignment,CrewMember,FlightLeg,Qualification
from rules.operational_profile import AccumulatedTotals,OperationalContext,OperationalLegalityEvaluator,OperationalLimits


NOW=datetime(2026,8,1,8,tzinfo=timezone.utc)
LIMITS=OperationalLimits("signed-operator-package-2026.08")


def scenario(start=NOW,hours=5):
    crew=CrewMember("IC-1","DEL",{Qualification.A321},current_location="DEL",last_rest_end=start-timedelta(hours=12))
    leg=FlightLeg("AI421","DEL","BOM",start+timedelta(hours=1),start+timedelta(hours=4),"A321")
    return crew,Assignment("IC-1",[leg],start,start+timedelta(hours=hours))


def complete_context(**changes):
    values=dict(evaluated_at=NOW,history_complete=True,
        accumulated=AccumulatedTotals(1000,10000,1000,4000),
        licence_valid_until=NOW+timedelta(days=365),medical_valid_until=NOW+timedelta(days=365),
        recency_valid_until=NOW+timedelta(days=30),qualification_valid_until={"A321":NOW+timedelta(days=365)},
        acclimatized=True,timezone_delta_hours=0,consecutive_night_duties=0,
        required_roles=frozenset({"captain","first-officer"}),assigned_roles=frozenset({"captain","first-officer"}),
        visa_and_transit_allowed=True)
    values.update(changes);return OperationalContext(**values)


def codes(findings):return {item.code for item in findings}


def test_complete_current_context_produces_no_additional_findings():
    crew,assignment=scenario()
    assert OperationalLegalityEvaluator(LIMITS).evaluate(crew,assignment,complete_context())==[]


def test_strict_mode_fails_closed_without_history_credentials_and_acclimatization():
    crew,assignment=scenario();context=OperationalContext(evaluated_at=NOW,history_complete=False)
    result=codes(OperationalLegalityEvaluator(LIMITS).evaluate(crew,assignment,context))
    assert {"AUTHORITATIVE_HISTORY_REQUIRED","LICENCE_EVIDENCE_REQUIRED","MEDICAL_EVIDENCE_REQUIRED",
            "RECENCY_EVIDENCE_REQUIRED","QUALIFICATION_VALIDITY_REQUIRED",
            "ACCLIMATIZATION_EVIDENCE_REQUIRED","IMMIGRATION_EVIDENCE_REQUIRED"}<=result


def test_cumulative_arithmetic_includes_proposed_assignment_and_trace():
    crew,assignment=scenario();context=complete_context(
        accumulated=AccumulatedTotals(5900,59900,3500,11200))
    findings=OperationalLegalityEvaluator(LIMITS).evaluate(crew,assignment,context)
    assert {"CUMULATIVE_FLIGHT_28D","CUMULATIVE_FLIGHT_365D","CUMULATIVE_DUTY_7D",
            "CUMULATIVE_DUTY_28D"}<=codes(findings)
    assert all("formula" in item.details for item in findings if item.code.startswith("CUMULATIVE_"))


def test_expiring_credentials_are_compared_to_projected_duty_release():
    crew,assignment=scenario();expiry=assignment.duty_end-timedelta(minutes=1)
    findings=OperationalLegalityEvaluator(LIMITS).evaluate(crew,assignment,
        complete_context(licence_valid_until=expiry,medical_valid_until=expiry,
                         recency_valid_until=expiry,qualification_valid_until={"A321":expiry}))
    assert {"LICENCE_EXPIRED","MEDICAL_EXPIRED","RECENCY_EXPIRED","QUALIFICATION_EXPIRED"}<=codes(findings)


def test_night_standby_split_augmentation_complement_and_visa_are_hard_findings():
    crew,assignment=scenario(start=NOW.replace(hour=3),hours=10)
    context=complete_context(consecutive_night_duties=3,standby_minutes_before_report=600,
        split_break_minutes=60,split_break_approved=False,augmented_crew_count=2,
        rest_facility_class="class-3",required_roles=frozenset({"captain","first-officer","cabin-lead"}),
        assigned_roles=frozenset({"captain"}),visa_and_transit_allowed=False)
    result=codes(OperationalLegalityEvaluator(LIMITS).evaluate(crew,assignment,context))
    assert {"CONSECUTIVE_NIGHT_LIMIT","STANDBY_PLUS_DUTY_LIMIT","SPLIT_DUTY_NOT_CREDITABLE",
            "AUGMENTED_COMPLEMENT_INSUFFICIENT","INFLIGHT_REST_FACILITY_INELIGIBLE",
            "CREW_COMPLEMENT_INCOMPLETE","IMMIGRATION_INFEASIBLE"}<=result
