"""Item 12, module 3: request log middleware.

Covers: which requests are logged, route templates (never raw public tokens),
user_sub and flags, status codes, excluded paths, the auth-failure gap, the
429 case, client IP, no body fields, holder isolation between requests, and
that a failing DB write does not change the response.
"""
import importlib
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database  # noqa: E402
from core import rate_limit as rl  # noqa: E402
from core import request_log as rlog  # noqa: E402
from main import app  # noqa: E402

SECRET = "test-secret-key"
RAW_TOKEN = "RAW-PUBLIC-TOKEN-ABC123"
REAL_LOG_REQUEST = rlog.log_request  # captured before the fixture patches it


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    rl._limiter.reset()
    for name in ("RATE_LIMIT_AUTH_MAX", "RATE_LIMIT_AUTH_WINDOW",
                 "RATE_LIMIT_PUBLIC_MAX", "RATE_LIMIT_PUBLIC_WINDOW",
                 "RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    auth_service = importlib.import_module("auth.service")
    monkeypatch.setattr(auth_service, "ENFORCE_ACTIVE_CHECK", False)

    calls = []

    def fake_log_request(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(rlog, "log_request", fake_log_request)
    yield calls
    rl._limiter.reset()


def _hdr(sub="alice", role="user", key=SECRET):
    tok = jwt.encode({"sub": sub, "role": role, "user_id": 1,
                      "exp": int(time.time()) + 600}, key, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _client():
    return TestClient(app, raise_server_exceptions=False)


def _wait_for(calls, n=1, timeout=2.0):
    # The write runs in a worker thread after the response, so poll briefly.
    end = time.time() + timeout
    while len(calls) < n and time.time() < end:
        time.sleep(0.01)
    return calls


# ---------- logged ----------

def test_authenticated_request_is_logged(_isolate):
    calls = _isolate
    resp = _client().get("/auth/me", headers=_hdr("alice"))
    assert resp.status_code == 200
    _wait_for(calls)
    assert len(calls) == 1
    c = calls[0]
    assert c["method"] == "GET"
    assert c["path"] == "/auth/me"
    assert c["status_code"] == 200
    assert c["user_sub"] == "alice"
    assert c["is_authenticated"] is True
    assert c["is_public"] is False
    assert isinstance(c["latency_ms"], int) and c["latency_ms"] >= 0


def test_authenticated_403_is_logged_with_status(_isolate):
    calls = _isolate
    resp = _client().get("/auth/admin-only", headers=_hdr("bob", role="user"))
    assert resp.status_code == 403
    _wait_for(calls)
    assert calls[0]["status_code"] == 403
    assert calls[0]["user_sub"] == "bob"


def test_rate_limited_authenticated_request_is_logged_as_429(_isolate, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_AUTH_MAX", "1")
    calls = _isolate
    client = _client()
    client.get("/auth/me", headers=_hdr("carol"))
    resp = client.get("/auth/me", headers=_hdr("carol"))
    assert resp.status_code == 429
    _wait_for(calls, n=2)
    assert [c["status_code"] for c in calls] == [200, 429]
    assert calls[1]["user_sub"] == "carol"


def test_public_quote_view_logged_with_template_not_raw_token(_isolate):
    calls = _isolate
    _client().get(f"/quotes/public/{RAW_TOKEN}")
    _wait_for(calls)
    assert len(calls) == 1
    c = calls[0]
    assert c["path"] == "/quotes/public/{token}"
    assert RAW_TOKEN not in c["path"]
    assert c["is_public"] is True
    assert c["is_authenticated"] is False
    assert c["user_sub"] is None


def test_public_invoice_pdf_logged_with_template(_isolate):
    calls = _isolate
    _client().get(f"/invoices/public/{RAW_TOKEN}/pdf")
    _wait_for(calls)
    assert calls[0]["path"] == "/invoices/public/{token}/pdf"
    assert calls[0]["is_public"] is True
    assert RAW_TOKEN not in calls[0]["path"]


def test_client_ip_comes_from_rightmost_forwarded_entry(_isolate):
    calls = _isolate
    _client().get("/auth/me", headers={**_hdr(), "X-Forwarded-For": "10.0.0.1, 198.51.100.9"})
    _wait_for(calls)
    assert calls[0]["client_ip"] == "198.51.100.9"


# ---------- not logged ----------

def test_health_is_not_logged(_isolate):
    calls = _isolate
    _client().get("/health")
    time.sleep(0.05)
    assert calls == []


def test_login_is_not_logged(_isolate):
    calls = _isolate
    _client().post("/auth/login", data={"username": "x", "password": "y"})
    time.sleep(0.05)
    assert calls == []


def test_unauthenticated_401_is_not_logged(_isolate):
    calls = _isolate
    resp = _client().get("/auth/me")
    assert resp.status_code == 401
    time.sleep(0.05)
    assert calls == []


def test_invalid_token_401_is_not_logged(_isolate):
    calls = _isolate
    resp = _client().get("/auth/me", headers=_hdr(key="wrong-key"))
    assert resp.status_code == 401
    time.sleep(0.05)
    assert calls == []


def test_unmatched_path_is_not_logged(_isolate):
    calls = _isolate
    _client().get("/does-not-exist", headers=_hdr())
    time.sleep(0.05)
    assert calls == []


# ---------- isolation and shape ----------

def test_user_sub_does_not_leak_into_following_public_request(_isolate):
    calls = _isolate
    client = _client()
    client.get("/auth/me", headers=_hdr("alice"))
    client.get(f"/quotes/public/{RAW_TOKEN}")
    _wait_for(calls, n=2)
    assert calls[0]["user_sub"] == "alice"
    assert calls[1]["user_sub"] is None
    assert calls[1]["is_authenticated"] is False


def test_log_kwargs_have_no_body_or_header_fields(_isolate):
    calls = _isolate
    _client().request("GET", "/auth/me", headers=_hdr(),
                      content=b'{"secret": "do-not-store"}')
    _wait_for(calls)
    allowed = {"method", "path", "status_code", "latency_ms", "client_ip",
               "user_sub", "is_public", "is_authenticated"}
    assert set(calls[0].keys()) <= allowed
    assert "do-not-store" not in repr(calls[0])


def test_db_failure_does_not_change_response(monkeypatch, capsys):
    # Use the real writer and make the DB unavailable.
    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(database, "get_db_connection", boom)
    monkeypatch.setattr(rlog, "log_request", REAL_LOG_REQUEST)
    resp = _client().get("/auth/me", headers=_hdr("dave"))
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "dave"
    time.sleep(0.1)
    assert "request_log: write failed: ConnectionError" in capsys.readouterr().err


def test_record_error_is_reported_without_payload_and_response_unchanged(monkeypatch, capsys):
    from core import request_log_middleware as rlm

    def broken_template(app, scope):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(rlm, "_route_template", broken_template)
    resp = _client().get("/auth/me", headers=_hdr("erin"))
    assert resp.status_code == 200
    assert resp.json()["data"]["username"] == "erin"
    err = capsys.readouterr().err
    assert "request_log: record failed: RuntimeError" in err
    assert "secret-internal-detail" not in err
