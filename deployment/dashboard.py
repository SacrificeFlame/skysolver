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
from datetime import datetime
from typing import Dict, List, Any, Optional
from http.server import HTTPServer, BaseHTTPRequestHandler

# Project root (parent of deployment/) — holds index.html + stitch/ assets.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Metrics storage (in production: Prometheus). File-backed so the web server
# and solver/replay processes share one source of truth.
_METRICS_FILE = ".sky_metrics.json"
_TEMPLATE = os.path.join(os.path.dirname(__file__), "dashboard.html")

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
}

# In-memory rolling event feed (capped). Persisted to file too so a fresh
# browser tab can replay recent activity.
_events: List[Dict[str, Any]] = []
_EVENTS_FILE = ".sky_events.json"
_EVENT_CAP = 200


# --------------------------------------------------------------------------
# Storage helpers
# --------------------------------------------------------------------------

def _load_metrics() -> Dict[str, Any]:
    if os.path.exists(_METRICS_FILE):
        try:
            with open(_METRICS_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
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
    return []


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


def get_metrics() -> Dict[str, Any]:
    """Get current metrics snapshot (merged with shared file)."""
    global _metrics
    _metrics = _load_metrics()
    start = _metrics["start_time"]
    try:
        start_dt = datetime.fromisoformat(start) if isinstance(start, str) else start
        uptime = (datetime.now() - start_dt).total_seconds()
    except (ValueError, TypeError):
        uptime = 0.0
    return {**_metrics, "uptime_s": uptime}


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
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/ops"):
            self._serve_dashboard()
        elif path == "/ops":
            self._serve_dashboard()
        elif path == "/api/metrics":
            self._serve_json(get_metrics())
        elif path == "/api/events":
            self._serve_json(_load_events())
        elif path == "/api/health":
            self._serve_json({"status": "healthy"})
        elif path.startswith("/stitch/"):
            # Serve pulled Stitch screen assets (html + png) from project root.
            rel = os.path.normpath(path.lstrip("/")).replace("\\", "/")
            if rel.startswith("stitch/"):
                self._serve_static(os.path.join(_ROOT, rel))
            else:
                self._serve_404()
        else:
            self._serve_404()

    def _serve_dashboard(self):
        try:
            with open(_TEMPLATE, "r", encoding="utf-8") as f:
                html = f.read()
        except OSError:
            html = "<h1>Dashboard template missing: dashboard.html</h1>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def do_POST(self):
        path = self.path.split("?")[0]
        if path == "/api/chaos":
            self._serve_json({"status": trigger_chaos()})
        else:
            self._serve_404()

    def _serve_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(data, default=str).encode())

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
    server = HTTPServer(("0.0.0.0", port), DashboardHandler)
    print(f"SkySolver v2 Dashboard (Live Airport Ops Center) -> http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_dashboard()
