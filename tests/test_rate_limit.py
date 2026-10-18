"""Item 6: rate limits on /auth/login and public quote/invoice token routes.

Business logic is unchanged. Tests cover the limiter, the 429 response,
per-IP isolation, the disable toggle, and that the limited routes still
return their normal result under the limit.
"""
import importlib
import os
import sys
import uuid

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core import rate_limit as rl  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    rl._limiter.reset()
    for name in (
        "RATE_LIMIT_LOGIN_MAX", "RATE_LIMIT_LOGIN_WINDOW",
        "RATE_LIMIT_PUBLIC_MAX", "RATE_LIMIT_PUBLIC_WINDOW",
    ):
        monkeypatch.delenv(name, raising=False)
    # Enforcement tests opt in explicitly. Default is off.
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    yield
    rl._limiter.reset()


# ---------- limiter unit tests ----------

class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_default_is_disabled(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    assert rl.rate_limit_enabled() is False


def test_limiter_allows_up_to_limit_then_blocks():
    clock = _Clock()
    lim = rl.SlidingWindowLimiter(clock=clock)
    assert [lim.hit("k", 3, 60) for _ in range(3)] == [0.0, 0.0, 0.0]
    assert lim.hit("k", 3, 60) > 0


def test_limiter_window_slides():
    clock = _Clock()
    lim = rl.SlidingWindowLimiter(clock=clock)
    for _ in range(2):
        lim.hit("k", 2, 60)
    assert lim.hit("k", 2, 60) > 0
    clock.now += 61
    assert lim.hit("k", 2, 60) == 0.0


def test_limiter_keys_are_independent():
    lim = rl.SlidingWindowLimiter(clock=_Clock())
    lim.hit("a", 1, 60)
    assert lim.hit("a", 1, 60) > 0
    assert lim.hit("b", 1, 60) == 0.0


def test_limiter_fails_closed_when_key_table_full(monkeypatch):
    monkeypatch.setattr(rl, "MAX_TRACKED_KEYS", 2)
    lim = rl.SlidingWindowLimiter(clock=_Clock())
    lim.hit("a", 5, 60)
    lim.hit("b", 5, 60)
    assert lim.hit("c", 5, 60) > 0


def test_client_ip_uses_rightmost_forwarded_entry():
    class _Req:
        headers = {"x-forwarded-for": "6.6.6.6, 203.0.113.9"}
        client = None

    assert rl.client_ip(_Req()) == "203.0.113.9"


def test_client_ip_falls_back_to_socket_peer():
    class _Peer:
        host = "198.51.100.7"

    class _Req:
        headers = {}
        client = _Peer()

    assert rl.client_ip(_Req()) == "198.51.100.7"


# ---------- /auth/login ----------

class _EmptyCursor:
    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return None

    def close(self):
        pass


class _Conn:
    def cursor(self, *a, **k):
        return _EmptyCursor()

    def close(self):
        pass


@pytest.fixture
def login_db(monkeypatch):
    ar = importlib.import_module("auth.router")
    monkeypatch.setattr(ar, "get_db_connection", lambda: _Conn())
    return ar


def _login(client, ip="203.0.113.1"):
    return client.post(
        "/auth/login",
        json={"username": "nobody", "password": "wrong"},
        headers={"X-Forwarded-For": ip},
    )


def test_login_blocks_after_limit_with_retry_after(login_db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LOGIN_MAX", "2")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_WINDOW", "60")
    client = TestClient(app)

    assert _login(client).status_code == 401
    assert _login(client).status_code == 401
    blocked = _login(client)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Demasiadas solicitudes"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_login_limit_is_per_ip(login_db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LOGIN_MAX", "1")
    client = TestClient(app)

    assert _login(client, "203.0.113.1").status_code == 401
    assert _login(client, "203.0.113.1").status_code == 429
    assert _login(client, "203.0.113.2").status_code == 401


def test_login_spoofed_leftmost_forwarded_for_does_not_reset_limit(login_db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_LOGIN_MAX", "1")
    client = TestClient(app)

    assert _login(client, "10.0.0.1, 203.0.113.5").status_code == 401
    # Attacker rotates the leftmost value. Rightmost (edge-set) is unchanged.
    assert _login(client, "10.0.0.2, 203.0.113.5").status_code == 429


def test_login_disabled_by_toggle(login_db, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_LOGIN_MAX", "1")
    client = TestClient(app)

    for _ in range(3):
        assert _login(client).status_code == 401


def test_login_limit_does_not_change_success_body(monkeypatch):
    """Under the limit, login behaves as before: bad password still returns 401 detail."""
    monkeypatch.setenv("RATE_LIMIT_LOGIN_MAX", "5")
    ar = importlib.import_module("auth.router")
    monkeypatch.setattr(ar, "get_db_connection", lambda: _Conn())
    resp = TestClient(app).post(
        "/auth/login",
        json={"username": "nobody", "password": "wrong"},
        headers={"X-Forwarded-For": "203.0.113.50"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Usuario o contraseña incorrectos"


# ---------- public token routes ----------

QUOTE_TOKEN = str(uuid.UUID(int=1, version=4))
INVOICE_TOKEN = str(uuid.UUID(int=2, version=4))
PUBLIC_ROUTES = [
    ("quotes.service", "quote_id_for_public_token", f"/quotes/public/{QUOTE_TOKEN}"),
    ("quotes.service", "quote_id_for_public_token", f"/quotes/public/{QUOTE_TOKEN}/pdf"),
    ("invoices.router", "_invoice_id_for_public_token", f"/invoices/public/{INVOICE_TOKEN}"),
    ("invoices.router", "_invoice_id_for_public_token", f"/invoices/public/{INVOICE_TOKEN}/pdf"),
]


def _stub_public(monkeypatch, module, name):
    mod = importlib.import_module(module)
    calls = []

    def _fake(*a, **k):
        calls.append(1)
        raise HTTPException(status_code=404, detail="Not found")

    monkeypatch.setattr(mod, name, _fake)
    return calls


@pytest.mark.parametrize("module, name, path", PUBLIC_ROUTES)
def test_public_route_blocks_after_limit(monkeypatch, module, name, path):
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_MAX", "2")
    calls = _stub_public(monkeypatch, module, name)
    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.60"}

    assert client.get(path, headers=headers).status_code == 404
    assert client.get(path, headers=headers).status_code == 404
    blocked = client.get(path, headers=headers)
    assert blocked.status_code == 429
    assert "Retry-After" in blocked.headers
    # Blocked request never reached the handler.
    assert len(calls) == 2


def test_public_limit_shared_across_public_routes_for_one_ip(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_MAX", "1")
    _stub_public(monkeypatch, "quotes.service", "quote_id_for_public_token")
    _stub_public(monkeypatch, "invoices.router", "_invoice_id_for_public_token")
    client = TestClient(app)
    headers = {"X-Forwarded-For": "203.0.113.70"}

    assert client.get(f"/quotes/public/{QUOTE_TOKEN}", headers=headers).status_code == 404
    assert client.get(f"/invoices/public/{INVOICE_TOKEN}", headers=headers).status_code == 429


def test_public_route_success_body_unchanged_under_limit(monkeypatch):
    qs = importlib.import_module("quotes.service")
    monkeypatch.setattr(qs, "quote_id_for_public_token", lambda token: 7)
    monkeypatch.setattr(
        qs, "get_quote_with_contact",
        lambda qid: {"quote_id": "Q-7", "public_token": "x", "company_name": "Acme"},
    )
    resp = TestClient(app).get(
        f"/quotes/public/{QUOTE_TOKEN}", headers={"X-Forwarded-For": "203.0.113.80"}
    )
    assert resp.status_code == 200
    assert resp.json() == {"data": {"quote_id": "Q-7", "company_name": "Acme"}, "success": True}


def test_public_limit_disabled_by_toggle(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PUBLIC_MAX", "1")
    _stub_public(monkeypatch, "quotes.service", "quote_id_for_public_token")
    client = TestClient(app)
    for _ in range(3):
        assert client.get(f"/quotes/public/{QUOTE_TOKEN}").status_code == 404
