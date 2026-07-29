import json
import threading
import urllib.request
from http.server import HTTPServer

from deployment.dashboard import DashboardHandler, _build_passenger_metrics


def _serve_once():
    server = HTTPServer(("127.0.0.1", 0), DashboardHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def _request(path: str, method: str = "GET", body: bytes | None = None):
    server, port, thread = _serve_once()
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=body)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=2) as resp:
            payload = resp.read().decode("utf-8")
            return resp.status, resp.headers.get_content_type(), payload
    except Exception as exc:  # pragma: no cover - used for test clarity
        raise AssertionError(f"request failed for {path}: {exc}") from exc
    finally:
        server.shutdown()
        thread.join(timeout=2)


def test_login_page_serves_html():
    status, ctype, body = _request("/")
    assert status == 200
    assert ctype == "text/html"
    assert "SkySolver Mission Control" in body


def test_login_endpoint_accepts_valid_credentials():
    payload = json.dumps({"username": "ops", "password": "sky2026"}).encode("utf-8")
    status, ctype, body = _request("/api/login", method="POST", body=payload)
    assert status == 200
    assert ctype == "application/json"
    data = json.loads(body)
    assert data["ok"] is True
    assert data["redirect"] == "/dashboard"


def test_passenger_metrics_are_derived_from_recovery_engine():
    metrics = _build_passenger_metrics({"sla_breaches": 2, "partitions": {"DEN": {"avg_coverage": 0.94}}})
    assert metrics["disrupted_pax"] >= 1
    assert metrics["recovered_pax"] >= 0
    assert metrics["backlog"]
    assert metrics["inventory"]
    assert metrics["hotel_actions"]
