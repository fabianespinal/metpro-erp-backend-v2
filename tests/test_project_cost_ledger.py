"""Project Cost Ledger (2026-10-18): expenses linked to projects, project totals, reports.

Unit tests run everywhere. The integration tests at the bottom need a real Postgres with the
production schema plus migrations/2026-10-18_expenses_project_fk.sql; set
METPRO_LEDGER_TEST_DB to its DSN to run them (skipped otherwise).
"""
import os
import sys
from datetime import date

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order: avoids a circular import via pdf)
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from expenses.models import ExpenseCreate, ExpenseUpdate  # noqa: E402
from main import app  # noqa: E402
from projects.ledger import categories_from_rows, expense_date_filter  # noqa: E402

client = TestClient(app)


def _hdr(role="user"):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda username: None)


# ---------------- models ----------------

def test_expense_project_id_is_optional_int():
    base = {"date": "2026-10-18", "category": "Materiales", "amount": 10}
    assert ExpenseCreate(**base).project_id is None
    assert ExpenseCreate(**base, project_id=7).project_id == 7
    assert ExpenseCreate(**base, project_id="7").project_id == 7
    assert ExpenseCreate(**base, project_id="").project_id is None
    assert ExpenseCreate(**base, project_id="  ").project_id is None
    with pytest.raises(ValidationError):
        ExpenseCreate(**base, project_id="Nave Santiago")


def test_expense_update_explicit_null_unlinks():
    u = ExpenseUpdate(project_id=None)
    assert u.dict(exclude_unset=True) == {"project_id": None}
    assert ExpenseUpdate().dict(exclude_unset=True) == {}


# ---------------- helpers ----------------

def test_categories_sorted_with_percentages():
    rows = [{"category": "Combustible", "total": 25, "n": 1}, {"category": "Materiales", "total": 75, "n": 3},
            {"category": None, "total": 0, "n": 1}]
    out = categories_from_rows(rows, 100.0)
    assert [c["category"] for c in out] == ["Materiales", "Combustible", "Sin categoría"]
    assert out[0] == {"category": "Materiales", "total": 75.0, "count": 3, "percentage": 75.0}
    assert categories_from_rows(rows, 0.0)[0]["percentage"] == 0.0


def test_date_filter_bounds_are_optional():
    p = []
    assert expense_date_filter("e.date", None, None, p) == "" and p == []
    p = []
    sql = expense_date_filter("e.date", date(2026, 1, 1), date(2026, 1, 31), p)
    assert ">=" in sql and "<=" in sql and p == [date(2026, 1, 1), date(2026, 1, 31)]


# ---------------- routes ----------------

def test_new_routes_require_auth():
    for path in ("/projects/1/expenses", "/reports/project-profitability", "/reports/expenses-by-category"):
        assert client.get(path).status_code == 401, path


def test_reversed_dates_rejected(active):
    for path in ("/projects/1/expenses", "/reports/project-profitability", "/reports/expenses-by-category"):
        r = client.get(path + "?start_date=2026-02-01&end_date=2026-01-01", headers=_hdr())
        assert r.status_code == 400, (path, r.text)
        assert r.json()["code"] == "DATE_RANGE_INVALID"


def test_bad_date_is_spanish_422(active):
    r = client.get("/reports/project-profitability?start_date=ayer", headers=_hdr())
    assert r.status_code == 422 and "Solicitud no válida" in r.json()["detail"]


def test_project_expenses_route_calls_ledger(active, monkeypatch):
    seen = {}

    def fake(pid, s, e):
        seen.update(pid=pid, s=s, e=e)
        return {"project_id": pid, "expenses": [], "totals": {"total_expenses": 0, "count": 0, "expenses_by_category": []}}

    monkeypatch.setattr("projects.ledger.get_project_expenses", fake)
    r = client.get("/projects/5/expenses?start_date=2026-10-01", headers=_hdr())
    assert r.status_code == 200
    assert seen == {"pid": 5, "s": date(2026, 10, 1), "e": None}
    assert r.json()["data"]["totals"]["total_expenses"] == 0


# ---------------- integration (real Postgres) ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "expenses.router", "projects.ledger", "projects.service", "reports.service"):
        monkeypatch.setattr(f"{mod}.get_db_connection", connect, raising=False)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "contacts, clients RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO clients (company_name) VALUES ('Cliente Ledger') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO quotes (quote_id, client_id, status, total_amount, grand_total) "
                "VALUES ('q-ledger', %s, 'Invoiced', 1180, 1180)", (cid,))
    cur.execute("INSERT INTO projects (client_id, name, start_date, quote_id) VALUES (%s, 'Nave A', '2026-10-01', 'q-ledger') "
                "RETURNING id", (cid,))
    pid = cur.fetchone()["id"]
    cur.execute("INSERT INTO projects (client_id, name, start_date) VALUES (%s, 'Sin factura', '2026-10-01') RETURNING id", (cid,))
    pid2 = cur.fetchone()["id"]
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, status, total_amount, itbis_total, invoice_date) "
                "VALUES ('F-1', 'q-ledger', %s, 'Pending', 1180, 180, '2026-10-05') RETURNING id", (cid,))
    iid = cur.fetchone()["id"]
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, status, total_amount, invoice_date) "
                "VALUES ('F-X', 'q-ledger', %s, 'Cancelled', 999, '2026-10-05')", (cid,))
    cur.execute("INSERT INTO invoice_payments (invoice_id, amount, payment_date, method) VALUES (%s, 500, '2026-10-06', 'Cheque')", (iid,))
    conn.commit()
    conn.close()
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda username: None)
    return {"pid": pid, "pid2": pid2, "cid": cid}


def _post_expense(**kw):
    body = {"date": "2026-10-10", "category": "Materiales", "amount": 100, **kw}
    return client.post("/expenses/", json=body, headers=_hdr())


@needs_db
def test_linked_expense_flow(db):
    pid = db["pid"]
    assert _post_expense(project_id=pid, amount=200).status_code == 200
    assert _post_expense(project_id=str(pid), category="Combustible", amount=50, date="2026-09-01").status_code == 200
    assert _post_expense(amount=30).status_code == 200  # unassigned
    r = _post_expense(project_id=99999)
    assert r.status_code == 404 and r.json()["code"] == "PROJECT_NOT_FOUND"

    rows = client.get("/expenses/", headers=_hdr()).json()["data"]
    linked = [e for e in rows if e["project_id"] == pid]
    assert len(linked) == 2 and all(e["project_name"] == "Nave A" and e["project_number"].startswith("P-") for e in linked)

    led = client.get(f"/projects/{pid}/expenses", headers=_hdr()).json()["data"]
    assert led["totals"]["total_expenses"] == 250.0 and led["totals"]["count"] == 2
    assert [c["category"] for c in led["totals"]["expenses_by_category"]] == ["Materiales", "Combustible"]
    led = client.get(f"/projects/{pid}/expenses?start_date=2026-10-01", headers=_hdr()).json()["data"]
    assert led["totals"]["total_expenses"] == 200.0
    assert client.get("/projects/99999/expenses", headers=_hdr()).status_code == 404


@needs_db
def test_update_link_unlink_and_validation(db):
    pid = db["pid"]
    eid = _post_expense().json()["data"]["expense_id"]
    assert client.put(f"/expenses/{eid}", json={"project_id": pid}, headers=_hdr()).status_code == 200
    assert client.get(f"/expenses/{eid}", headers=_hdr()).json()["data"]["project_id"] == pid
    r = client.put(f"/expenses/{eid}", json={"project_id": 4242}, headers=_hdr())
    assert r.status_code == 404 and r.json()["code"] == "PROJECT_NOT_FOUND"
    assert client.put(f"/expenses/{eid}", json={"project_id": None}, headers=_hdr()).status_code == 200
    assert client.get(f"/expenses/{eid}", headers=_hdr()).json()["data"]["project_id"] is None
    assert client.put("/expenses/77777", json={"amount": 1}, headers=_hdr()).status_code == 404


@needs_db
def test_project_with_expenses_cannot_be_deleted(db):
    pid = db["pid"]
    _post_expense(project_id=pid)
    r = client.delete(f"/projects/{pid}", headers=_hdr("admin"))
    assert r.status_code == 400 and r.json()["code"] == "PROJECT_HAS_EXPENSES"
    assert client.delete(f"/projects/{db['pid2']}", headers=_hdr("admin")).status_code == 200


@needs_db
def test_profitability_report(db):
    pid = db["pid"]
    _post_expense(project_id=pid, amount=300)
    _post_expense(project_id=pid, category="Combustible", amount=80)
    data = client.get("/reports/project-profitability", headers=_hdr()).json()["data"]
    p = [x for x in data["projects"] if x["project_id"] == pid][0]
    assert p["billed"] == 1180.0          # cancelled invoice excluded
    assert p["billed_itbis"] == 180.0
    assert p["billed_net"] == 1000.0      # Facturado (sin ITBIS)
    assert p["paid"] == 500.0 and p["outstanding"] == 680.0
    assert p["paid_net"] == round(500 * 1000 / 1180, 2)   # Cobrado (sin ITBIS), proportional
    # Margins exclude ITBIS (approved 2026-10-18)
    assert p["expenses"] == 380.0 and p["net_margin"] == 620.0
    assert p["margin_pct"] == 62.0
    assert p["cash_margin"] == round(500 * 1000 / 1180 - 380, 2)
    assert p["invoices_without_itbis"] == 0
    assert [c["category"] for c in p["expense_categories"]] == ["Materiales", "Combustible"]
    other = [x for x in data["projects"] if x["project_id"] == db["pid2"]][0]
    assert other["billed"] == 0 and other["margin_pct"] is None
    assert data["summary"]["total_billed"] == 1180.0 and data["summary"]["total_expenses"] == 380.0
    assert data["summary"]["total_billed_net"] == 1000.0 and data["summary"]["net_margin"] == 620.0
    assert data["summary"]["margin_basis"] == "sin_itbis"
    one = client.get(f"/reports/project-profitability?project_id={pid}", headers=_hdr()).json()["data"]
    assert [x["project_id"] for x in one["projects"]] == [pid]
    later = client.get("/reports/project-profitability?start_date=2026-11-01", headers=_hdr()).json()["data"]
    assert later["summary"]["total_billed"] == 0 and later["summary"]["total_expenses"] == 0


@needs_db
def test_expenses_by_category_report(db):
    pid = db["pid"]
    _post_expense(project_id=pid, amount=60)
    _post_expense(category="Combustible", amount=40)
    data = client.get("/reports/expenses-by-category", headers=_hdr()).json()["data"]
    assert data["summary"]["total_expenses"] == 100.0
    assert data["summary"]["assigned_to_projects"] == 60.0 and data["summary"]["unassigned"] == 40.0
    assert data["categories"][0] == {"category": "Materiales", "total": 60.0, "count": 1, "percentage": 60.0}
    only = client.get(f"/reports/expenses-by-category?project_id={pid}", headers=_hdr()).json()["data"]
    assert only["summary"]["total_expenses"] == 60.0 and len(only["categories"]) == 1


@needs_db
def test_invoice_without_itbis_is_flagged_and_counted_as_net(db):
    import psycopg2
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("INSERT INTO quotes (quote_id, client_id, status) VALUES ('q-legacy', %s, 'Invoiced')", (db["cid"],))
    cur.execute("INSERT INTO projects (client_id, name, start_date, quote_id) VALUES (%s, 'Legacy', '2026-10-01', 'q-legacy') "
                "RETURNING id", (db["cid"],))
    pid = cur.fetchone()[0]
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, status, total_amount, itbis_total, invoice_date) "
                "VALUES ('F-L', 'q-legacy', %s, 'Pending', 500, 0, '2026-10-05')", (db["cid"],))
    conn.commit()
    conn.close()
    p = client.get(f"/reports/project-profitability?project_id={pid}", headers=_hdr()).json()["data"]["projects"][0]
    assert p["invoices_without_itbis"] == 1
    assert p["billed_net"] == 500.0 and p["margin_pct"] == 100.0
