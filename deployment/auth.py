"""Minimal containment authentication for the synthetic demo.

This is intentionally a bridge to enterprise OIDC, not a substitute for it.
Sessions are signed, short lived, HttpOnly and server-derived. Production mode
refuses to start without an explicit signing secret and configured credentials.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Mapping, Optional


COOKIE_NAME = "skysolver_demo_session"
SESSION_SECONDS = 8 * 60 * 60
_EPHEMERAL_SECRET = secrets.token_bytes(32)


@dataclass(frozen=True)
class Principal:
    subject: str
    role: str
    tenant_id: str
    expires_at: int
    auth_method: str = "demo-session"
    auth_time: int = 0
    amr: tuple[str, ...] = ()
    base: str | None = None
    stations: tuple[str, ...] = ()


def _secret() -> bytes:
    configured = os.environ.get("SKYSOLVER_SESSION_SECRET")
    if configured:
        return configured.encode("utf-8")
    if os.environ.get("SKYSOLVER_ENV", "development").lower() in {"production", "shadow-production"}:
        raise RuntimeError("SKYSOLVER_SESSION_SECRET is required outside demo environments")
    return _EPHEMERAL_SECRET


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_session(subject: str, role: str = "scheduler-demo", tenant_id: str = "synthetic-airline") -> str:
    payload = {
        "sub": subject,
        "role": role,
        "tenant_id": tenant_id,
        "exp": int(time.time()) + SESSION_SECONDS,
    }
    encoded = _encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = _encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def verify_session(token: str) -> Optional[Principal]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _encode(hmac.new(_secret(), encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_decode(encoded))
        expires_at = int(payload["exp"])
        if expires_at <= int(time.time()):
            return None
        return Principal(str(payload["sub"]), str(payload["role"]), str(payload["tenant_id"]), expires_at)
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        return None


def principal_from_headers(headers: Mapping[str, str]) -> Optional[Principal]:
    cookie = SimpleCookie()
    cookie.load(headers.get("Cookie", ""))
    morsel = cookie.get(COOKIE_NAME)
    return verify_session(morsel.value) if morsel else None


def session_cookie(token: str, secure: bool) -> str:
    flags = [f"{COOKIE_NAME}={token}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={SESSION_SECONDS}"]
    if secure:
        flags.append("Secure")
    return "; ".join(flags)
