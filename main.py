"""Canonical SkySolver web entry point.

Keep this module aligned with the dashboard HTTP server so local development
and Railway use the same surface.
"""

from deployment.app_server import run_app


if __name__ == "__main__":
    run_app()
