"""Status history S1: every quote and invoice status change is recorded with user and time.

Unit tests run everywhere. Integration tests need Postgres with the production schema plus
2026-10-23_status_history (METPRO_LEDGER_TEST_DB); skipped otherwise.
"""
import importlib
import os
import sys
from datetime import date

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core import status_history  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
ANA = "00000000-0000-0000-0000-000000000001"
BOSS = "00000000-0000-0000-0000-000000000002"
NO_CHARGES = {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}
LINE = {"product_name": "Viga W10", "quantity": 2, "unit_price": 500.0, "discount_type": "none", "discount_value": 0}


def _d(r):
    j = r.json()
    return j["data"] if isinstance(j, dict) and "data" in j else j


def _hdr(role="user", uid=ANA, name="t_user"):
    return {"Authorization": "Bearer " + create_access_token({"sub": name, "role": role, "user_id": uid})}


# ---------------- unit: switch and SQL discipline ----------------

class _Cur:
    def __init__(self, fail=False):
        self.sql, self.fail = [], fail

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        if self.fail and "INSERT INTO status_history" in sql:
            raise RuntimeError("boom")


def test_switch_defaults_off(monkeypatch):
    monkeypatch.delenv("STATUS_HISTORY_ENABLED", raising=False)
    assert status_history.enabled() is False
    monkeypatch.setenv("STATUS_HISTORY_ENABLED", "true")
    assert status_history.enabled() is True


def test_off_runs_no_sql(monkeypatch):
    monkeypatch.delenv("STATUS_HISTORY_ENABLED", raising=False)
    cur = _Cur()
    assert status_history.record(cur, "quote", "Q1", None, "Draft", ANA) is False
    assert status_history.fetch(cur, "quote", "Q1") == []
    rows = [{"quote_id": "Q1"}]
    assert status_history.attach_last(cur, "quote", rows, "quote_id") == [
        {"quote_id": "Q1", "last_status_by": None, "last_status_at": None}]
    assert cur.sql == []


def test_same_status_is_not_recorded(monkeypatch):
    monkeypatch.setenv("STATUS_HISTORY_ENABLED", "true")
    cur = _Cur()
    assert status_history.record(cur, "invoice", 5, "Paid", "Paid", ANA) is False
    assert cur.sql == []


def test_failed_write_is_isolated_by_savepoint(monkeypatch):
    monkeypatch.setenv("STATUS_HISTORY_ENABLED", "true")
    cur = _Cur(fail=True)
    assert status_history.record(cur, "quote", "Q1", "Draft", "Final", ANA) is False
    assert cur.sql[0].startswith("SAVEPOINT") and cur.sql[-1].startswith("ROLLBACK TO SAVEPOINT")


def test_migration_is_additive_and_rollback_refuses_with_rows():
    up = open(os.path.join(ROOT, "migrations", "2026-10-23_status_history.sql"), encoding="utf-8").read().upper()
    down = open(os.path.join(ROOT, "migrations", "2026-10-23_status_history.rollback.sql"), encoding="utf-8").read().upper()
    assert "CREATE TABLE IF NOT EXISTS PUBLIC.STATUS_HISTORY" in up and "ENABLE ROW LEVEL SECURITY" in up
    assert "BEFORE UPDATE OR DELETE" in up
    for word in ("ALTER TABLE PUBLIC.QUOTES", "ALTER TABLE PUBLIC.INVOICES", "DROP TABLE", "TRUNCATE", "DELETE FROM"):
        assert word not in up
    assert "RAISE EXCEPTION" in down and "DROP TABLE IF EXISTS PUBLIC.STATUS_HISTORY" in down


# ---------------- integration ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "invoices.router", "pdf.service", "products.service",
                "projects.service", "reports.service", "tax.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("STATUS_HISTORY_ENABLED", "true")
    monkeypatch.setenv("PAYMENT_VOID_ENABLED", "true")
    monkeypatch.setenv("PAYMENT_CORRECTION_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("ALTER TABLE status_history DISABLE TRIGGER status_history_append_only")
    cur.execute("TRUNCATE status_history, conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, "
                "projects, quotes, template_pack_items, template_pack_categories, template_packs, products, contacts, "
                "clients RESTART IDENTITY CASCADE")
    cur.execute("ALTER TABLE status_history ENABLE TRIGGER status_history_append_only")
    cur.execute("INSERT INTO users (id, username, full_name, password_hash, email, role, is_active) VALUES "
                "(%s, 't_user', 'Ana Perez', 'x', 't_user@test.local', 'user', true), "
                "(%s, 't_boss', 'Boss Admin', 'x', 't_boss@test.local', 'admin', true) "
                "ON CONFLICT (id) DO UPDATE SET full_name = EXCLUDED.full_name", (ANA, BOSS))
    cur.execute("INSERT INTO clients (company_name, tax_id) VALUES ('Cliente S1', '1-31-00001-1') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"cid": cid, "ctid": ctid, "connect": connect}


def _rows(db, sql, params=()):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def _hist(db, etype, key):
    rows = _rows(db, "SELECT from_status, to_status, actor_user_id::text AS uid, actor_name, note FROM status_history "
                     "WHERE entity_type = %s AND entity_key = %s ORDER BY id", (etype, str(key)))
    return [(r["from_status"], r["to_status"], r["uid"], r["actor_name"]) for r in rows]


def _quote(db, **over):
    body = {"client_id": db["cid"], "contact_id": db["ctid"], "project_name": "S1", "items": [LINE],
            "included_charges": NO_CHARGES}
    body.update(over)
    r = client.post("/quotes/", json=body, headers=_hdr())
    assert r.status_code == 200, r.text
    return _d(r)["quote_id"]


def _approved(db):
    qid = _quote(db)
    assert client.post(f"/quotes/{qid}/finalize", headers=_hdr()).status_code == 200
    assert client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr("admin", BOSS)).status_code == 200
    return qid


@needs_db
def test_quote_lifecycle_records_every_change(db):
    from quotes import service
    qid = _quote(db)
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    service.mark_quote_sent(qid, BOSS)
    client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr("admin", BOSS))
    r = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr())
    assert r.status_code == 200, r.text
    iid = _d(r)["invoice_id"]
    assert _hist(db, "quote", qid) == [
        (None, "Draft", ANA, "Ana Perez"), ("Draft", "Final", ANA, "Ana Perez"), ("Final", "Sent", BOSS, "Boss Admin"),
        ("Sent", "Approved", BOSS, "Boss Admin"), ("Approved", "Invoiced", ANA, "Ana Perez")]
    assert _hist(db, "invoice", iid) == [(None, "Pending", ANA, "Ana Perez")]


@needs_db
def test_sent_is_recorded_only_when_it_changed(db):
    from quotes import service
    qid = _approved(db)
    before = len(_hist(db, "quote", qid))
    service.mark_quote_sent(qid, ANA)  # Approved keeps its status
    assert len(_hist(db, "quote", qid)) == before


@needs_db
def test_rejected_and_delete(db):
    qid = _quote(db)
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    assert client.patch(f"/quotes/{qid}/status", json={"status": "Rejected"}, headers=_hdr("admin", BOSS)).status_code == 200
    assert client.delete(f"/quotes/{qid}", headers=_hdr("admin", BOSS)).status_code == 200
    assert _hist(db, "quote", qid)[-2:] == [("Final", "Rejected", BOSS, "Boss Admin"), ("Rejected", "Deleted", BOSS, "Boss Admin")]


@needs_db
def test_duplicate_starts_a_history(db):
    qid = _quote(db)
    r = client.post(f"/quotes/{qid}/duplicate", headers=_hdr())
    assert r.status_code == 200, r.text
    assert _hist(db, "quote", _d(r)["quote_id"]) == [(None, "Draft", ANA, "Ana Perez")]


@needs_db
def test_payments_void_correct_move_the_invoice_status(db):
    qid = _approved(db)
    iid = _d(client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()))["invoice_id"]
    total = float(_rows(db, "SELECT total_amount FROM invoices WHERE id = %s", (iid,))[0]["total_amount"])
    pay = {"amount": total, "method": "Transferencia", "payment_date": date.today().isoformat()}
    pid = _d(client.post(f"/invoices/{iid}/payments", json=pay, headers=_hdr()))["payment_id"]
    r = client.post(f"/invoices/{iid}/payments/{pid}/void", json={"reason": "error de monto"}, headers=_hdr("admin", BOSS))
    assert r.status_code == 200, r.text
    pid2 = _d(client.post(f"/invoices/{iid}/payments", json=pay, headers=_hdr()))["payment_id"]
    pay_half = dict(pay, amount=total / 2)
    r = client.post(f"/invoices/{iid}/payments/{pid2}/correct", json=dict(pay_half, reason="monto mal"), headers=_hdr("admin", BOSS))
    assert r.status_code == 200, r.text
    assert _hist(db, "invoice", iid) == [
        (None, "Pending", ANA, "Ana Perez"), ("Pending", "Paid", ANA, "Ana Perez"), ("Paid", "Pending", BOSS, "Boss Admin"),
        ("Pending", "Paid", ANA, "Ana Perez"), ("Paid", "Pending", BOSS, "Boss Admin")]


@needs_db
def test_cancel_invoice_releases_quote_and_both_are_recorded(db):
    qid = _approved(db)
    iid = _d(client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()))["invoice_id"]
    r = client.patch(f"/invoices/{iid}/status", json={"status": "Cancelled"}, headers=_hdr("admin", BOSS))
    assert r.status_code == 200, r.text
    assert _hist(db, "invoice", iid)[-1] == ("Pending", "Cancelled", BOSS, "Boss Admin")
    assert _hist(db, "quote", qid)[-1] == ("Invoiced", "Approved", BOSS, "Boss Admin")


@needs_db
def test_delete_invoice_records_deleted_and_release(db):
    qid = _approved(db)
    iid = _d(client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()))["invoice_id"]
    assert client.delete(f"/invoices/{iid}", headers=_hdr("admin", BOSS)).status_code == 200
    assert _hist(db, "invoice", iid)[-1] == ("Pending", "Deleted", BOSS, "Boss Admin")
    assert _hist(db, "quote", qid)[-1] == ("Invoiced", "Approved", BOSS, "Boss Admin")


@needs_db
def test_history_endpoints_and_list_fields(db):
    qid = _approved(db)
    iid = _d(client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()))["invoice_id"]
    r = client.get(f"/quotes/{qid}/status-history", headers=_hdr())
    body = _d(r)
    assert r.status_code == 200 and body["enabled"] is True and body["current_status"] == "Invoiced"
    assert [e["to_status"] for e in body["entries"]][:2] == ["Invoiced", "Approved"]  # newest first
    assert body["entries"][0]["actor_name"] == "Ana Perez" and body["entries"][0]["changed_at"]
    r = client.get(f"/invoices/{iid}/status-history", headers=_hdr())
    assert r.status_code == 200 and _d(r)["entries"][0]["to_status"] == "Pending"
    quotes_list = _d(client.get("/quotes/", headers=_hdr()))
    row = next(q for q in (quotes_list["data"] if isinstance(quotes_list, dict) else quotes_list) if q["quote_id"] == qid)
    assert row["last_status_by"] == "Ana Perez" and row["last_status_at"]
    inv_list = _d(client.get("/invoices/", headers=_hdr()))
    irow = next(i for i in (inv_list["data"] if isinstance(inv_list, dict) else inv_list) if i["id"] == iid)
    assert irow["last_status_by"] == "Ana Perez"
    assert client.get("/quotes/NOPE/status-history", headers=_hdr()).status_code == 404
    assert client.get("/invoices/999999/status-history", headers=_hdr()).status_code == 404


@needs_db
def test_switch_off_writes_nothing_and_flows_still_work(db, monkeypatch):
    monkeypatch.setenv("STATUS_HISTORY_ENABLED", "false")
    qid = _approved(db)
    assert client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()).status_code == 200
    assert _rows(db, "SELECT count(*) AS n FROM status_history")[0]["n"] == 0
    body = _d(client.get(f"/quotes/{qid}/status-history", headers=_hdr()))
    assert body["enabled"] is False and body["entries"] == []


@needs_db
def test_history_is_append_only(db):
    _quote(db)
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception):
            cur.execute("UPDATE status_history SET to_status = 'X'")
        conn.rollback()
        with pytest.raises(Exception):
            cur.execute("DELETE FROM status_history")
    finally:
        conn.rollback()
        conn.close()
