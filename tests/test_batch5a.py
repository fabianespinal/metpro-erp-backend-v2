"""Debug pass batch 5a (backend, Medium/Low): B-10..B-14, B-20..B-23.

Unit tests run everywhere. Integration tests need METPRO_LEDGER_TEST_DB (production schema
plus migrations up to 2026-10-18_payment_void.sql); skipped otherwise.
"""
import importlib
import io
import os
import sys
from datetime import date, timedelta

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core.public_payload import public_payload  # noqa: E402
from main import app  # noqa: E402

irouter = importlib.import_module("invoices.router")
rsvc = importlib.import_module("reports.service")
qsvc = importlib.import_module("quotes.service")
client = TestClient(app)
USER_ID = "00000000-0000-0000-0000-000000000001"


def _hdr(role="user"):
    return {"Authorization": "Bearer " + create_access_token({"sub": f"t_{role}", "role": role, "user_id": USER_ID})}


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)


# ---------------- B-10 invoice send gate ----------------

@pytest.mark.parametrize("row,code", [
    ({"status": "Cancelled", "contact_email": "a@x.com"}, "INVOICE_CANCELLED"),
    ({"status": "Pending", "contact_email": None}, "INVOICE_NO_CONTACT_EMAIL"),
])
def test_invoice_send_refused_before_any_email(monkeypatch, active, row, code):
    sent = []
    monkeypatch.setattr(irouter.service, "get_invoice_with_contact", lambda i: dict(row, id=i))
    monkeypatch.setattr(irouter, "send_invoice_email", lambda **kw: sent.append(kw))
    r = client.post("/invoices/5/send", headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == code
    assert sent == []


# ---------------- B-11 / B-12 reports ----------------

class _Cur:
    def __init__(self):
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchall(self):
        return []


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def close(self):
        pass


def test_client_activity_filters_by_client(monkeypatch):
    cur = _Cur()
    monkeypatch.setattr(rsvc, "get_db_connection", lambda: _Conn(cur))
    out = rsvc.get_client_activity("2026-10-01", "2026-10-31", 7)
    sql, params = cur.sql[0]
    assert "AND c.id = %s" in sql and params[-1] == 7
    assert out["summary"]["filters"]["client_id"] == 7


@pytest.mark.parametrize("path", ["/reports/quotes-summary", "/reports/revenue", "/reports/client-activity"])
def test_reports_reject_bad_dates_with_422(active, path):
    r = client.get(path + "?start_date=abc&end_date=xyz", headers=_hdr())
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    r = client.get(path + "?start_date=2026-10-31&end_date=2026-10-01", headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "DATE_RANGE_INVALID"


# ---------------- B-12 validation ----------------

@pytest.mark.parametrize("body", [{"company_name": "   "}, {"company_name": ""}, {}])
def test_client_requires_company_name(active, body):
    assert client.post("/clients/", json=body, headers=_hdr()).status_code == 422


@pytest.mark.parametrize("body", [
    {"date": "2026-10-18", "category": "Materiales", "amount": -5},
    {"date": "2026-10-18", "category": "Materiales", "amount": 0},
    {"date": "2026-10-18", "category": "", "amount": 10},
])
def test_expense_create_validation(active, body):
    assert client.post("/expenses", json=body, headers=_hdr()).status_code == 422


@pytest.mark.parametrize("body", [{"amount": None}, {"date": None}, {"category": None}, {"amount": -1}])
def test_expense_update_rejects_null_and_negative(active, body):
    assert client.put("/expenses/1", json=body, headers=_hdr()).status_code == 422


# ---------------- B-13 one totals source for quote PDFs ----------------

def test_quote_document_totals_prefers_stored_values():
    items = [{"quantity": 1, "unit_price": 100, "discount_type": "none", "discount_value": 0}]
    charges = {"supervision": True, "supervision_percentage": 10}
    stored = {"subtotal": 110.0, "discount_total": 0, "tax_amount": 19.8, "grand_total": 129.8}
    t = qsvc.quote_document_totals(stored, items, charges)
    assert (t["subtotal_general"], t["itbis"], t["grand_total"], t["supervision"]) == (110.0, 19.8, 129.8, 10.0)
    legacy = qsvc.quote_document_totals({}, items, charges)
    assert round(legacy["grand_total"], 2) == 129.8


def test_internal_quote_pdf_no_longer_defaults_missing_charges_on(monkeypatch):
    """A quote whose stored charges lack the flags prints them OFF, like the email and public PDFs."""
    psvc = importlib.import_module("pdf.service")
    seen = {}

    class Cur:
        def __init__(self):
            self.q = [
                {"quote_id": "q1", "client_id": 1, "contact_id": None, "included_charges": "{}", "created_at": None,
                 "quote_number": 1, "subtotal": None, "discount_total": None, "tax_amount": None, "grand_total": None},
                {"company_name": "C", "address": "", "tax_id": ""},
            ]

        def execute(self, sql, params=None):
            self.last = sql

        def fetchone(self):
            return self.q.pop(0)

        def fetchall(self):
            return [{"quantity": 1, "unit_price": 100, "discount_type": "none", "discount_value": 0, "product_name": "X"}]

    cur = Cur()
    monkeypatch.setattr(psvc, "get_db_connection", lambda: _Conn(cur) if False else type("C", (), {
        "cursor": lambda self, cursor_factory=None: cur, "close": lambda self: None})())
    monkeypatch.setattr(psvc, "build_quote_invoice_pdf", lambda **kw: seen.update(kw) or io.BytesIO(b"%PDF"))
    psvc.generate_quote_pdf("q1", {"sub": "u", "name": "U"})
    assert seen["supervision"] == 0 and round(seen["grand_total"], 2) == 118.0


# ---------------- B-22 public payload ----------------

def test_public_payload_strips_internal_ids():
    doc = {"id": 5, "quote_id": "uuid", "client_id": 1, "contact_id": 2, "created_by_name": "Ana",
           "public_token": "t", "quote_number": 10002, "company_name": "C",
           "items": [{"id": 9, "quote_id": "uuid", "product_id": 3, "product_name": "Viga", "quantity": 1}]}
    out = public_payload(doc)
    assert out == {"quote_number": 10002, "company_name": "C", "items": [{"product_name": "Viga", "quantity": 1}]}
    assert doc["id"] == 5  # input untouched


# ---------------- integration ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import database

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "invoices.router", "pdf.service", "projects.service",
                "reports.service", "clients.service", "products.service", "expenses.router"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    engine = create_engine("postgresql+psycopg2://", creator=lambda: psycopg2.connect(DSN))  # plain rows for SQLAlchemy
    Session = sessionmaker(bind=engine)

    def _get_db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[database.get_db] = _get_db
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "(%s, 't_user', 'x', 't_user@test.local', 'user', true) ON CONFLICT DO NOTHING", (USER_ID,))
    cur.execute("INSERT INTO clients (company_name, tax_id, email) VALUES ('Cliente 5A', '1-31-00001-1', 'c@x.com') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    cur.execute("INSERT INTO quotes (quote_id, client_id, contact_id, status, subtotal, tax_amount, grand_total, total_amount, "
                "included_charges, quote_number, valid_until) VALUES ('q-5a', %s, %s, 'Invoiced', 100, 18, 118, 118, '{}', "
                "10005, %s)", (cid, ctid, date.today() - timedelta(days=30)))
    cur.execute("INSERT INTO quote_items (quote_id, product_name, quantity, unit_price) VALUES ('q-5a', 'Viga', 1, 100)")
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, contact_id, status, total_amount, invoice_date) "
                "VALUES ('F-10005', 'q-5a', %s, %s, 'Pending', 118, '2026-10-17') RETURNING id", (cid, ctid))
    iid = cur.fetchone()["id"]
    cur.execute("INSERT INTO projects (client_id, name, start_date, end_date, estimated_budget) "
                "VALUES (%s, 'P5A', '2026-10-01', '2026-12-01', 5000) RETURNING id", (cid,))
    pid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    yield {"cid": cid, "iid": iid, "pid": pid, "connect": connect}
    app.dependency_overrides.pop(database.get_db, None)


def _one(connect, sql, params=()):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        conn.close()


@needs_db
def test_payment_void_flow(db):
    iid, user, admin = db["iid"], _hdr(), _hdr("admin")
    for amount in (100, 18):
        assert client.post(f"/invoices/{iid}/payments", json={"amount": amount, "method": "Transferencia",
                                                               "payment_date": "2026-10-18"}, headers=user).status_code == 200
    assert _one(db["connect"], "SELECT status FROM invoices WHERE id = %s", (iid,))["status"] == "Paid"
    pays = client.get(f"/invoices/{iid}/payments", headers=user).json()["data"]
    first = pays[0]["id"]

    assert client.post(f"/invoices/{iid}/payments/{first}/void", json={"reason": "Duplicado"}, headers=user).status_code == 403
    assert client.post(f"/invoices/{iid}/payments/{first}/void", json={"reason": ""}, headers=admin).status_code == 400
    r = client.post(f"/invoices/{iid}/payments/{first}/void", json={"reason": "Pago duplicado"}, headers=admin)
    assert r.status_code == 200
    assert r.json()["data"] == {"payment_id": first, "amount_paid": 18.0, "amount_due": 100.0, "status": "Pending"}
    assert client.post(f"/invoices/{iid}/payments/{first}/void", json={"reason": "otra vez"}, headers=admin).json()["code"] == "PAYMENT_ALREADY_VOIDED"
    assert client.post(f"/invoices/{iid}/payments/999/void", json={"reason": "x y z"}, headers=admin).status_code == 404

    # Kept for the record, flagged, and excluded from collected revenue.
    listed = {p["id"]: p for p in client.get(f"/invoices/{iid}/payments", headers=user).json()["data"]}
    assert listed[first]["voided_at"] and listed[first]["void_reason"] == "Pago duplicado"
    rev = client.get("/reports/revenue", headers=user).json()["data"]["summary"]
    assert rev["total_revenue"] == 18.0
    # A new payment sees only non-voided money as paid.
    assert client.post(f"/invoices/{iid}/payments", json={"amount": 100.01, "method": "x", "payment_date": "2026-10-18"},
                       headers=user).json()["code"] == "PAYMENT_EXCEEDS_DUE"


@needs_db
def test_payment_void_toggle_off(db, monkeypatch):
    monkeypatch.setenv("PAYMENT_VOID_ENABLED", "false")
    assert client.post(f"/invoices/{db['iid']}/payments/1/void", json={"reason": "abc"}, headers=_hdr("admin")).status_code == 404


@needs_db
def test_sub_cent_payment_rejected(db):
    r = client.post(f"/invoices/{db['iid']}/payments", json={"amount": 0.004, "method": "x", "payment_date": "2026-10-18"},
                    headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "PAYMENT_AMOUNT_INVALID"


@needs_db
def test_client_create_rules(db):
    user = _hdr()
    assert client.post("/clients/", json={"company_name": "X", "email": "malo"}, headers=user).json()["code"] == "EMAIL_INVALID"
    assert client.post("/clients/", json={"company_name": "X", "tax_id": "1-31-00001-1"}, headers=user).json()["code"] == "CLIENT_TAX_ID_TAKEN"
    assert client.post("/clients/", json={"company_name": "X", "email": "c@x.com"}, headers=user).json()["code"] == "CLIENT_EMAIL_TAKEN"
    r = client.post("/clients/", json={"company_name": "  Nuevo SRL ", "tax_id": "", "email": " "}, headers=user)
    assert r.status_code == 200
    row = _one(db["connect"], "SELECT company_name, tax_id, email FROM clients WHERE id = %s", (r.json()["data"]["id"],))
    assert dict(row) == {"company_name": "Nuevo SRL", "tax_id": None, "email": None}  # B-21


@needs_db
def test_contact_unknown_company_and_blank_name(db):
    r = client.post("/contacts/", json={"company_id": 999999, "name": "X"}, headers=_hdr())
    assert r.status_code == 404 and r.json()["code"] == "CLIENT_NOT_FOUND"
    r = client.post("/contacts/", json={"company_id": db["cid"], "name": "   "}, headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "CONTACT_NAME_REQUIRED"


@needs_db
def test_expense_delete_missing_is_404(db):
    r = client.delete("/expenses/999999", headers=_hdr("admin"))
    assert r.status_code == 404 and r.json()["code"] == "EXPENSE_NOT_FOUND"


@needs_db
def test_project_clear_end_date_and_budget(db):
    pid = db["pid"]
    r = client.put(f"/projects/{pid}", json={"end_date": None, "estimated_budget": None}, headers=_hdr())
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["end_date"] is None and d["estimated_budget"] is None
    r = client.put(f"/projects/{pid}", json={"name": "P5A b"}, headers=_hdr())  # omitted fields stay
    assert r.json()["data"]["name"] == "P5A b"


@needs_db
def test_product_csv_update_counted_and_single_row(db):
    conn = db["connect"]()
    with conn, conn.cursor() as cur:
        cur.execute("INSERT INTO products (name, unit_price) VALUES ('Viga', 90), ('Viga', 91)")
    conn.close()
    r = client.post("/products/import-csv", headers=_hdr(),
                    files={"file": ("p.csv", b"name,unit_price,description\nViga,95,nueva\nCodo,10,x\n")})
    assert r.json()["data"] == {"imported": 1, "updated": 1, "skipped": 0, "total": 2}
    prices = _one(db["connect"], "SELECT array_agg(unit_price::float ORDER BY id) AS p FROM products WHERE name = 'Viga'")["p"]
    assert prices == [95.0, 91.0]


@needs_db
def test_duplicate_clears_past_valid_until(db):
    r = client.post("/quotes/q-5a/duplicate", headers=_hdr())
    assert r.status_code == 200 and r.json()["data"]["valid_until"] is None


@needs_db
def test_public_invoice_payload_and_pdf_name(db):
    token = _one(db["connect"], "SELECT public_token::text AS t FROM invoices WHERE id = %s", (db["iid"],))["t"]
    body = client.get(f"/invoices/public/{token}").json()["data"]
    assert body["invoice_number"] == "F-10005"
    for k in ("id", "quote_id", "client_id", "created_by_name", "public_token"):
        assert k not in body
    r = client.get(f"/invoices/public/{token}/pdf")
    assert r.status_code == 200 and "factura_F-10005.pdf" in r.headers["content-disposition"]
