"""Client Profitability Report, Phase 1 (approved 2026-10-22). Read-only aggregation."""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


def _connect():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    return psycopg2.connect(DSN, cursor_factory=RealDictCursor)


def _invoice(cur, number, cid, total, tax, qid=None, date="2026-10-20", status="Pending", pay=0, voided=0):
    cur.execute(
        "INSERT INTO invoices (invoice_number, client_id, quote_id, status, total_amount, grand_total, itbis_total, "
        "amount_paid, amount_due, invoice_date, tax_type_code, tax_rate, tax_label) VALUES "
        "(%s,%s,%s,%s,%s,%s,%s,0,%s,%s,'itbis_18',0.18,'ITBIS (18%%)') RETURNING id",
        (number, cid, qid, status, total, total, tax, total, date))
    iid = cur.fetchone()["id"]
    if pay:
        cur.execute("INSERT INTO invoice_payments (invoice_id, amount, payment_date, method) VALUES (%s,%s,'2026-10-21','x')", (iid, pay))
    if voided:
        cur.execute("INSERT INTO invoice_payments (invoice_id, amount, payment_date, method, voided_at, void_reason, voided_by_user_id) "
                    "VALUES (%s,%s,'2026-10-21','x',now(),'error','00000000-0000-0000-0000-000000000001')", (iid, voided))
    return iid


def _quote(cur, qid, cid):
    cur.execute("INSERT INTO quotes (quote_id, client_id, tax_type_code, tax_rate, tax_label) VALUES (%s,%s,'itbis_18',0.18,'x')", (qid, cid))


def _project(cur, cid, name, qid=None):
    cur.execute("INSERT INTO projects (client_id, name, start_date, quote_id) VALUES (%s,%s,'2026-10-01',%s) RETURNING id", (cid, name, qid))
    return cur.fetchone()["id"]


def _expense(cur, amount, project_id=None, date="2026-10-15"):
    cur.execute("INSERT INTO expenses (date, category, amount, project_id) VALUES (%s,'Material',%s,%s)", (date, amount, project_id))


def _line(cur, iid, product_id, qty):
    cur.execute("INSERT INTO invoice_items (invoice_id, product_id, description, quantity, unit_price, total) "
                "VALUES (%s,%s,'l',%s,10,%s)", (iid, product_id, qty, qty * 10))


@pytest.fixture
def db(monkeypatch):
    for mod in ("database", "reports.service", "reports.client_profitability"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", _connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = _connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE expenses, projects, invoice_payments, invoice_items, invoices, quote_items, quotes, "
                "products, contacts, clients RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash) VALUES ('00000000-0000-0000-0000-000000000001','cp-test','x') "
                "ON CONFLICT (id) DO NOTHING")
    yield conn, cur
    conn.close()


def _get(path="/reports/client-profitability"):
    token = create_access_token({"sub": "t", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})
    r = client.get(path, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return r.json()["data"]


@needs_db
def test_revenue_cogs_profit_outstanding_and_general_bucket(db):
    conn, cur = db
    cur.execute("INSERT INTO clients (company_name) VALUES ('Alfa') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO products (name, unit_price, cost) VALUES ('P1', 10, 4) RETURNING id")
    p1 = cur.fetchone()["id"]
    cur.execute("INSERT INTO products (name, unit_price) VALUES ('P2', 10) RETURNING id")  # no cost
    p2 = cur.fetchone()["id"]
    _quote(cur, "q-1", cid)
    pid = _project(cur, cid, "Nave", "q-1")
    # Project invoice: total 1180, tax 180 -> revenue 1000. One costed line (qty 50 x 4 = 200), one uncosted.
    i1 = _invoice(cur, "F-1", cid, 1180, 180, qid="q-1", pay=500, voided=300)
    _line(cur, i1, p1, 50)
    _line(cur, i1, p2, 5)
    # Construction-tax invoice, no project: total 1018, tax 18 -> revenue 1000. Goes to General Client Activity.
    _invoice(cur, "F-2", cid, 1018, 18)
    _expense(cur, 150, pid)
    _expense(cur, 99)  # unlinked
    # Cancelled invoice never counts.
    _invoice(cur, "F-3", cid, 5000, 0, status="Cancelled")
    conn.commit()

    d = _get()
    c = d["clients"][0]
    assert c["client_name"] == "Alfa"
    assert c["revenue"] == 2000.0                 # no tax in revenue, either type
    assert c["product_cost"] == 200.0
    assert c["direct_costs"] == 150.0
    assert c["cogs"] == 350.0
    assert c["gross_profit"] == 1650.0
    assert c["profit_pct"] == 82.5
    assert c["outstanding"] == 680.0 + 1018.0     # voided payment does not reduce the balance
    assert c["cost_coverage_pct"] == 50.0  # 1 of 2 invoice lines costed
    names = [b["name"] for b in c["breakdown"]]
    assert names == ["Nave", "General Client Activity"]
    general = c["breakdown"][1]
    assert general["revenue"] == 1000.0 and general["direct_costs"] == 0.0
    assert d["summary"]["revenue"] == 2000.0
    assert d["summary"]["unlinked_expenses"] == {"count": 1, "amount": 99.0}


@needs_db
def test_filters_and_empty_revenue(db):
    conn, cur = db
    cur.execute("INSERT INTO clients (company_name) VALUES ('A'), ('B') RETURNING id")
    a, b = [r["id"] for r in cur.fetchall()]
    _invoice(cur, "F-1", a, 118, 18, date="2026-09-01")
    _invoice(cur, "F-2", b, 236, 36, date="2026-10-01")
    pid = _project(cur, b, "Solo gasto")
    _expense(cur, 50, pid, "2026-10-02")
    conn.commit()
    d = _get("/reports/client-profitability?client_id=%d" % a)
    assert [c["client_name"] for c in d["clients"]] == ["A"]
    assert d["summary"]["unlinked_expenses"] is None
    d = _get("/reports/client-profitability?start_date=2026-10-01&end_date=2026-10-31")
    assert [c["client_name"] for c in d["clients"]] == ["B"]
    assert d["clients"][0]["revenue"] == 200.0 and d["clients"][0]["gross_profit"] == 150.0


@needs_db
def test_client_with_only_expenses_has_no_percent(db):
    conn, cur = db
    cur.execute("INSERT INTO clients (company_name) VALUES ('C') RETURNING id")
    cid = cur.fetchone()["id"]
    pid = _project(cur, cid, "P")
    _expense(cur, 50, pid, "2026-10-02")
    conn.commit()
    c = _get()["clients"][0]
    assert c["revenue"] == 0.0 and c["gross_profit"] == -50.0 and c["profit_pct"] is None


@needs_db
def test_totals_match_project_report_margin_basis(db):
    """Same revenue basis as the project report: billed minus the invoice's own tax."""
    conn, cur = db
    cur.execute("INSERT INTO clients (company_name) VALUES ('D') RETURNING id")
    cid = cur.fetchone()["id"]
    _quote(cur, "q-9", cid)
    pid = _project(cur, cid, "P", "q-9")
    _invoice(cur, "F-1", cid, 1180, 180, qid="q-9")
    _expense(cur, 100, pid, "2026-10-02")
    conn.commit()
    from reports.service import get_project_profitability
    proj = get_project_profitability()["summary"]
    cp = _get()["summary"]
    assert cp["revenue"] == proj["total_billed_net"]
    assert cp["direct_costs"] == proj["total_expenses"]
    assert cp["gross_profit"] == proj["net_margin"]  # no product cost lines here


def test_requires_auth():
    assert client.get("/reports/client-profitability").status_code in (401, 403)


def test_rejects_inverted_range(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    token = create_access_token({"sub": "t", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})
    r = client.get("/reports/client-profitability?start_date=2026-10-31&end_date=2026-10-01",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
