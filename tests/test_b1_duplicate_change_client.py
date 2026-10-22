"""B1 Duplicate quote + change client. Integration tests need METPRO_LEDGER_TEST_DB (ci schema)."""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
ITEMS = [{"product_name": "Viga", "quantity": 2, "unit_price": 500.0, "discount_type": "none", "discount_value": 0,
          "print_on_pdf": True},
         {"product_name": "Oculta", "quantity": 1, "unit_price": 100.0, "discount_type": "none", "discount_value": 0,
          "print_on_pdf": False}]
NO_CHARGES = {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


def _hdr():
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": "t_user", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})}


def test_switches_default_off(monkeypatch):
    from core import quote_features as f
    monkeypatch.delenv("DUPLICATE_CHANGE_CLIENT_ENABLED", raising=False)
    monkeypatch.delenv("BLANK_QUOTES_ENABLED", raising=False)
    assert f.duplicate_change_client_enabled() is False and f.blank_quotes_enabled() is False
    monkeypatch.setenv("DUPLICATE_CHANGE_CLIENT_ENABLED", "true")
    assert f.duplicate_change_client_enabled() is True


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "projects.service", "tax.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("PRINT_CONTROLS_ENABLED", "true")
    monkeypatch.setenv("DUPLICATE_CHANGE_CLIENT_ENABLED", "true")
    monkeypatch.setenv("BLANK_QUOTES_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "('00000000-0000-0000-0000-000000000001', 't_user', 'x', 't_user@test.local', 'user', true) "
                "ON CONFLICT DO NOTHING")
    ids = {}
    for tag in ("A", "B"):
        cur.execute("INSERT INTO clients (company_name) VALUES (%s) RETURNING id", (f"Cliente {tag}",))
        cid = cur.fetchone()["id"]
        cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, %s, %s) RETURNING id",
                    (cid, f"Contacto {tag}", f"{tag}@x.com"))
        ids[tag] = (cid, cur.fetchone()["id"])
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Segundo A', 'a2@x.com') RETURNING id", (ids["A"][0],))
    ids["A2"] = (ids["A"][0], cur.fetchone()["id"])
    conn.commit()
    conn.close()
    ids["connect"] = connect
    return ids


def _quote(db, tag="A", **over):
    body = {"client_id": db[tag][0], "contact_id": db[tag][1], "project_name": "Obra", "notes": "nota exacta",
            "payment_terms": "30 días", "items": ITEMS, "included_charges": NO_CHARGES}
    body.update(over)
    r = client.post("/quotes/", json=body, headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()["data"]["quote_id"]


def _one(db, sql, params=()):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


@needs_db
def test_plain_duplicate_is_unchanged_and_needs_no_body(db):
    qid = _quote(db)
    r = client.post(f"/quotes/{qid}/duplicate", headers=_hdr())
    assert r.status_code == 200, r.text
    new = _one(db, "SELECT client_id, contact_id FROM quotes WHERE quote_id = %s", (r.json()["data"]["quote_id"],))[0]
    assert (new["client_id"], new["contact_id"]) == db["A"]


@needs_db
def test_change_client_moves_only_the_client_and_contact(db):
    qid = _quote(db)
    r = client.post(f"/quotes/{qid}/duplicate", json={"client_id": db["B"][0], "contact_id": db["B"][1]}, headers=_hdr())
    assert r.status_code == 200, r.text
    nid = r.json()["data"]["quote_id"]
    old = _one(db, "SELECT * FROM quotes WHERE quote_id = %s", (qid,))[0]
    new = _one(db, "SELECT * FROM quotes WHERE quote_id = %s", (nid,))[0]
    assert (new["client_id"], new["contact_id"]) == db["B"] and new["status"] == "Draft" and new["public_token"] is None
    for col in ("project_name", "notes", "payment_terms", "grand_total", "tax_type_code", "tax_rate", "tax_label"):
        assert new[col] == old[col], col
    # The original is untouched.
    assert (old["client_id"], old["contact_id"]) == db["A"] and old["status"] == "Draft"
    items = _one(db, "SELECT product_name, unit_price, print_on_pdf FROM quote_items WHERE quote_id = %s ORDER BY id", (nid,))
    assert [(i["product_name"], float(i["unit_price"]), i["print_on_pdf"]) for i in items] == [("Viga", 500.0, True), ("Oculta", 100.0, False)]


@needs_db
def test_changing_client_requires_a_contact_of_the_new_client(db):
    qid = _quote(db)
    r = client.post(f"/quotes/{qid}/duplicate", json={"client_id": db["B"][0]}, headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "CONTACT_REQUIRED"
    r = client.post(f"/quotes/{qid}/duplicate", json={"client_id": db["B"][0], "contact_id": db["A"][1]}, headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "CONTACT_CLIENT_MISMATCH"
    r = client.post(f"/quotes/{qid}/duplicate", json={"client_id": 99999, "contact_id": db["B"][1]}, headers=_hdr())
    assert r.status_code == 404 and r.json()["code"] == "CLIENT_NOT_FOUND"
    assert _one(db, "SELECT COUNT(*) AS n FROM quotes")[0]["n"] == 1  # nothing was created by the failures


@needs_db
def test_same_client_other_contact(db):
    qid = _quote(db)
    r = client.post(f"/quotes/{qid}/duplicate", json={"contact_id": db["A2"][1]}, headers=_hdr())
    assert r.status_code == 200, r.text
    new = _one(db, "SELECT client_id, contact_id FROM quotes WHERE quote_id = %s", (r.json()["data"]["quote_id"],))[0]
    assert (new["client_id"], new["contact_id"]) == db["A2"]


@needs_db
def test_switch_off_blocks_change_but_not_plain_duplicate(db, monkeypatch):
    qid = _quote(db)
    monkeypatch.setenv("DUPLICATE_CHANGE_CLIENT_ENABLED", "false")
    r = client.post(f"/quotes/{qid}/duplicate", json={"client_id": db["B"][0], "contact_id": db["B"][1]}, headers=_hdr())
    assert r.status_code == 404
    assert client.post(f"/quotes/{qid}/duplicate", headers=_hdr()).status_code == 200
    assert client.post(f"/quotes/{qid}/duplicate", json={}, headers=_hdr()).status_code == 200


@needs_db
def test_invoiced_or_rejected_quotes_can_be_duplicated_for_a_new_client(db):
    qid = _quote(db)
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    client.patch(f"/quotes/{qid}/status", json={"status": "Rejected"}, headers=_hdr())
    r = client.post(f"/quotes/{qid}/duplicate", json={"client_id": db["B"][0], "contact_id": db["B"][1]}, headers=_hdr())
    assert r.status_code == 200 and r.json()["data"]["status"] == "Draft"


@needs_db
def test_options_endpoint(db, monkeypatch):
    assert client.get("/quotes/options", headers=_hdr()).json()["data"] == {
        "blank_quotes_enabled": True, "duplicate_change_client_enabled": True}
    monkeypatch.setenv("BLANK_QUOTES_ENABLED", "false")
    assert client.get("/quotes/options", headers=_hdr()).json()["data"]["blank_quotes_enabled"] is False
    assert client.get("/quotes/options").status_code in (401, 403)
