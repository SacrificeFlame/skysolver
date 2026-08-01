from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from rules.certificates import CertificateIssuer
from rules.validation_service import (
    DEMO_CONTEXT, RulesExecutionContext, ValidationExecutor, ValidationRequest, create_validation_app,
)
from rules.operational_profile import OperationalLimits


def request_payload(*, qualification="A321", rest_hours=12):
    start = datetime(2026, 8, 1, 8, tzinfo=timezone.utc)
    return {
        "tenant_id": "airline-1", "recovery_id": "REC-1", "candidate_id": "CAN-1",
        "state_version": 4, "input_snapshot_id": "SNP-1",
        "crew": [{"crew_id": "IC-1", "base_hub": "DEL", "current_location": "DEL",
                  "qualifications": [qualification], "last_rest_end": (start-timedelta(hours=rest_hours)).isoformat()}],
        "assignments": [{"crew_id": "IC-1", "duty_start": start.isoformat(),
                         "duty_end": (start+timedelta(hours=4)).isoformat(),
                         "flight_legs": [{"flight_id": "AI421", "origin": "DEL", "destination": "BOM",
                                          "scheduled_dep": (start+timedelta(hours=1)).isoformat(),
                                          "scheduled_arr": (start+timedelta(hours=3)).isoformat(),
                                          "aircraft_type": "A321"}]}],
        "candidate_artifact": {"candidate_id": "CAN-1", "assignments": ["IC-1:AI421"]},
    }


def operational_evidence():
    return [{
        "crew_id": "IC-1", "evaluated_at": "2026-08-01T08:00:00+00:00", "history_complete": True,
        "accumulated": {"flight_minutes_28d": 1000, "flight_minutes_365d": 10000,
                        "duty_minutes_7d": 1000, "duty_minutes_28d": 4000},
        "licence_valid_until": "2027-08-01T00:00:00+00:00",
        "medical_valid_until": "2027-08-01T00:00:00+00:00",
        "recency_valid_until": "2026-09-01T00:00:00+00:00",
        "qualification_valid_until": {"A321": "2027-08-01T00:00:00+00:00"},
        "acclimatized": True, "timezone_delta_hours": 0, "consecutive_night_duties": 0,
        "required_roles": ["captain"], "assigned_roles": ["captain"],
        "visa_and_transit_allowed": True,
    }]


def test_demo_service_is_separate_but_never_issues_certification():
    client = TestClient(create_validation_app(ValidationExecutor(DEMO_CONTEXT)))
    response = client.post("/v1/validate", json=request_payload())
    assert response.status_code == 200
    assert response.json()["valid"] is True
    assert response.json()["certificate"] is None
    assert "not operator-approved" in response.json()["warning"]


def test_failed_rule_returns_machine_finding_and_calculation_trace():
    result = ValidationExecutor(DEMO_CONTEXT).validate(ValidationRequest.model_validate(request_payload(rest_hours=5)))
    assert result["valid"] is False
    assert result["findings"][0]["code"] == "MIN_REST"
    assert result["calculation_trace"][0]["rule_reference"].startswith("DGCA-CAR")


def test_only_active_operator_approved_context_can_issue_certificate():
    context = RulesExecutionContext("RPK-1", "airline-rules-7", "a"*64, "active",
                                    "operator_approved_certified", "validation-service", "7.0.0")
    issuer = CertificateIssuer("kms-key-7", b"test-key", context.execution_identity,
                               context.service_version, context.assurance_level)
    payload = request_payload(); payload["operational_evidence"] = operational_evidence()
    result = ValidationExecutor(context, issuer, OperationalLimits(context.package_id)).validate(
        ValidationRequest.model_validate(payload))
    assert result["valid"] is True
    assert result["certificate"]["assurance_level"] == "operator_approved_certified"
    assert result["certificate"]["ruleset_version"] == "airline-rules-7"


def test_certified_context_refuses_startup_without_operational_profile():
    context = RulesExecutionContext("RPK-1", "airline-rules-7", "a"*64, "active",
                                    "operator_approved_certified", "validation-service", "7.0.0")
    with __import__("pytest").raises(RuntimeError, match="operational profile"):
        ValidationExecutor(context, CertificateIssuer("key", b"key", "service", "7", "certified"))


def test_certified_validation_without_operational_evidence_cannot_issue_certificate():
    context = RulesExecutionContext("RPK-1", "airline-rules-7", "a"*64, "active",
                                    "operator_approved_certified", "validation-service", "7.0.0")
    executor = ValidationExecutor(context, CertificateIssuer("key", b"key", "service", "7", "certified"),
                                  OperationalLimits(context.package_id))
    result = executor.validate(ValidationRequest.model_validate(request_payload()))
    assert result["valid"] is False and result["certificate"] is None
    assert any(item["code"] == "AUTHORITATIVE_HISTORY_REQUIRED" for item in result["findings"])


def test_missing_crew_reference_is_rejected():
    payload = request_payload(); payload["assignments"][0]["crew_id"] = "IC-MISSING"
    response = TestClient(create_validation_app(ValidationExecutor(DEMO_CONTEXT))).post("/v1/validate", json=payload)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_validation_input"
