"""Set 1, money integrity: payments, invoice status, invoice delete, convert header totals.

Scripted fake cursor. No database.
"""
import importlib
import inspect
import os
import pathlib
import re
import sys
from datetime import date

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import invoices.service as isvc  # noqa: E402
import invoices.payments.service as psvc  # noqa: E402
import quotes.service as qsvc  # noqa: E402
from invoices.payments.models import PaymentCreate  # noqa: E402

irouter = importlib.import_module("invoices.router")


def R(needle, one=None, many=None, rowcount=1):
    return (needle, one, many if many is not None else [], rowcount)


class Scripted:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self._one, self._many, self.rowcount = None, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.calls.append((norm, params))
        for needle, one, many, rowcount in self.routes:
            if needle in norm:
                self._one, self._many, self.rowcount = one, many, rowcount
                return
        self._one, self._many, self.rowcount = None, [], 0

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many

    def sql_with(self, needle):
        return [(s, p) for s, p in self.calls if needle in s]


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def pay(amount, method="cash"):
    return PaymentCreate(amount=amount, method=method, notes=None, payment_date=date(2026, 10, 16))


def invoice_row(status="Pending", total=100.0):
    return R("FROM invoices WHERE id = %s FOR UPDATE", one={"id": 5, "status": status, "total_amount": total})


# ============================================================
# Static guard: the wrong-column filter must never come back
# ============================================================

def test_no_invoice_payments_filtered_by_payment_id_anywhere():
    bad = re.compile(r"invoice_payments\s+WHERE\s+id\s*=", re.I)
    offenders = []
    for f in ROOT.rglob("*.py"):
        if "tests" in f.parts or ".venv" in f.parts:
            continue
        if bad.search(f.read_text(errors="ignore")):
            offenders.append(str(f.relative_to(ROOT)))
    assert offenders == []


# ============================================================
# create_payment
# ============================================================

def test_payment_sums_by_invoice_id_and_marks_paid():
    cur = Scripted([
        invoice_row("Pending", 100.0),
        R("SELECT COALESCE(SUM(amount), 0) AS total_paid FROM invoice_payments WHERE invoice_id", one={"total_paid": 40.0}),
        R("INSERT INTO invoice_payments", one={"id": 77}),
        R("UPDATE invoices"),
    ])
    conn = FakeConn(cur)
    assert psvc.create_payment(conn, 5, pay(60.0)) == 77
    sum_sql, sum_params = cur.sql_with("SUM(amount)")[0]
    assert "WHERE invoice_id = %s" in sum_sql and sum_params == (5,)
    _, upd = cur.sql_with("UPDATE invoices")[0]
    assert upd == (100.0, 0.0, "Paid", 5)
    assert conn.committed


def test_partial_payment_keeps_overdue():
    cur = Scripted([
        invoice_row("Overdue", 100.0),
        R("SUM(amount)", one={"total_paid": 0}),
        R("INSERT INTO invoice_payments", one={"id": 1}),
        R("UPDATE invoices"),
    ])
    psvc.create_payment(FakeConn(cur), 5, pay(25.0))
    _, upd = cur.sql_with("UPDATE invoices")[0]
    assert upd == (25.0, 75.0, "Overdue", 5)


@pytest.mark.parametrize("status", ["Paid", "Cancelled"])
def test_payment_refused_on_closed_invoice(status):
    cur = Scripted([invoice_row(status)])
    with pytest.raises(HTTPException) as exc:
        psvc.create_payment(FakeConn(cur), 5, pay(10.0))
    assert exc.value.code == "INVOICE_NOT_PAYABLE"
    assert not cur.sql_with("INSERT INTO invoice_payments")


def test_overpayment_refused():
    cur = Scripted([invoice_row("Pending", 100.0), R("SUM(amount)", one={"total_paid": 90.0})])
    with pytest.raises(HTTPException) as exc:
        psvc.create_payment(FakeConn(cur), 5, pay(10.02))
    assert exc.value.code == "PAYMENT_EXCEEDS_DUE"
    assert not cur.sql_with("INSERT INTO invoice_payments")


def test_payment_on_missing_invoice_404():
    cur = Scripted([R("FROM invoices WHERE id = %s FOR UPDATE", one=None)])
    with pytest.raises(HTTPException) as exc:
        psvc.create_payment(FakeConn(cur), 5, pay(10.0))
    assert exc.value.status_code == 404


def test_zero_amount_rejected_by_model():
    with pytest.raises(Exception):
        PaymentCreate(amount=0, method="cash", payment_date=date(2026, 10, 16))


def test_get_payments_filters_by_invoice_id():
    cur = Scripted([R("FROM invoice_payments p", many=[{"id": 1}])])
    assert psvc.get_payments_for_invoice(FakeConn(cur), 5) == [{"id": 1}]
    sql, params = cur.calls[0]
    assert "WHERE p.invoice_id = %s" in sql and params == (5,)  # the invoice FK, never the payment id


def test_payments_list_route_exists():
    paths = {(r.path, tuple(sorted(r.methods))) for r in irouter.router.routes}
    assert ("/invoices/{invoice_id}/payments", ("GET",)) in paths
    assert ("/invoices/{invoice_id}/payments", ("POST",)) in paths


# ============================================================
# delete_invoice
# ============================================================

def test_delete_refused_when_payments_exist(monkeypatch):
    cur = Scripted([
        R("SELECT id, quote_id FROM invoices WHERE id = %s FOR UPDATE", one={"id": 5, "quote_id": "q1"}),
        R("COUNT(*) AS n FROM invoice_payments WHERE invoice_id", one={"n": 1}),
    ])
    monkeypatch.setattr(isvc, "get_db_connection", lambda: FakeConn(cur))
    with pytest.raises(HTTPException) as exc:
        isvc.delete_invoice(5)
    assert exc.value.code == "INVOICE_HAS_PAYMENTS"
    assert not cur.sql_with("DELETE")


def test_delete_removes_items_then_invoice_and_reverts_only_invoiced_quote(monkeypatch):
    cur = Scripted([
        R("SELECT id, quote_id FROM invoices WHERE id = %s FOR UPDATE", one={"id": 5, "quote_id": "q1"}),
        R("COUNT(*) AS n FROM invoice_payments", one={"n": 0}),
        R("DELETE FROM invoice_items WHERE invoice_id"),
        R("DELETE FROM conduces WHERE invoice_id"),
        R("DELETE FROM invoices WHERE id"),
        R("UPDATE quotes SET status = 'Approved'", rowcount=1),
    ])
    conn = FakeConn(cur)
    monkeypatch.setattr(isvc, "get_db_connection", lambda: conn)
    out = isvc.delete_invoice(5)
    deletes = [s for s, _ in cur.calls if s.startswith("DELETE")]
    assert deletes[0].startswith("DELETE FROM invoice_items WHERE invoice_id")
    assert deletes[1].startswith("DELETE FROM conduces WHERE invoice_id")  # B-05
    assert deletes[2].startswith("DELETE FROM invoices WHERE id")
    assert not any("invoice_payments" in d for d in deletes)
    revert, _ = cur.sql_with("UPDATE quotes")[0]
    assert "AND status = 'Invoiced'" in revert
    assert out["quote_reverted"] is True and conn.committed


# ============================================================
# update_invoice_status (manual matrix)
# ============================================================

def _status_cursor(current, amount_paid=0):
    return Scripted([
        R("FROM invoices WHERE id = %s FOR UPDATE", one={"id": 5, "quote_id": "q1", "status": current, "amount_paid": amount_paid}),
        R("UPDATE invoices SET status"),
    ])


@pytest.mark.parametrize("current,target", [("Pending", "Overdue"), ("Overdue", "Pending"), ("Pending", "Cancelled")])
def test_allowed_manual_transitions(monkeypatch, current, target):
    cur = _status_cursor(current)
    monkeypatch.setattr(isvc, "get_db_connection", lambda: FakeConn(cur))
    monkeypatch.setattr(isvc, "get_invoice_by_id", lambda i: {"id": i, "status": target})
    assert isvc.update_invoice_status(5, target)["status"] == target
    assert cur.sql_with("UPDATE invoices SET status")


@pytest.mark.parametrize("current,target,code", [
    ("Pending", "Paid", "INVOICE_PAID_VIA_PAYMENTS"),
    ("Cancelled", "Pending", "INVOICE_TRANSITION_INVALID"),
    ("Paid", "Pending", "INVOICE_TRANSITION_INVALID"),
    ("Pending", "Bogus", "INVOICE_STATUS_INVALID"),
])
def test_refused_manual_transitions(monkeypatch, current, target, code):
    cur = _status_cursor(current)
    monkeypatch.setattr(isvc, "get_db_connection", lambda: FakeConn(cur))
    with pytest.raises(HTTPException) as exc:
        isvc.update_invoice_status(5, target)
    assert exc.value.code == code
    assert not cur.sql_with("UPDATE invoices SET status")


def test_cancel_refused_when_paid_something(monkeypatch):
    cur = _status_cursor("Pending", amount_paid=10)
    monkeypatch.setattr(isvc, "get_db_connection", lambda: FakeConn(cur))
    with pytest.raises(HTTPException) as exc:
        isvc.update_invoice_status(5, "Cancelled")
    assert exc.value.code == "INVOICE_HAS_PAYMENTS"


def test_status_route_is_admin_only():
    src = inspect.getsource(irouter.update_invoice_status)
    assert 'require_role("admin")' in src


# ============================================================
# convert writes header totals (P13)
# ============================================================

def test_convert_writes_header_totals(monkeypatch):
    quote = {
        "quote_id": "q1", "client_id": 7, "contact_id": 3, "project_name": "W", "notes": None,
        "status": "Approved", "included_charges": {}, "total_amount": 118.0,
        "grand_total": 118.0, "payment_terms": None, "valid_until": None,
        "tax_type_code": "itbis_18", "tax_rate": 0.18, "tax_label": "ITBIS (18%)",
    }
    items = [{"product_id": None, "product_name": "X", "quantity": 1, "unit_price": 100.0,
              "discount_type": "none", "discount_value": 0}]
    cur = Scripted([
        R("included_charges, total_amount, grand_total, payment_terms, valid_until", one=quote),
        R("SELECT id FROM invoices WHERE quote_id", one=None),
        R("SELECT COUNT(*) AS n FROM invoices WHERE quote_id", one={"n": 0}),  # B-06: earlier (cancelled) invoices
        R("SELECT * FROM quote_items", many=items),
        R("INSERT INTO invoices", one={"id": 5}),
        R("UPDATE quotes SET status = 'Invoiced'"),
        R("SELECT i.*, q.payment_terms", one={"id": 5}),
        R("SELECT * FROM invoice_items", many=[]),
    ])
    monkeypatch.setattr(qsvc, "get_db_connection", lambda: FakeConn(cur))
    monkeypatch.setattr(qsvc, "execute_values", lambda *a, **k: None)
    qsvc.convert_quote_to_invoice("q1", "creator")
    sql, params = cur.sql_with("INSERT INTO invoices")[0]
    assert "grand_total" in sql and "amount_due" in sql
    # subtotal, discounts, charges, itbis, grand_total, amount_paid, amount_due
    assert params[11:18] == (100.0, 0.0, 0.0, 18.0, 118.0, 0, 118.0)
