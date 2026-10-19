"""Debug pass batch 4: X-01 invoiced quotes always have a project; X-02 rejecting a quote cancels it.

Integration tests (need METPRO_LEDGER_TEST_DB, production schema). Skipped otherwise.
"""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
USER_ID = "00000000-0000-0000-0000-000000000001"
BACKFILL = os.path.join(os.path.dirname(__file__), "..", "migrations", "2026-10-18_backfill_quote_projects.sql")


def _hdr(role="user"):
    return {"Authorization": "Bearer " + create_access_token({"sub": f"t_{role}", "role": role, "user_id": USER_ID})}


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "projects.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "(%s, 't_user', 'x', 't_user@test.local', 'user', true) ON CONFLICT DO NOTHING", (USER_ID,))
    cur.execute("INSERT INTO clients (company_name, address) VALUES ('Cliente B4', 'Calle 4') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    for qid, num, status, name in (("q-leg", 10002, "Approved", ""), ("q-inv", 10006, "Invoiced", "Nave"),
                                   ("q-fin", 10007, "Final", "Final")):
        cur.execute("INSERT INTO quotes (quote_id, client_id, contact_id, status, subtotal, tax_amount, grand_total, "
                    "total_amount, included_charges, quote_number, project_name) "
                    "VALUES (%s, %s, %s, %s, 100, 18, 118, 118, '{}', %s, %s)", (qid, cid, ctid, status, num, name))
        cur.execute("INSERT INTO quote_items (quote_id, product_name, quantity, unit_price) VALUES (%s, 'Viga', 1, 100)", (qid,))
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, contact_id, status, total_amount, invoice_date) "
                "VALUES ('F-10006', 'q-inv', %s, %s, 'Pending', 118, '2026-10-17')", (cid, ctid))
    conn.commit()
    conn.close()
    return connect


def _projects(connect):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT quote_id, name, status, start_date::text AS start_date FROM projects ORDER BY quote_id")
        return {r["quote_id"]: dict(r) for r in cur.fetchall()}
    finally:
        conn.close()


@needs_db
def test_backfill_creates_projects_for_approved_and_invoiced_only(db):
    conn = db()
    with conn, conn.cursor() as cur:
        cur.execute(open(BACKFILL, encoding="utf8").read())
    conn.close()
    p = _projects(db)
    assert set(p) == {"q-leg", "q-inv"}                      # Final quote untouched
    assert p["q-leg"]["name"] == "Proyecto Q-10002"          # blank project_name -> label
    assert p["q-inv"]["name"] == "Nave" and p["q-inv"]["start_date"] == "2026-10-17"  # invoice date
    assert all(x["status"] == "pending" for x in p.values())


@needs_db
def test_invoicing_a_legacy_approved_quote_creates_its_project(db):
    r = client.post("/quotes/q-leg/convert-to-invoice", headers=_hdr())
    assert r.status_code == 200
    p = _projects(db)
    assert "q-leg" in p and p["q-leg"]["status"] == "pending"
    # Second conversion path is blocked (active invoice), and no duplicate project appears.
    assert client.post("/quotes/q-leg/convert-to-invoice", headers=_hdr()).status_code == 400
    assert len([k for k in _projects(db) if k == "q-leg"]) == 1


@needs_db
def test_rejecting_an_approved_quote_cancels_its_project(db):
    assert client.patch("/quotes/q-fin/status", json={"status": "Approved"}, headers=_hdr()).status_code == 200
    assert _projects(db)["q-fin"]["status"] == "pending"
    assert client.patch("/quotes/q-fin/status", json={"status": "Rejected"}, headers=_hdr()).status_code == 200
    assert _projects(db)["q-fin"]["status"] == "cancelled"


@needs_db
def test_rejecting_keeps_a_completed_project(db):
    client.patch("/quotes/q-fin/status", json={"status": "Approved"}, headers=_hdr())
    conn = db()
    with conn, conn.cursor() as cur:
        cur.execute("UPDATE projects SET status = 'completed' WHERE quote_id = 'q-fin'")
    conn.close()
    client.patch("/quotes/q-fin/status", json={"status": "Rejected"}, headers=_hdr())
    assert _projects(db)["q-fin"]["status"] == "completed"
