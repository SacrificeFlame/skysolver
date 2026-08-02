from __future__ import annotations

import os

import uvicorn


def run_app(port=None):
    uvicorn.run(
        "deployment.production_api:app",
        host="0.0.0.0",
        port=int(port or os.environ.get("PORT", "8000")),
        proxy_headers=True,
        forwarded_allow_ips=os.environ.get("SKYSOLVER_FORWARDED_ALLOW_IPS", "127.0.0.1"),
    )


if __name__ == "__main__":
    run_app()
