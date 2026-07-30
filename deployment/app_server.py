from __future__ import annotations

import os

from deployment.dashboard import run_dashboard


def run_app(port=None):
    port = int(port or os.environ.get("PORT", "8000"))
    run_dashboard(port)


if __name__ == "__main__":
    run_app()
