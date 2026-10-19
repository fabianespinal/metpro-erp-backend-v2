"""Quote debug pass tests (bug 8).

Covers: public token view 200/404, edits locked outside Draft, GET /quotes/{id}
response fields, convert uses stored grand_total and marks the quote Invoiced in
the same transaction, public PDF uses stored totals, status update row lock.

Fake DB cursor pattern, same as test_quote_duplicate.py.
"""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes.service as svc  # noqa: E402
router_mod = importlib.import_module("quotes.router")  # noqa: E402

TOKEN = "6f1c2a3e-9b7d-4c1e-8a2f-0d3b5e7f9a1c"


class LogCursor:
    """Records every execute and commit in order. Returns queued fetch results."""

    def __init__(self, fetchone_queue=None, fetchall_queue=None):
        self.log = []
        self._one = list(fetchone_queue or [])
        self._all = list(fetchall_queue or [])

    def execute(self, sql, params=None):
        self.log.append(("SQL", " ".join(sql.split()), params))

    def fetchone(self):
        return self._one.pop(0) if self._one else None

    def fetchall(self):
        return self._all.pop(0) if self._all else []


class LogConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True
        self._cursor.log.append(("COMMIT", None, None))

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


# ---------------------------------------------------------------- public view

def test_public_token_known_returns_200_and_hides_token(monkeypatch):
    monkeypatch.setattr(svc, "quote_id_for_public_token", lambda token: "q-1")
    monkeypatch.setattr(
        svc,
        "get_quote_with_contact",
        lambda quote_id: {"quote_id": quote_id, "public_token": TOKEN, "status": "Final"},
    )
    body = router_mod.get_quote_public(TOKEN)
    assert body["status"] == "Final"
    assert "public_token" not in body
    assert "quote_id" not in body  # B-22: no internal UUID on the public payload


def test_public_token_unknown_returns_404(monkeypatch):
    from fastapi import HTTPException

    cursor = LogCursor(fetchone_queue=[None])
    monkeypatch.setattr(svc, "get_db_connection", lambda: LogConn(cursor))
    with pytest.raises(HTTPException) as exc:
        svc.quote_id_for_public_token(TOKEN)
    assert exc.value.status_code == 404
    assert exc.value.code == "QUOTE_NOT_FOUND"


# ------------------------------------------------------------- edits locked

class _Update:
    def dict(self, exclude_unset=True):
        return {}


@pytest.mark.parametrize("status", ["Approved", "Invoiced", "Sent", "Rejected"])
def test_non_draft_quote_cannot_be_edited(monkeypatch, status):
    cursor = LogCursor(fetchone_queue=[{"quote_id": "q-1", "status": status}])
    monkeypatch.setattr(svc, "get_db_connection", lambda: LogConn(cursor))
    with pytest.raises(Exception) as exc:
        svc.update_quote("q-1", _Update())
    assert exc.value.code == "QUOTE_NOT_DRAFT"


def test_final_quote_cannot_be_edited(monkeypatch):
    cursor = LogCursor(fetchone_queue=[{"quote_id": "q-1", "status": "Final"}])
    monkeypatch.setattr(svc, "get_db_connection", lambda: LogConn(cursor))
    with pytest.raises(Exception) as exc:
        svc.update_quote("q-1", _Update())
    assert exc.value.code == "QUOTE_FINALIZED"


def test_edit_flag_is_off():
    assert svc.ALLOW_EDIT_NON_DRAFT_QUOTES is False


# ------------------------------------------------------- GET /quotes/{id} fields

RESPONSE_FIELDS = {
    "subtotal", "discount_total", "tax_amount", "grand_total",
    "terms", "finalized_at", "public_token",
}


def test_get_quote_select_returns_totals_terms_and_token_fields(monkeypatch):
    row = {
        "quote_id": "q-1", "client_id": 1, "contact_id": 2, "project_name": "P",
        "notes": None, "status": "Final", "included_charges": {}, "total_amount": 118.0,
        "subtotal": 100.0, "discount_total": 0.0, "tax_amount": 18.0, "grand_total": 118.0,
        "terms": "net 30", "payment_terms": None, "valid_until": None,
        "finalized_at": None, "public_token": TOKEN,
        "created_at": None, "updated_at": None,
    }
    cursor = LogCursor(fetchone_queue=[row], fetchall_queue=[[]])
    monkeypatch.setattr(svc, "get_db_connection", lambda: LogConn(cursor))

    result = svc.get_quote_by_id("q-1")

    select_sql = next(sql for kind, sql, _ in cursor.log if kind == "SQL" and "FROM quotes" in sql)
    for field in RESPONSE_FIELDS:
        assert field in select_sql, f"GET quote SELECT is missing {field}"
    for field in RESPONSE_FIELDS:
        assert field in result, f"GET quote response is missing {field}"
    assert result["grand_total"] == 118.0


# ------------------------------------------------- convert: stored total + Invoiced

def test_convert_uses_stored_grand_total_and_marks_invoiced_in_same_transaction(monkeypatch):
    quote_row = {
        "quote_id": "q-1", "client_id": 1, "contact_id": 2, "project_name": "P",
        "notes": None, "status": "Approved", "included_charges": {},
        "total_amount": 3015.51, "grand_total": 3015.51,
        "payment_terms": None, "valid_until": None,
    }
    invoice_row = {
        "id": 7, "invoice_number": "INV-TEST", "quote_id": "q-1", "client_id": 1,
        "status": "Pending", "total_amount": 3015.51, "invoice_date": "2026-10-16",
        "payment_terms": None, "valid_until": None,
    }
    # fetchone: quote, duplicate-invoice check (None), earlier-invoice count, INSERT RETURNING id, final SELECT
    cursor = LogCursor(
        fetchone_queue=[quote_row, None, {"n": 0}, {"id": 7}, None, invoice_row],  # None: X-01 project lookup  # B-06: count of earlier invoices
        fetchall_queue=[[], []],  # quote_items (none), invoice_items after commit
    )
    conn = LogConn(cursor)
    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)

    svc.convert_quote_to_invoice("q-1")

    log = cursor.log
    insert_idx = next(i for i, (k, s, _) in enumerate(log) if k == "SQL" and s.startswith("INSERT INTO invoices"))
    update_idx = next(i for i, (k, s, _) in enumerate(log) if k == "SQL" and "SET status = 'Invoiced'" in s)
    commit_idx = next(i for i, (k, _, _) in enumerate(log) if k == "COMMIT")
    assert insert_idx < update_idx < commit_idx, "quote status must change in the same transaction"

    insert_params = log[insert_idx][2]
    assert insert_params[5] == 3015.51  # stored grand_total, not recomputed
    assert conn.committed is True


def test_convert_legacy_quote_without_stored_total_falls_back_to_computation(monkeypatch):
    quote_row = {
        "quote_id": "q-2", "client_id": 1, "contact_id": 2, "project_name": None,
        "notes": None, "status": "Approved", "included_charges": {},
        "total_amount": None, "grand_total": None, "payment_terms": None, "valid_until": None,
    }
    invoice_row = {"id": 8, "invoice_number": "INV-L", "quote_id": "q-2", "client_id": 1,
                   "status": "Pending", "total_amount": 0, "invoice_date": "2026-10-16",
                   "payment_terms": None, "valid_until": None}
    cursor = LogCursor(
        fetchone_queue=[quote_row, None, {"n": 0}, {"id": 8}, None, invoice_row],  # None: X-01 project lookup  # B-06: count of earlier invoices
        fetchall_queue=[[], []],
    )
    monkeypatch.setattr(svc, "get_db_connection", lambda: LogConn(cursor))
    svc.convert_quote_to_invoice("q-2")
    insert = next(p for k, s, p in cursor.log if k == "SQL" and s.startswith("INSERT INTO invoices"))
    assert insert[5] == 0.0  # no items, no charges: computed grand_total is zero


# ------------------------------------------------------------- public PDF totals

def _pdf_capture(monkeypatch):
    captured = {}

    def fake_pdf(**kwargs):
        captured.update(kwargs)
        return iter([b"%PDF"])

    monkeypatch.setattr(router_mod, "create_quote_pdf", fake_pdf)
    return captured


def _public_quote(**overrides):
    base = {
        "quote_id": "q-1", "quote_number": 10001, "public_token": TOKEN, "status": "Final",
        "company_name": "ACME", "company_address": "", "contact_name": "", "contact_email": "",
        "contact_phone": "", "project_name": "P", "notes": "", "payment_terms": None,
        "valid_until": None, "created_at": None,
        "included_charges": {"supervision": True, "supervision_percentage": 10,
                             "admin": False, "insurance": False,
                             "transport": False, "contingency": False},
        "items": [{"quantity": 2, "unit_price": 100.0, "discount_type": "none",
                   "discount_value": 0, "product_name": "X", "item_type": "product",
                   "description": None}],
        "subtotal": 220.0, "discount_total": 0.0, "tax_amount": 39.6, "grand_total": 259.6,
    }
    base.update(overrides)
    return base


def test_public_pdf_uses_stored_totals(monkeypatch):
    monkeypatch.setattr(svc, "quote_id_for_public_token", lambda token: "q-1")
    monkeypatch.setattr(svc, "get_quote_with_contact", lambda quote_id: _public_quote())
    captured = _pdf_capture(monkeypatch)

    router_mod.get_quote_public_pdf(TOKEN)

    assert captured["doc_id"] == "Q-10001"  # printed number is Q-<sequence>, not the UUID
    assert captured["grand_total"] == 259.6
    assert captured["itbis"] == 39.6
    assert captured["subtotal_general"] == 220.0


def test_public_pdf_legacy_quote_without_stored_totals_recomputes(monkeypatch):
    monkeypatch.setattr(svc, "quote_id_for_public_token", lambda token: "q-1")
    monkeypatch.setattr(
        svc, "get_quote_with_contact",
        lambda quote_id: _public_quote(subtotal=None, discount_total=None,
                                       tax_amount=None, grand_total=None),
    )
    captured = _pdf_capture(monkeypatch)

    router_mod.get_quote_public_pdf(TOKEN)

    # 200 * 1.10 supervision = 220 subtotal; ITBIS 18% = 39.6; total 259.6
    assert round(captured["grand_total"], 2) == 259.6


# ------------------------------------------------------------- status row lock

def test_status_update_takes_row_lock(monkeypatch):
    cursor = LogCursor(fetchone_queue=[{"quote_id": "q-1", "status": "Final"}])
    monkeypatch.setattr(svc, "get_db_connection", lambda: LogConn(cursor))
    svc.update_quote_status("q-1", "Approved")
    select = next(s for k, s, _ in cursor.log if k == "SQL" and s.startswith("SELECT quote_id, status FROM quotes"))
    assert select.endswith("FOR UPDATE")
