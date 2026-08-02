import uuid

from fastapi.testclient import TestClient

from deployment.auth import COOKIE_NAME, issue_session
from deployment.production_api import create_app


def client():
    instance = TestClient(create_app())
    response = instance.post("/api/login", json={"username": "ops", "password": "sky2026"})
    assert response.status_code == 200
    return instance


def mutation_headers(version: int = 0, correlation_id: str | None = None):
    return {
        "Idempotency-Key": f"test-{uuid.uuid4()}",
        "Expected-State-Version": str(version),
        "X-Correlation-ID": correlation_id or str(uuid.uuid4()),
        "X-Causation-ID": str(uuid.uuid4()),
    }


def test_openapi_exposes_versioned_contracts():
    response = TestClient(create_app()).get("/api/v1/openapi.json")
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert "/api/v1/data-health" in paths
    assert "/api/v1/recoveries" in paths
    assert "/api/v1/candidates/{candidate_id}/hold" in paths
    assert "/api/v1/recoveries/{recovery_id}/deployments" in paths
    assert "/api/v1/recoveries/{recovery_id}/suggestions" in paths
    assert "/api/v1/recoveries/{recovery_id}/suggestions/{suggestion_id}/decisions" in paths
    assert "/api/v1/deployments/{deployment_id}" in paths
    assert "/api/v1/deployments/{deployment_id}/retry" in paths
    assert "/api/v1/deployments/{deployment_id}/compensate" in paths
    assert "/api/v1/events" in paths


def test_api_requires_signed_identity():
    response = TestClient(create_app()).get("/api/v1/overview")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "authentication_required"


def test_dashboard_redirects_anonymous_browser_to_login_without_weakening_api_auth():
    instance = TestClient(create_app(), follow_redirects=False)
    response = instance.get("/dashboard")
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert instance.get("/api/v1/overview").status_code == 401


def test_dashboard_is_served_after_demo_login():
    response = client().get("/dashboard")
    assert response.status_code == 200
    assert 'id="root"' in response.text and "SkySolver" in response.text


def test_data_health_blocks_operational_deployment():
    response = client().get("/api/v1/data-health")
    assert response.status_code == 200
    assert response.json()["deployment_allowed"] is False
    assert response.json()["findings"][0]["severity"] == "blocking"


def test_mutation_headers_are_required():
    response = client().post("/api/v1/recoveries", json={"disruption_id": "DSP-DEL-0726", "partition_id": "DEL", "objective": "balanced"})
    assert response.status_code == 422


def test_correlation_id_propagates_to_response_and_envelope():
    correlation_id = str(uuid.uuid4())
    response = client().post(
        "/api/v1/recoveries", headers=mutation_headers(correlation_id=correlation_id),
        json={"disruption_id": "DSP-DEL-0726", "partition_id": "DEL", "objective": "balanced"},
    )
    assert response.status_code == 201
    assert response.headers["X-Correlation-ID"] == correlation_id
    assert response.json()["correlation_id"] == correlation_id


def test_recovery_contract_and_carrier_write_gate():
    session = client()
    created = session.post(
        "/api/v1/recoveries",
        headers=mutation_headers(),
        json={"disruption_id": "DSP-DEL-0726", "partition_id": "DEL", "objective": "balanced"},
    )
    assert created.status_code == 201
    recovery = created.json()["recovery"]
    selected = session.post(
        f"/api/v1/recoveries/{recovery['id']}/decisions",
        headers=mutation_headers(recovery["state_version"]),
        json={"candidate_id": recovery["candidates"][0]["id"], "action": "approve", "reason": ""},
    )
    assert selected.status_code == 200
    selected_recovery = selected.json()["recovery"]
    validated = session.post(
        f"/api/v1/candidates/{selected_recovery['selected_candidate_id']}/validate?recovery_id={recovery['id']}",
        headers=mutation_headers(selected_recovery["state_version"]),
    )
    assert validated.status_code == 200
    validated_recovery = validated.json()["recovery"]
    session.cookies.set(COOKIE_NAME, issue_session("manager-1", role="duty-manager"))
    approved = session.post(
        f"/api/v1/recoveries/{recovery['id']}/approvals",
        headers=mutation_headers(validated_recovery["state_version"]),
        json={"reason": "Reviewed legality and operational scope"},
    )
    assert approved.status_code == 200
    approved_recovery = approved.json()["recovery"]
    session.cookies.set(COOKIE_NAME, issue_session("controller-1", role="deployment-controller"))
    deployed = session.post(
        f"/api/v1/recoveries/{recovery['id']}/deployments",
        headers=mutation_headers(approved_recovery["state_version"]),
    )
    assert deployed.status_code == 403
    assert deployed.json()["error"] == "carrier_writes_disabled"


def test_search_uses_real_fixture_records_and_labels_authority():
    response = client().get("/api/v1/search", params={"q": "VT-EXA"})
    assert response.status_code == 200
    assert response.json()["items"][0]["id"] == "AI421"
    assert response.json()["authoritative"] is False


def test_tier3_queue_is_authenticated_paginated_and_never_auto_approved():
    session=client()
    created=session.post("/api/v1/recoveries",headers=mutation_headers(),json={"disruption_id":"DSP-DEL-0726","partition_id":"DEL","objective":"balanced"})
    recovery=created.json()["recovery"]
    response=session.get(f"/api/v1/recoveries/{recovery['id']}/suggestions",params={"offset":0,"limit":10})
    assert response.status_code==200
    queue=response.json()
    assert queue["limit"]==10
    assert queue["state_version"]==recovery["state_version"]
    assert all(item["status"]=="pending" for item in queue["items"])
