import base64
import json

from deployment.auth import issue_session, verify_session


def test_signed_session_round_trip():
    principal = verify_session(issue_session("scheduler-17"))
    assert principal is not None
    assert principal.subject == "scheduler-17"
    assert principal.role == "scheduler-demo"
    assert principal.tenant_id == "synthetic-airline"


def test_tampered_session_is_rejected():
    token = issue_session("scheduler-17")
    encoded, signature = token.split(".", 1)
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    payload["role"] = "deployment-controller"
    tampered = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    assert verify_session(f"{tampered}.{signature}") is None
