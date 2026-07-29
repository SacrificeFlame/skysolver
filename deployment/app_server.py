from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
for candidate in (str(ROOT), str(ROOT / "deployment")):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

try:
    from deployment.dashboard import get_metrics, _load_events, record_solve, record_sla_breach
except ModuleNotFoundError:
    from dashboard import get_metrics, _load_events, record_solve, record_sla_breach


class AppHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/metrics":
            self._json(get_metrics())
        elif path == "/api/events":
            self._json(_load_events())
        elif path == "/":
            self._serve_html("login.html")
        elif path == "/dashboard":
            self._serve_html("dashboard.html")
        else:
            self._serve_404()

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/login":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            payload = json.loads(body)
            user = payload.get("username", "")
            password = payload.get("password", "")
            if user == "ops" and password == "sky2026":
                self._json({"ok": True, "redirect": "/dashboard"})
            else:
                self._json({"ok": False, "error": "Invalid credentials"}, status=401)
        else:
            self._serve_404()

    def _json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_html(self, filename):
        root = os.path.dirname(__file__)
        path = os.path.join(root, filename)
        with open(path, "r", encoding="utf-8") as fh:
            body = fh.read().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_404(self):
        self.send_response(404)
        self.end_headers()


def run_app(port=None):
    port = int(port or os.environ.get("PORT", "8000"))
    server = HTTPServer(("0.0.0.0", port), AppHandler)
    print(f"SkySolver UI listening on http://localhost:{port}")
    server.serve_forever()


if __name__ == "__main__":
    run_app()
