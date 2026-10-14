"""Item 11: per-user rate limit on all authenticated routes.

Covers: disabled by default, 429 shape and Retry-After, per-user isolation,
window sliding, invalid tokens not counted, 429 raised before the role check,
public routes and /health exempt, success payload unchanged, and the hook
present in require_auth.
"""
import importlib
import inspect
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import rate_limit as rl  # noqa: E402
from main import app  # noqa: E402

SECRET = "test-secret-key"


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    rl._limiter.reset()
    for name in (
        "RATE_LIMIT_AUTH_MAX", "RATE_LIMIT_AUTH_WINDOW",
        "RATE_LIMIT_PUBLIC_MAX", "RATE_LIMIT_PUBLIC_WINDOW",
        "RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW",
    ):
        monkeypatch.delenv(name, raising=False)
    # Skip the DB active-user lookup. These tests cover the limiter only.
    auth_service = importlib.import_module("auth.service")
    monkeypatch.setattr(auth_service, "ENFORCE_ACTIVE_CHECK", False)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    yield
    rl._limiter.reset()


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _token(sub="alice", role="user", exp_offset=600, key=SECRET):
    claims = {
        "sub": sub,
        "role": role,
        "user_id": 1,
        "exp": int(time.time()) + exp_offset,
    }
    return jwt.encode(claims, key, algorithm="HS256")


def _hdr(sub="alice", role="user"):
    return {"Authorization": f"Bearer {_token(sub=sub, role=role)}"}


def _client():
    return TestClient(app, raise_server_exceptions=False)


# ---------- toggle and default ----------

def test_disabled_by_default_never_limits(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    client = _client()
    for _ in range(5):
        assert client.get("/auth/me", headers=_hdr()).status_code == 200


def test_explicitly_disabled_never_limits(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    client = _client()
    for _ in range(5):
        assert client.get("/auth/me", headers=_hdr()).status_code == 200


# ---------- enforcement on protected routes ----------

def test_over_limit_returns_429_with_error_shape(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "2")
    client = _client()
    assert client.get("/auth/me", headers=_hdr()).status_code == 200
    assert client.get("/auth/me", headers=_hdr()).status_code == 200
    resp = client.get("/auth/me", headers=_hdr())
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Too many requests", "code": "RATE_LIMITED"}
    retry = int(resp.headers["Retry-After"])
    assert retry >= 1


def test_limit_is_per_user(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    client = _client()
    assert client.get("/auth/me", headers=_hdr("alice")).status_code == 200
    assert client.get("/auth/me", headers=_hdr("alice")).status_code == 429
    # A different subject has its own bucket.
    assert client.get("/auth/me", headers=_hdr("bob")).status_code == 200


def test_window_slides_and_allows_again(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_AUTH_WINDOW", "60")
    clock = _Clock()
    monkeypatch.setattr(rl, "_limiter", rl.SlidingWindowLimiter(clock=clock))
    client = _client()
    assert client.get("/auth/me", headers=_hdr()).status_code == 200
    assert client.get("/auth/me", headers=_hdr()).status_code == 429
    clock.now += 61
    assert client.get("/auth/me", headers=_hdr()).status_code == 200


def test_invalid_token_does_not_consume_quota(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    client = _client()
    bad = {"Authorization": f"Bearer {_token(key='wrong-key')}"}
    for _ in range(3):
        assert client.get("/auth/me", headers=bad).status_code == 401
    # Quota is still unused, so one valid request passes.
    assert client.get("/auth/me", headers=_hdr()).status_code == 200


def test_admin_route_returns_429_before_role_check(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    client = _client()
    # Non-admin: first call reaches the role check and gets 403, using the slot.
    first = client.get("/auth/admin-only", headers=_hdr(role="user"))
    assert first.status_code == 403
    # Second call is over the limit, so 429 wins over 403.
    second = client.get("/auth/admin-only", headers=_hdr(role="user"))
    assert second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED"


def test_under_limit_success_payload_unchanged(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "5")
    client = _client()
    resp = client.get("/auth/me", headers=_hdr("alice"))
    assert resp.status_code == 200
    assert resp.json() == {
        "data": {"username": "alice", "user_id": 1, "role": "user"},
        "success": True,
    }


# ---------- exemptions ----------

def test_health_is_never_limited(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    client = _client()
    for _ in range(5):
        assert client.get("/health").status_code == 200


def test_public_routes_are_not_counted_against_user_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_MAX", "1000")
    client = _client()
    for _ in range(3):
        resp = client.get("/quotes/public/not-a-real-token")
        assert resp.status_code != 429
        resp = client.get("/invoices/public/not-a-real-token")
        assert resp.status_code != 429
    # The user bucket was never touched by public traffic.
    assert client.get("/auth/me", headers=_hdr()).status_code == 200


def test_login_bucket_does_not_consume_user_quota(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_MAX", "1000")
    client = _client()
    # Login is unauthenticated and uses its own bucket. It must not spend
    # the user's quota, so the first authenticated call still passes.
    for _ in range(3):
        client.post("/auth/login", data={"username": "x", "password": "y"})
    assert client.get("/auth/me", headers=_hdr()).status_code == 200


# ---------- wiring ----------

def test_require_auth_calls_user_limit():
    from auth import service

    src = inspect.getsource(service.require_auth)
    assert "enforce_user_limit(payload[\"sub\"])" in src
    assert src.index("_validate_access_token") < src.index("enforce_user_limit")
