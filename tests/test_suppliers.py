"""P2 Suplidores. Integration tests need METPRO_LEDGER_TEST_DB with migrations/2026-10-23_suppliers*.sql applied."""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
UID = "00000000-0000-0000-0000-000000000001"


def _hdr(role="user"):
    return {"Authorization": "Bearer " + create_access_token({"sub": "t_" + role, "role": role, "user_id": UID})}


def _d(r):
    """Success bodies are wrapped as {"data": ...}."""
    j = r.json()
    return j["data"] if isinstance(j, dict) and "data" in j and "success" in j else j


def test_switch_default_off(monkeypatch):
    from core.supplier_features import suppliers_enabled
    monkeypatch.delenv("SUPPLIERS_ENABLED", raising=False)
    assert suppliers_enabled() is False
    monkeypatch.setenv("SUPPLIERS_ENABLED", "true")
    assert suppliers_enabled() is True


def test_requires_auth():
    assert client.get("/suppliers/options").status_code in (401, 403)
    assert client.get("/suppliers/").status_code in (401, 403)


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    monkeypatch.setattr(importlib.import_module("suppliers.service"), "get_db_connection", connect)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("SUPPLIERS_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM suppliers WHERE NOT is_dummy OR company_name LIKE 'T-%'")
    conn.commit()
    yield conn
    cur = conn.cursor()
    cur.execute("DELETE FROM suppliers WHERE company_name LIKE 'T-%'")
    conn.commit()
    conn.close()


@needs_db
def test_options_and_off_switch(db, monkeypatch):
    assert _d(client.get("/suppliers/options", headers=_hdr()))["suppliers_enabled"] is True
    monkeypatch.setenv("SUPPLIERS_ENABLED", "false")
    assert _d(client.get("/suppliers/options", headers=_hdr()))["suppliers_enabled"] is False
    r = client.get("/suppliers/", headers=_hdr())
    assert r.status_code == 404 and r.json()["code"] == "SUPPLIERS_DISABLED"
    assert client.post("/suppliers/", json={"company_name": "T-x"}, headers=_hdr()).status_code == 404


@needs_db
def test_dummies_seeded_and_flagged(db):
    rows = _d(client.get("/suppliers/", headers=_hdr()))
    dummies = [r for r in rows if r["is_dummy"]]
    assert len(dummies) == 5 and all(r["company_name"].startswith("[PRUEBA]") for r in dummies)


@needs_db
def test_crud_and_validation(db):
    r = client.post("/suppliers/", json={"company_name": "  T-Uno  ", "email": " t1@x.com ", "tax_id": "T-RNC-1",
                                         "phone": "  "}, headers=_hdr())
    assert r.status_code == 200, r.text
    s = _d(r)
    assert s["company_name"] == "T-Uno" and s["email"] == "t1@x.com" and s["phone"] is None and s["is_dummy"] is False
    # duplicates
    d = client.post("/suppliers/", json={"company_name": "T-Dos", "email": "T1@X.com"}, headers=_hdr())
    assert d.status_code == 400 and d.json()["code"] == "SUPPLIER_EMAIL_TAKEN"
    d = client.post("/suppliers/", json={"company_name": "T-Dos", "tax_id": "T-RNC-1"}, headers=_hdr())
    assert d.status_code == 400 and d.json()["code"] == "SUPPLIER_TAX_ID_TAKEN"
    assert client.post("/suppliers/", json={"company_name": "   "}, headers=_hdr()).status_code == 422
    assert client.post("/suppliers/", json={"company_name": "T-Tres", "email": "bad"}, headers=_hdr()).status_code == 400
    # update keeps own email/RNC, can deactivate
    u = client.put(f"/suppliers/{s['id']}", json={"company_name": "T-Uno b", "email": "t1@x.com", "tax_id": "T-RNC-1",
                                                   "is_active": False}, headers=_hdr())
    assert u.status_code == 200 and _d(u)["is_active"] is False and _d(u)["company_name"] == "T-Uno b"
    assert _d(client.get(f"/suppliers/{s['id']}", headers=_hdr()))["company_name"] == "T-Uno b"
    assert client.get("/suppliers/99999999", headers=_hdr()).json()["code"] == "SUPPLIER_NOT_FOUND"
    # delete: admin only
    assert client.delete(f"/suppliers/{s['id']}", headers=_hdr("user")).status_code == 403
    assert client.delete(f"/suppliers/{s['id']}", headers=_hdr("admin")).status_code == 200
    assert client.get(f"/suppliers/{s['id']}", headers=_hdr()).status_code == 404


@needs_db
def test_clients_untouched(db):
    """Suppliers never appear in the clients list."""
    names = [c["company_name"] for c in _d(client.get("/clients/", headers=_hdr()))]
    assert not any(n.startswith("[PRUEBA]") for n in names)
