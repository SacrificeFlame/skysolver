"""
SkySolver v2 - Observability Dashboard (Live Digital Airport Ops Center)

Serves a canvas-animated "digital airport" with planes taxiing, taking off,
and landing in real time, driven by live solve events from the solver/replay
processes. Launch with: python -m deployment.dashboard
"""

from __future__ import annotations

import os
import json
import math
import threading
import hmac
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

from passengers.engine import PassengerRecoveryEngine
from passengers.event_store import PassengerEventStore
from passengers.models import Passenger, PassengerStatus
from passengers.routes.generator import FlightEdge, ItineraryGenerator
from deployment.recovery_api import recovery_store, WorkflowError

# Project root (parent of deployment/) — holds index.html + stitch/ assets.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Metrics storage (in production: Prometheus). File-backed so the web server
# and solver/replay processes share one source of truth.
_METRICS_FILE = ".sky_metrics.json"
_TEMPLATE = os.path.join(os.path.dirname(__file__), "dashboard.html")
_FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "frontend", "dist")

# Static content types for the dashboard hub + Stitch screen assets.
_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".ico": "image/x-icon",
}

_metrics: Dict[str, Any] = {
    "start_time": datetime.now().isoformat(),
    "partitions": {},
    "sla_breaches": 0,
    "tier_usage": {"tier1": 0, "tier2": 0, "tier3": 0},
    "total_solves": 0,
    "cross_partition_moves": 0,
    "legal_violations": 0,
    "passenger_metrics": {
        "disrupted_pax": 38,
        "recovered_pax": 24,
        "compensation_estimate": 18250,
        "backlog": [
            {"id": "P-104", "route": "LAX → DEN → ORD", "priority": "High", "status": "Rebooked"},
            {"id": "P-221", "route": "SEA → DFW → JFK", "priority": "Medium", "status": "Hotel required"},
            {"id": "P-387", "route": "BOS → ATL → MIA", "priority": "Critical", "status": "Standby"},
        ],
        "inventory": [
            {"flight": "AA118", "economy": "7/12", "business": "2/4", "status": "Open"},
            {"flight": "UA512", "economy": "3/9", "business": "4/4", "status": "Limited"},
            {"flight": "DL221", "economy": "11/14", "business": "1/3", "status": "Open"},
        ],
        "hotel_actions": [
            {"city": "Chicago", "hotel": "Westin O’Hare", "rooms": 6, "status": "Assigned"},
            {"city": "Dallas", "hotel": "Hyatt Regency", "rooms": 3, "status": "Pending"},
        ],
    },
}

# In-memory rolling event feed (capped). Persisted to file too so a fresh
# browser tab can replay recent activity.
_events: List[Dict[str, Any]] = []
_EVENTS_FILE = ".sky_events.json"
_EVENT_CAP = 200


def _build_passenger_metrics(base_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create passenger metrics from the passenger recovery engine state."""
    base_metrics = base_metrics or {}
    graph = {
        "LAX": [
            FlightEdge(flight_id="AA118", origin="LAX", destination="DEN", score=0.94),
            FlightEdge(flight_id="UA512", origin="LAX", destination="ORD", score=0.91),
        ],
        "DEN": [
            FlightEdge(flight_id="DL221", origin="DEN", destination="ORD", score=0.92),
        ],
        "ORD": [],
    }
    generator = ItineraryGenerator(graph)
    engine = PassengerRecoveryEngine(PassengerEventStore())

    sample_passengers = [
        Passenger(passenger_id="P-104", pnr="PNR-104", origin="LAX", destination="ORD", current_airport="LAX", cabin="business", frequent_flyer_tier=2, medical_requirements=["wheelchair"], wheelchair_required=True),
        Passenger(passenger_id="P-221", pnr="PNR-221", origin="SEA", destination="JFK", current_airport="SEA", cabin="economy", frequent_flyer_tier=1, minor=True),
        Passenger(passenger_id="P-387", pnr="PNR-387", origin="BOS", destination="MIA", current_airport="BOS", cabin="first", frequent_flyer_tier=3),
    ]

    backlog = []
    recovered = 0
    compensation = 0
    for passenger in sample_passengers:
        routes = generator.generate(passenger.origin, passenger.destination, max_options=3)
        if not routes:
            continue
        decision = engine.recover(passenger, routes)
        if decision.status == PassengerStatus.REBOOKED:
            recovered += 1
        status = "Rebooked" if decision.status == PassengerStatus.REBOOKED else "Standby"
        priority = "Critical" if passenger.medical_requirements or passenger.wheelchair_required else "Medium"
        backlog.append({
            "id": passenger.passenger_id,
            "route": f"{passenger.origin} → {passenger.destination}",
            "priority": priority,
            "status": status,
        })
        compensation += 320 + (passenger.frequent_flyer_tier * 120)

    inventory = [
        {"flight": "AA118", "economy": "7/12", "business": "2/4", "status": "Open"},
        {"flight": "UA512", "economy": "3/9", "business": "4/4", "status": "Limited"},
        {"flight": "DL221", "economy": "11/14", "business": "1/3", "status": "Open"},
    ]
    hotel_actions = [
        {"city": "Chicago", "hotel": "Westin O’Hare", "rooms": 6, "status": "Assigned"},
        {"city": "Dallas", "hotel": "Hyatt Regency", "rooms": 3, "status": "Pending"},
    ]

    return {
        "disrupted_pax": len(backlog),
        "recovered_pax": recovered,
        "compensation_estimate": compensation + (base_metrics.get("sla_breaches", 0) * 750),
        "backlog": backlog,
        "inventory": inventory,
        "hotel_actions": hotel_actions,
    }


# --------------------------------------------------------------------------
# Storage helpers
# --------------------------------------------------------------------------

def _seed_demo_state() -> None:
    global _metrics, _events
    if os.path.exists(_METRICS_FILE) and os.path.exists(_EVENTS_FILE):
        return

    _metrics.update({
        "start_time": datetime.now().isoformat(),
        "partitions": {
            "DEN": {"solves": 14, "avg_coverage": 0.96, "avg_time_s": 0.31, "last_tier": 1},
            "ORD": {"solves": 11, "avg_coverage": 0.92, "avg_time_s": 0.38, "last_tier": 2},
            "ATL": {"solves": 9, "avg_coverage": 0.88, "avg_time_s": 0.46, "last_tier": 1},
            "LAX": {"solves": 8, "avg_coverage": 0.91, "avg_time_s": 0.42, "last_tier": 1},
        },
        "sla_breaches": 1,
        "tier_usage": {"tier1": 18, "tier2": 6, "tier3": 4},
        "total_solves": 28,
        "cross_partition_moves": 3,
        "legal_violations": 1,
        "passenger_metrics": _build_passenger_metrics({
            "sla_breaches": 1,
            "partitions": {
                "DEN": {"avg_coverage": 0.96},
            },
        }),
    })

    _events[:] = [
        {"ts": datetime.now().isoformat(), "kind": "solve", "partition": "DEN", "tier": 1, "coverage": 0.96, "elapsed_s": 0.31},
        {"ts": datetime.now().isoformat(), "kind": "solve", "partition": "ORD", "tier": 2, "coverage": 0.92, "elapsed_s": 0.38},
        {"ts": datetime.now().isoformat(), "kind": "xpartition", "partition": "ATL"},
        {"ts": datetime.now().isoformat(), "kind": "sla_breach", "partition": "LAX"},
    ]

    _save_metrics()
    _save_events()


def _load_metrics() -> Dict[str, Any]:
    if os.path.exists(_METRICS_FILE):
        try:
            with open(_METRICS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    _seed_demo_state()
    return _metrics


def _save_metrics() -> None:
    try:
        with open(_METRICS_FILE, "w") as f:
            json.dump(_metrics, f, default=str)
    except OSError:
        pass


def _load_events() -> List[Dict[str, Any]]:
    if os.path.exists(_EVENTS_FILE):
        try:
            with open(_EVENTS_FILE) as f:
                return json.load(f)[-_EVENT_CAP:]
        except (json.JSONDecodeError, OSError):
            pass
    _seed_demo_state()
    return _events[-_EVENT_CAP:]


def _save_events() -> None:
    try:
        with open(_EVENTS_FILE, "w") as f:
            json.dump(_events[-_EVENT_CAP:], f, default=str)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Recording API (called by solver / chaos harness)
# --------------------------------------------------------------------------

def record_solve(partition_id: str, tier: int, coverage: float, elapsed_s: float):
    """Record a solve event (shared across processes via file)."""
    global _metrics, _events
    _metrics = _load_metrics()

    if partition_id not in _metrics["partitions"]:
        _metrics["partitions"][partition_id] = {
            "solves": 0, "avg_coverage": 0.0, "avg_time_s": 0.0, "last_tier": tier,
        }

    p = _metrics["partitions"][partition_id]
    p["solves"] += 1
    p["avg_coverage"] = (p["avg_coverage"] * (p["solves"] - 1) + coverage) / p["solves"]
    p["avg_time_s"] = (p["avg_time_s"] * (p["solves"] - 1) + elapsed_s) / p["solves"]
    p["last_tier"] = tier

    _metrics["total_solves"] += 1
    tier_key = f"tier{tier}"
    if tier_key in _metrics["tier_usage"]:
        _metrics["tier_usage"][tier_key] += 1

    _events.append({
        "ts": datetime.now().isoformat(),
        "kind": "solve",
        "partition": partition_id,
        "tier": tier,
        "coverage": round(coverage, 3),
        "elapsed_s": round(elapsed_s, 4),
    })
    _events = _events[-_EVENT_CAP:]

    _save_metrics()
    _save_events()


def record_sla_breach():
    global _metrics, _events
    _metrics = _load_metrics()
    _metrics["sla_breaches"] += 1
    _events.append({"ts": datetime.now().isoformat(), "kind": "sla_breach"})
    _events = _events[-_EVENT_CAP:]
    _save_metrics()
    _save_events()


def record_cross_partition_move():
    global _metrics, _events
    _metrics = _load_metrics()
    _metrics["cross_partition_moves"] += 1
    _events.append({"ts": datetime.now().isoformat(), "kind": "xpartition"})
    _events = _events[-_EVENT_CAP:]
    _save_metrics()
    _save_events()


def record_ui_action(kind: str, detail: str = "", partition: str = "GLOBAL"):
    """Record a dashboard-triggered operational event for the live feed."""
    global _metrics, _events
    _metrics = _load_metrics()
    _events.append({
        "ts": datetime.now().isoformat(),
        "kind": kind,
        "partition": partition,
        "detail": detail,
    })
    _events = _events[-_EVENT_CAP:]
    _save_events()


def get_metrics() -> Dict[str, Any]:
    """Get current metrics snapshot (merged with shared file)."""
    global _metrics
    _metrics = _load_metrics()
    if "passenger_metrics" not in _metrics or not _metrics["passenger_metrics"]:
        _metrics["passenger_metrics"] = _build_passenger_metrics(_metrics)
    start = _metrics["start_time"]
    try:
        start_dt = datetime.fromisoformat(start) if isinstance(start, str) else start
        uptime = (datetime.now() - start_dt).total_seconds()
    except (ValueError, TypeError):
        uptime = 0.0
    return {**_metrics, "uptime_s": uptime}


def get_operational_overview() -> Dict[str, Any]:
    """Versioned dashboard contract; all demo data is explicitly identified."""
    metrics = get_metrics()
    events = _load_events()
    return {
        "api_version": "v1", "data_mode": "synthetic-demo",
        "generated_at": datetime.now().isoformat(),
        "disruption": {
            "type": "winter-weather", "epicenter": "DEN", "status": "active",
            "affected_flights": sum(max(1, int((1 - p.get("avg_coverage", 1)) * 100)) for p in metrics.get("partitions", {}).values()),
        },
        "recovery": {
            "total_solves": metrics.get("total_solves", 0),
            "tier_usage": metrics.get("tier_usage", {}),
            "legal_violations": metrics.get("legal_violations", 0),
            "pending_intervention": sum(1 for e in events if e.get("kind") in {"sla_breach", "review_required"}),
        },
        "partitions": metrics.get("partitions", {}),
        "passengers": metrics.get("passenger_metrics", {}),
        "recent_decisions": events[-25:],
    }


# --------------------------------------------------------------------------
# Chaos / replay trigger (drives the live dashboard with real solve data)
# --------------------------------------------------------------------------

_chaos_running = False
_chaos_lock = threading.Lock()


def _run_chaos():
    """Run the Elliott-scale replay in a background thread.

    The harness calls record_solve / record_sla_breach as it progresses, so the
    live dashboard updates in real time while the replay runs.
    """
    global _chaos_running, _events
    try:
        from chaos.replay import run_elliott_sla_test
        passed = run_elliott_sla_test()
        _events.append({
            "ts": datetime.now().isoformat(),
            "kind": "chaos_done",
            "detail": "Elliott replay complete — SLA " + ("PASS" if passed else "FAIL"),
        })
        _events = _events[-_EVENT_CAP:]
        _save_events()
    except Exception as e:  # noqa: BLE001 - surface harness failures to the UI
        _events.append({
            "ts": datetime.now().isoformat(),
            "kind": "chaos_error",
            "detail": f"replay error: {e}",
        })
        _events = _events[-_EVENT_CAP:]
        _save_events()
        print(f"[chaos] replay error: {e}")
    finally:
        _chaos_running = False


def trigger_chaos() -> str:
    """Start a chaos replay if one isn't already running. Returns a status."""
    global _chaos_running, _events
    with _chaos_lock:
        if _chaos_running:
            return "already_running"
        _chaos_running = True
    _events.append({
        "ts": datetime.now().isoformat(),
        "kind": "chaos_start",
        "detail": "Winter Storm Elliott replay initiated",
    })
    _events = _events[-_EVENT_CAP:]
    _save_events()
    t = threading.Thread(target=_run_chaos, daemon=True)
    t.start()
    return "started"


# --------------------------------------------------------------------------
# HTTP server
# --------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/login", "/index.html"):
            self._serve_login()
        elif path in ("/dashboard", "/ops"):
            self._serve_dashboard()
        elif path == "/api/metrics":
            self._serve_json(get_metrics())
        elif path == "/api/events":
            self._serve_json(_load_events())
        elif path == "/api/health":
            self._serve_json({"status": "healthy"})
        elif path == "/api/v1/health/live":
            self._serve_json({"status": "live", "component": "operations-api"})
        elif path == "/api/v1/health/ready":
            self._serve_json({"status": "ready", "event_store": "file-demo", "ruleset": "synthetic-far117-v2"})
        elif path == "/api/v1/overview":
            self._serve_json(get_operational_overview())
        elif path == "/api/v1/disruptions":
            self._serve_json({"items": recovery_store.disruptions(), "data_mode": "synthetic-demo"})
        elif path.startswith("/api/v1/disruptions/"):
            self._api(lambda: recovery_store.disruption(path.rsplit("/", 1)[-1]))
        elif path.startswith("/api/v1/flights/"):
            self._api(lambda: recovery_store.flight(path.rsplit("/", 1)[-1]))
        elif path == "/api/v1/audit":
            self._serve_json({"items": recovery_store.audit()})
        elif path == "/api/v1/events":
            self._serve_event_stream(recovery_store.events())
        elif path.startswith("/api/v1/recoveries/"):
            parts = [p for p in path.split("/") if p]
            recovery_id = parts[3] if len(parts) > 3 else ""
            if len(parts) == 4:
                self._api(lambda: recovery_store.get(recovery_id))
            elif len(parts) == 5 and parts[4] == "candidates":
                self._api(lambda: {"items": recovery_store.candidates(recovery_id)})
            else:
                self._serve_404()
        elif path == "/api/login":
            self._serve_json({"ok": True, "redirect": "/dashboard"})
        elif path.startswith("/stitch/"):
            # Serve pulled Stitch screen assets (html + png) from project root.
            rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
            if rel.startswith("stitch/"):
                self._serve_static(os.path.join(_ROOT, rel))
            else:
                self._serve_404()
        elif path.startswith("/assets/"):
            rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
            if rel.startswith("assets/"):
                self._serve_static(os.path.join(_FRONTEND_DIST, rel))
            else:
                self._serve_404()
        else:
            self._serve_404()

    def _serve_dashboard(self):
        built_index = os.path.join(_FRONTEND_DIST, "index.html")
        try:
            with open(built_index if os.path.exists(built_index) else _TEMPLATE, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            html = "<h1>Dashboard template missing: dashboard.html</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_login(self):
        login_path = os.path.join(os.path.dirname(__file__), "login.html")
        try:
            with open(login_path, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            html = "<h1>Login page missing</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/chaos":
            self._serve_json({"status": trigger_chaos()})
        elif path == "/api/v1/recoveries":
            payload = self._read_json()
            if payload is not None:
                self._api(lambda: recovery_store.create(payload), status=201)
        elif path.startswith("/api/v1/recoveries/"):
            parts = [p for p in path.split("/") if p]
            recovery_id = parts[3] if len(parts) > 3 else ""
            action = parts[4] if len(parts) > 4 else ""
            payload = self._read_json()
            if payload is None:
                return
            operations = {
                "decisions": lambda: recovery_store.decide(recovery_id, payload),
                "validate": lambda: recovery_store.validate(recovery_id, payload),
                "deploy": lambda: recovery_store.deploy(recovery_id, payload, self.headers.get("Idempotency-Key", "")),
                "rollback": lambda: recovery_store.rollback(recovery_id, payload),
            }
            if action in operations:
                self._api(operations[action])
            else:
                self._serve_404()
        elif path == "/api/v1/recovery/run":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                self._serve_json({"error": "invalid_json"}, status=400)
                return
            partition = str(payload.get("partition_id", "DEN"))
            record_ui_action("recovery_requested", "Tiered recovery orchestration requested", partition)
            self._serve_json({"status": "accepted", "partition_id": partition, "data_mode": "synthetic-demo"}, status=202)
        elif path == "/api/rules/validate":
            record_ui_action("rules_validate", "Rules stack validated")
            self._serve_json({"status": "ok", "action": "validate"})
        elif path == "/api/rules/deploy":
            record_ui_action("rules_deploy", "Rules stack deployed")
            self._serve_json({"status": "ok", "action": "deploy"})
        elif path == "/api/rules/execute":
            record_ui_action("rules_execute", "Simulation executed")
            self._serve_json({"status": "ok", "action": "execute"})
        elif path == "/api/review/action":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8") if length else "{}"
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            action = str(payload.get("action", "review"))
            case_id = str(payload.get("case_id", "current"))
            record_ui_action(f"review_{action}", f"Review action {action} for {case_id}")
            self._serve_json({"status": "ok", "action": action, "case_id": case_id})
        elif path == "/api/login":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                payload = {}
            user = payload.get("username", "")
            password = payload.get("password", "")
            expected_user = os.environ.get("SKYSOLVER_DEMO_USER", "ops")
            expected_password = os.environ.get("SKYSOLVER_DEMO_PASSWORD", "sky2026")
            if hmac.compare_digest(str(user), expected_user) and hmac.compare_digest(str(password), expected_password):
                self._serve_json({"ok": True, "redirect": "/dashboard"})
            else:
                self._serve_json({"ok": False, "error": "Invalid credentials"}, status=401)
        else:
            self._serve_404()

    def _serve_json(self, data, status=200):
        body = json.dumps(data, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        try:
            return json.loads(self.rfile.read(length).decode("utf-8") if length else "{}")
        except json.JSONDecodeError:
            self._serve_json({"error": "invalid_json", "message": "Request body must be valid JSON"}, status=400)
            return None

    def _api(self, operation, status=200):
        try:
            self._serve_json(operation(), status=status)
        except WorkflowError as exc:
            self._serve_json({"error": exc.code, "message": exc.message, "correlation_id": str(uuid.uuid4()), "rule_violations": []}, status=exc.status)

    def _serve_event_stream(self, events):
        body = "".join(f"event: recovery\ndata: {json.dumps(event)}\n\n" for event in events).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, fs_path: str):
        ext = os.path.splitext(fs_path)[1].lower()
        ctype = _CONTENT_TYPES.get(ext, "application/octet-stream")
        try:
            with open(fs_path, "rb") as f:
                data = f.read()
        except OSError:
            self._serve_404()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_404(self):
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass  # Suppress


def run_dashboard(port: int = 8501):
    """Run the dashboard HTTP server."""
    _seed_demo_state()
    server = ThreadingHTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"SkySolver v2 Dashboard (Live Airport Ops Center) -> http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_dashboard()
