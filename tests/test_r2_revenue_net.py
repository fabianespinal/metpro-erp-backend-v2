"""Approved 2026-10-22: revenue is the subtotal before tax. Neither tax contributes, whatever the tax type."""
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


@needs_db
def test_revenue_excludes_both_taxes(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "reports.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE invoice_payments, invoice_items, invoices, quote_items, quotes, contacts, clients RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO clients (company_name) VALUES ('C') RETURNING id")
    cid = cur.fetchone()["id"]
    # 1.8% invoice: subtotal 1000, tax 18, total 1018.  18% invoice: subtotal 1000, tax 180, total 1180.
    for num, total, tax, code, rate, label in (("F-1", 1018, 18, "construction_17_2017", 0.018, "Construcción (Ley 17-2017)"),
                                                ("F-2", 1180, 180, "itbis_18", 0.18, "ITBIS (18%)")):
        cur.execute("INSERT INTO invoices (invoice_number, client_id, status, total_amount, grand_total, itbis_total, amount_paid, "
                    "amount_due, invoice_date, tax_type_code, tax_rate, tax_label) VALUES (%s,%s,'Pending',%s,%s,%s,%s,%s,"
                    "'2026-10-20',%s,%s,%s) RETURNING id", (num, cid, total, total, tax, total / 2, total / 2, code, rate, label))
        iid = cur.fetchone()["id"]
        cur.execute("INSERT INTO invoice_payments (invoice_id, amount, payment_date, method) VALUES (%s, %s, '2026-10-21', 'x')", (iid, total / 2))
    conn.commit()
    conn.close()
    token = create_access_token({"sub": "t", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})
    r = client.get("/reports/revenue", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    s = r.json()["data"]["summary"]
    assert s["basis"] == "sin_impuesto"
    assert s["invoiced_total"] == 2000.0       # not 2198
    assert s["total_revenue"] == 1000.0        # collected: half of each subtotal, not 1099
    assert s["outstanding"] == 1000.0
