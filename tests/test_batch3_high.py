"""Debug pass batch 3 (High, backend): B-02 .. B-09.

Unit tests run everywhere. Integration tests need Postgres with the production schema
(METPRO_LEDGER_TEST_DB, same database as test_product_cost.py); skipped otherwise.
"""
import asyncio
import importlib
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core import dates  # noqa: E402
from main import app  # noqa: E402

auth_router = importlib.import_module("auth.router")
csvc = importlib.import_module("clients.service")
psvc = importlib.import_module("products.service")
rsvc = importlib.import_module("reports.service")
qrouter = importlib.import_module("quotes.router")
irouter = importlib.import_module("invoices.router")

client = TestClient(app)


def _hdr(role="user"):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


# ---------------- B-02 passwords ----------------

def test_change_password_and_register_require_minimum_length(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: "admin")
    r = client.post("/auth/change-password", json={"old_password": "x", "new_password": ""}, headers=_hdr())
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    r = client.post("/auth/change-password", json={"old_password": "x", "new_password": "1234567"}, headers=_hdr())
    assert r.status_code == 422
    r = client.post("/auth/register", json={"username": "nuevo", "password": "a", "email": "n@x.com", "full_name": "N"},
                    headers=_hdr("admin"))
    assert r.status_code == 422


# ---------------- B-04 business dates ----------------

def test_business_today_is_santo_domingo_date():
    late_evening_dr = datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc)  # 21:30 on 10-18 in Santo Domingo
    assert dates.business_today(late_evening_dr).isoformat() == "2026-10-18"
    assert dates.business_today(datetime(2026, 10, 19, 4, 0, tzinfo=timezone.utc)).isoformat() == "2026-10-19"


def test_local_date_converts_naive_utc_and_keeps_dates():
    assert dates.local_date(datetime(2026, 10, 19, 1, 30)) == "2026-10-18"
    assert dates.local_date(datetime(2026, 10, 18, 15, 0)) == "2026-10-18"
    assert dates.local_date(datetime(2026, 10, 18).date()) == "2026-10-18"
    assert dates.local_date("2026-10-18T10:00:00") == "2026-10-18"
    assert dates.local_date(None) == ""


def test_business_tz_toggle(monkeypatch):
    monkeypatch.setenv("BUSINESS_TZ", "UTC")
    assert dates.business_today(datetime(2026, 10, 19, 1, 30, tzinfo=timezone.utc)).isoformat() == "2026-10-19"


# ---------------- B-03 report ranges ----------------

class _Cur:
    def __init__(self, ones=None, alls=None):
        self.ones, self.alls, self.sql = list(ones or []), list(alls or []), []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.ones.pop(0)

    def fetchall(self):
        return self.alls.pop(0) if self.alls else []


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_quotes_summary_and_client_activity_use_whole_local_days(monkeypatch):
    cur = _Cur(ones=[{"total": 0}], alls=[[]])
    monkeypatch.setattr(rsvc, "get_db_connection", lambda: _Conn(cur))
    rsvc.get_quotes_summary("2026-10-01", "2026-10-18", None)
    for sql, params in cur.sql:
        assert "AT TIME ZONE 'UTC') AT TIME ZONE %s)::date BETWEEN %s AND %s" in sql
        assert params[:3] == ["America/Santo_Domingo", "2026-10-01", "2026-10-18"]
    cur2 = _Cur(alls=[[]])
    monkeypatch.setattr(rsvc, "get_db_connection", lambda: _Conn(cur2))
    rsvc.get_client_activity("2026-10-01", "2026-10-18")
    sql, params = cur2.sql[0]
    assert "::date BETWEEN %s AND %s" in sql and params == ["America/Santo_Domingo", "2026-10-01", "2026-10-18"]


# ---------------- B-07 client RNC on emailed / public PDFs ----------------

def _quote_row():
    return {"quote_id": "q1", "quote_number": 10002, "company_name": "Cliente", "company_address": "Calle 1",
            "company_tax_id": "1-31-00001-1", "contact_name": "Ana", "contact_email": "a@x.com", "contact_phone": "809",
            "included_charges": {}, "items": [], "project_name": "P", "notes": None, "created_at": datetime(2026, 10, 19, 1, 0),
            "payment_terms": None, "valid_until": None, "status": "Final", "public_token": "t",
            "subtotal": 0, "discount_total": 0, "tax_amount": 0, "grand_total": 0, "created_by_name": "U"}


def test_quote_pdfs_receive_client_rnc_and_local_date(monkeypatch):
    seen = []

    def fake_pdf(**kw):
        import io
        seen.append(kw)
        return io.BytesIO(b"%PDF")

    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setattr(qrouter, "create_quote_pdf", fake_pdf)
    monkeypatch.setattr(qrouter.service, "get_quote_with_contact", lambda q: _quote_row())
    monkeypatch.setattr(qrouter.service, "quote_id_for_public_token", lambda t: "q1")
    monkeypatch.setattr(qrouter.service, "mark_quote_sent", lambda q: "Sent")
    monkeypatch.setattr(qrouter, "send_quote_email", lambda **kw: None)
    assert client.get("/quotes/q1/pdf", headers=_hdr()).status_code == 200
    assert client.get("/quotes/public/0b8a6f1e-1c2d-4e5f-8a9b-0c1d2e3f4a5b/pdf").status_code == 200
    assert client.post("/quotes/q1/send", headers=_hdr()).status_code == 200
    assert [kw["client"]["tax_id"] for kw in seen] == ["1-31-00001-1"] * 3
    assert {kw["doc_date"] for kw in seen} == {"2026-10-18"}  # 01:00 UTC on 10-19 is 21:00 on 10-18 in DR


# ---------------- B-08 CORS on unhandled 500 ----------------

def test_unhandled_error_keeps_cors_headers():
    path = "/__test_boom_b08"

    def _boom():
        raise RuntimeError("boom")

    app.add_api_route(path, _boom, methods=["GET"])
    route = app.router.routes[-1]
    try:
        c = TestClient(app, raise_server_exceptions=False)
        r = c.get(path, headers={"Origin": "https://app.metprord.com"})
    finally:
        app.router.routes.remove(route)  # keep the shared app's route table unchanged for other tests
    assert r.status_code == 500
    assert r.json() == {"detail": "Error interno del servidor", "code": "INTERNAL_ERROR"}
    assert r.headers.get("access-control-allow-origin") == "https://app.metprord.com"
    assert "boom" not in r.text


# ---------------- B-09 short CSV rows ----------------

class _ImportCur(_Cur):
    def __init__(self):
        super().__init__()
        self.inserted = []

    def execute(self, sql, params=None):
        super().execute(sql, params)
        if sql.strip().startswith("INSERT"):
            self.inserted.append(params)

    def fetchone(self):
        return None


def test_client_csv_short_rows_import(monkeypatch):
    cur = _ImportCur()
    monkeypatch.setattr(csvc, "get_db_connection", lambda: _Conn(cur))
    data = "company_name,contact_name,email,phone,address,tax_id,notes\nCorta SRL\nCompleta SRL,Ana,a@b.com,809,Calle,,n\n"
    out = asyncio.run(csvc.import_clients_from_csv(data.encode(), "c.csv", True, {}))
    assert out["summary"]["inserted"] == 2 and out["summary"]["skipped"] == 0
    assert [p[0] for p in cur.inserted] == ["Corta SRL", "Completa SRL"]
    assert cur.inserted[0][1:] == (None, None, None, None, None, None)  # B-21: blanks stored as NULL


def test_product_csv_short_rows_import(monkeypatch):
    cur = _ImportCur()
    monkeypatch.setattr(psvc, "get_db_connection", lambda: _Conn(cur))
    data = "name,unit_price,description\nCorto,10\nSinPrecio\nCompleto,20,desc\n"
    out = asyncio.run(psvc.import_products_from_csv(data.encode(), "p.csv"))
    assert out == {"imported": 2, "updated": 0, "skipped": 1, "total": 3}
    assert [(p[0], p[1], p[2]) for p in cur.inserted] == [("Corto", "", 10.0), ("Completo", "desc", 20.0)]


# ---------------- integration: B-05, B-06 ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "invoices.router", "pdf.service",
                "projects.service", "reports.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "('00000000-0000-0000-0000-000000000001', 't_user', 'x', 't_user@test.local', 'user', true) "
                "ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO clients (company_name, tax_id) VALUES ('Cliente B3', '1-31-00001-1') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    cur.execute("INSERT INTO quotes (quote_id, client_id, contact_id, status, subtotal, tax_amount, grand_total, total_amount, "
                "included_charges, quote_number, tax_type_code, tax_rate, tax_label) VALUES ('q-b3', %s, %s, 'Approved', 100, 18, 118, 118, '{}', 10002, 'itbis_18', 0.18, 'ITBIS (18%%)')",
                (cid, ctid))
    cur.execute("INSERT INTO quote_items (quote_id, product_name, quantity, unit_price) VALUES ('q-b3', 'Viga', 1, 100)")
    cur.execute("INSERT INTO projects (client_id, name, start_date, quote_id, quote_number) "
                "VALUES (%s, 'Nave B3', '2026-10-01', 'q-b3', 10002) RETURNING id", (cid,))
    pid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"pid": pid}


@needs_db
def test_cancel_then_reinvoice_and_delete_with_conduce(db):
    user, admin = _hdr(), _hdr("admin")
    first = client.post("/quotes/q-b3/convert-to-invoice", headers=user).json()["data"]
    assert first["invoice_number"] == "F-10002"
    # B-05: a previewed conduce no longer blocks deleting the invoice
    assert client.get(f"/pdf/invoices/{first['invoice_id']}/conduce", headers=user).status_code == 200
    r = client.delete(f"/invoices/{first['invoice_id']}", headers=admin)
    assert r.status_code == 200 and r.json()["data"]["quote_reverted"] is True

    # B-06: cancel -> quote back to Approved -> re-invoice gets F-10002-2
    second = client.post("/quotes/q-b3/convert-to-invoice", headers=user).json()["data"]
    assert second["invoice_number"] == "F-10002"   # the deleted one freed the number
    assert client.post("/quotes/q-b3/convert-to-invoice", headers=user).status_code == 400  # active invoice exists
    assert client.patch(f"/invoices/{second['invoice_id']}/status", json={"status": "Cancelled"}, headers=admin).status_code == 200
    assert client.get("/quotes/q-b3", headers=user).json()["data"]["status"] == "Approved"
    third = client.post("/quotes/q-b3/convert-to-invoice", headers=user).json()["data"]
    assert third["invoice_number"] == "F-10002-2"
    assert client.get("/quotes/q-b3", headers=user).json()["data"]["status"] == "Invoiced"

    # The project shows one row with the active invoice, not the cancelled one.
    projects = client.get("/projects/", headers=user).json()["data"]
    assert len(projects) == 1 and projects[0]["invoice_number"] == "F-10002-2"

    # Its conduce follows the invoice number.
    r = client.get(f"/pdf/invoices/{third['invoice_id']}/conduce", headers=user)
    assert r.status_code == 200 and "C-10002-2" in r.headers["content-disposition"]

    # Deleting the cancelled invoice must not release the quote (an active invoice remains).
    r = client.delete(f"/invoices/{second['invoice_id']}", headers=admin)
    assert r.status_code == 200 and r.json()["data"]["quote_reverted"] is False
    assert client.get("/quotes/q-b3", headers=user).json()["data"]["status"] == "Invoiced"

    # Revenue pipeline: an Approved quote with only a cancelled invoice counts as "aprobado sin facturar".
    rev = client.get("/reports/revenue", headers=user).json()["data"]["summary"]
    assert rev["pipeline_approved"] == 0.0  # quote is invoiced again
