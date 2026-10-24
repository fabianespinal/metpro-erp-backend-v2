"""ROLE_POLICY_ENABLED: approve/reject, convert, direct invoice create and expense edit need admin or superadmin."""
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
UID = "00000000-0000-0000-0000-000000000001"

ACTIONS = [
    ("patch", "/quotes/Q-NOPE/status", {"status": "Approved"}),
    ("patch", "/quotes/Q-NOPE/status", {"status": "Rejected"}),
    ("post", "/quotes/Q-NOPE/convert-to-invoice", None),
    ("post", "/invoices/", {"quote_id": "Q-NOPE"}),
    ("put", "/expenses/999999999", {"description": "x"}),
]


def _hdr(role):
    return {"Authorization": "Bearer " + create_access_token({"sub": "t_" + role, "role": role, "user_id": UID})}


def _call(m, url, body, role):
    return getattr(client, m)(url, headers=_hdr(role), **({"json": body} if body is not None else {}))


@pytest.fixture(autouse=True)
def _active(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)


def test_switch_default_off(monkeypatch):
    from core.role_policy import role_policy_enabled
    monkeypatch.delenv("ROLE_POLICY_ENABLED", raising=False)
    assert role_policy_enabled() is False
    monkeypatch.setenv("ROLE_POLICY_ENABLED", "true")
    assert role_policy_enabled() is True


@pytest.mark.parametrize("m,url,body", ACTIONS)
def test_policy_on_user_gets_403(monkeypatch, m, url, body):
    monkeypatch.setenv("ROLE_POLICY_ENABLED", "true")
    r = _call(m, url, body, "user")
    assert r.status_code == 403 and r.json()["code"] == "INSUFFICIENT_PERMISSIONS"


@needs_db
@pytest.mark.parametrize("role", ["admin", "superadmin"])
@pytest.mark.parametrize("m,url,body", ACTIONS)
def test_policy_on_admin_passes_guard(monkeypatch, m, url, body, role):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import importlib
    for mod in ("quotes.service", "invoices.service", "expenses.router", "projects.service"):
        try:
            monkeypatch.setattr(importlib.import_module(mod), "get_db_connection",
                                lambda: psycopg2.connect(DSN, cursor_factory=RealDictCursor), raising=False)
        except ImportError:
            pass
    monkeypatch.setenv("ROLE_POLICY_ENABLED", "true")
    assert _call(m, url, body, role).status_code != 403


@needs_db
@pytest.mark.parametrize("m,url,body", ACTIONS)
def test_policy_off_user_not_blocked(monkeypatch, m, url, body):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import importlib
    for mod in ("quotes.service", "invoices.service", "expenses.router"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection",
                            lambda: psycopg2.connect(DSN, cursor_factory=RealDictCursor), raising=False)
    monkeypatch.setenv("ROLE_POLICY_ENABLED", "false")
    assert _call(m, url, body, "user").status_code != 403


def test_policy_endpoint_exposes_flag(monkeypatch):
    monkeypatch.setenv("ROLE_POLICY_ENABLED", "true")
    r = client.get("/auth/policy", headers=_hdr("user"))
    body = r.json()
    body = body.get("data", body)
    assert body["role_policy"] is True
