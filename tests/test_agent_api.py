"""HTTP surface for the recovery agent."""

from fastapi.testclient import TestClient

from deployment.production_api import create_app


def client():
    instance = TestClient(create_app())
    response = instance.post("/api/login", json={"username": "ops", "password": "sky2026"})
    assert response.status_code == 200
    return instance


def test_agent_endpoints_require_authentication():
    anonymous = TestClient(create_app())
    assert anonymous.post("/api/v1/agent/run", json={}).status_code == 401
    assert anonymous.get("/api/v1/agent/tools").status_code == 401


def test_agent_endpoints_are_published_in_the_contract():
    paths = TestClient(create_app()).get("/api/v1/openapi.json").json()["paths"]
    assert "/api/v1/agent/run" in paths
    assert "/api/v1/agent/tools" in paths


def test_tools_endpoint_publishes_the_schemas_and_the_guarantees():
    payload = client().get("/api/v1/agent/tools").json()
    names = {tool["name"] for tool in payload["items"]}
    assert {"preview_reassignment", "commit_reassignment", "escalate_to_tier3"} <= names
    for tool in payload["items"]:
        assert tool["description"]
        assert tool["input_schema"]["type"] == "object"
    assert len(payload["guarantees"]) == 3


def test_run_returns_the_plan_and_the_full_trace():
    payload = client().post("/api/v1/agent/run", json={"planner": "deterministic"}).json()

    assert payload["summary"]["resolved"] == 2
    assert payload["summary"]["escalated"] == 1
    assert payload["summary"]["unresolved"] == 0
    assert payload["requested_planner"] == "deterministic"

    assert {r["flight_id"] for r in payload["resolved"]} == {"AI421", "UK945"}
    assert {e["flight_id"] for e in payload["escalated"]} == {"AI807"}

    steps = payload["trace"]["steps"]
    assert len(steps) == payload["summary"]["tool_calls"]
    for step in steps:
        assert step["rationale"] and step["outcome"] and step["phase"]


def test_run_defaults_to_the_deterministic_planner():
    payload = client().post("/api/v1/agent/run", json={}).json()
    assert payload["planner"] == "deterministic"


def test_escalation_reaches_the_client_with_real_violation_codes():
    payload = client().post("/api/v1/agent/run", json={}).json()
    case = next(e for e in payload["escalated"] if e["flight_id"] == "AI807")
    codes = {code for blocker in case["blockers"] for code in blocker["violations"]}
    assert codes == {"MIN_REST", "CREW_POSITION"}


def test_unconfigured_llm_planner_degrades_instead_of_failing(monkeypatch):
    for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    response = client().post("/api/v1/agent/run", json={"planner": "gemini"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["requested_planner"] == "gemini"
    assert payload["planner"] == "deterministic"
    assert any("GEMINI_API_KEY" in note for note in payload["notes"])
    # The plan is unaffected by the missing credential.
    assert payload["summary"]["resolved"] == 2
    assert payload["summary"]["unresolved"] == 0


def test_unknown_planner_is_rejected_by_the_schema():
    assert client().post("/api/v1/agent/run", json={"planner": "hal9000"}).status_code == 422


# Regression: role elevation used to sign in again with credentials compiled
# into the frontend bundle. Changing the demo password broke approval and
# logged the operator out, because the failed login returned 401.
def test_role_can_be_assumed_without_re_authenticating():
    instance = client()
    response = instance.post("/api/v1/session/role", json={"role": "duty-manager"})

    assert response.status_code == 200
    assert response.json()["operator"]["role"] == "duty-manager"
    assert "Set-Cookie" in response.headers


def test_assuming_a_role_requires_an_existing_session():
    anonymous = TestClient(create_app())
    assert anonymous.post("/api/v1/session/role", json={"role": "duty-manager"}).status_code == 401


def test_an_unknown_role_is_rejected():
    assert client().post("/api/v1/session/role", json={"role": "root"}).status_code == 422


def test_role_switch_survives_a_changed_demo_password(monkeypatch):
    """The whole point: elevation must not depend on a password the UI knows."""
    monkeypatch.setenv("SKYSOLVER_DEMO_USER", "someone-else")
    monkeypatch.setenv("SKYSOLVER_DEMO_PASSWORD", "a-different-password")
    instance = TestClient(create_app())
    assert instance.post(
        "/api/login", json={"username": "someone-else", "password": "a-different-password"}
    ).status_code == 200

    # ops/sky2026 would now fail, but elevation does not use them.
    response = instance.post("/api/v1/session/role", json={"role": "deployment-controller"})
    assert response.status_code == 200
    assert response.json()["operator"]["role"] == "deployment-controller"
