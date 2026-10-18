"""Set 3, quote lifecycle: strict status matrix, send flow, delete guard, input bounds."""
import os
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes.service as svc  # noqa: E402
from quotes.models import IncludedCharges, QuoteItemBase  # noqa: E402


class Cur:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class Conn:
    def __init__(self, cur):
        self.cur, self.committed, self.rolled_back = cur, False, False

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _status(monkeypatch, current, target):
    cur = Cur([{"quote_id": "q", "status": current}])
    conn = Conn(cur)
    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)
    return cur, conn, lambda: svc.update_quote_status("q", target)


ALL = list(svc.QUOTE_STATUSES)
DEDICATED = {"Final": "QUOTE_USE_FINALIZE", "Sent": "QUOTE_USE_SEND",
             "Invoiced": "QUOTE_USE_CONVERT", "Draft": "QUOTE_REOPEN_BLOCKED"}


@pytest.mark.parametrize("current", ALL)
@pytest.mark.parametrize("target", ALL)
def test_full_status_matrix(monkeypatch, current, target):
    cur, conn, call = _status(monkeypatch, current, target)
    if target in DEDICATED:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.code == DEDICATED[target]
    elif target == current:
        assert call()["message"] == "Estado sin cambios"
    elif target in svc.MANUAL_QUOTE_TRANSITIONS[current]:
        assert call()["status"] == target and conn.committed
    else:
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.code == "QUOTE_TRANSITION_INVALID"
    if target in DEDICATED or (target != current and target not in svc.MANUAL_QUOTE_TRANSITIONS[current]):
        assert not any(s.startswith("UPDATE quotes SET status") for s, _ in cur.executed)


def test_no_path_back_to_draft():
    assert all("Draft" not in nxt for nxt in svc.MANUAL_QUOTE_TRANSITIONS.values())
    assert svc.MANUAL_QUOTE_TRANSITIONS["Invoiced"] == set()
    assert svc.MANUAL_QUOTE_TRANSITIONS["Rejected"] == set()


# ---------------- send ----------------

@pytest.mark.parametrize("status", ["Draft", "Rejected", "Invoiced"])
def test_send_refused_before_any_email(status):
    with pytest.raises(HTTPException) as exc:
        svc.assert_quote_sendable({"status": status, "public_token": "t", "contact_email": "a@b.co"})
    assert exc.value.code == "QUOTE_NOT_FINALIZED"


def test_send_refused_without_contact_email():
    with pytest.raises(HTTPException) as exc:
        svc.assert_quote_sendable({"status": "Final", "public_token": "t", "contact_email": None})
    assert exc.value.code == "QUOTE_NO_CONTACT_EMAIL"


@pytest.mark.parametrize("status", ["Final", "Sent", "Approved"])
def test_sendable_statuses(status):
    svc.assert_quote_sendable({"status": status, "public_token": "t", "contact_email": "a@b.co"})


def test_mark_sent_only_moves_final(monkeypatch):
    cur = Cur([{"status": "Sent"}])
    monkeypatch.setattr(svc, "get_db_connection", lambda: Conn(cur))
    assert svc.mark_quote_sent("q") == "Sent"
    sql, params = cur.executed[0]
    assert "AND status = %s" in sql and params == ("q", "Final")


def test_send_route_validates_before_building_pdf():
    import inspect
    import importlib
    src = inspect.getsource(importlib.import_module("quotes.router").send_quote)
    assert src.index("assert_quote_sendable") < src.index("create_quote_pdf(")
    assert "mark_quote_sent" in src and 'update_quote_status(quote_id, "Sent")' not in src


# ---------------- delete ----------------

@pytest.mark.parametrize("status", ["Final", "Sent", "Approved", "Invoiced"])
def test_delete_blocked_for_finalized(monkeypatch, status):
    cur = Cur([{"status": status}])
    monkeypatch.setattr(svc, "get_db_connection", lambda: Conn(cur))
    with pytest.raises(HTTPException) as exc:
        svc.delete_quote("q")
    assert exc.value.code == "QUOTE_DELETE_BLOCKED"
    assert not any(s.startswith("DELETE") for s, _ in cur.executed)


def test_delete_blocked_when_invoice_exists(monkeypatch):
    cur = Cur([{"status": "Rejected"}, {"id": 1}])
    monkeypatch.setattr(svc, "get_db_connection", lambda: Conn(cur))
    with pytest.raises(HTTPException) as exc:
        svc.delete_quote("q")
    assert exc.value.code == "QUOTE_DELETE_BLOCKED"


def test_delete_draft_removes_items_and_quote(monkeypatch):
    cur = Cur([{"status": "Draft"}, None])
    conn = Conn(cur)
    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)
    assert svc.delete_quote("q") == {"message": "Cotización eliminada correctamente"}
    deletes = [s for s, _ in cur.executed if s.startswith("DELETE")]
    assert deletes == ["DELETE FROM quote_items WHERE quote_id = %s", "DELETE FROM quotes WHERE quote_id = %s"]
    assert conn.committed


# ---------------- input bounds (Q10) ----------------

@pytest.mark.parametrize("field,value", [("quantity", -1), ("unit_price", -5), ("discount_value", -1)])
def test_negative_item_values_rejected(field, value):
    data = {"product_name": "X", "quantity": 1, "unit_price": 10, "discount_type": "none", "discount_value": 0}
    data[field] = value
    with pytest.raises(Exception):
        QuoteItemBase(**data)


def test_unknown_discount_type_rejected():
    with pytest.raises(Exception):
        QuoteItemBase(product_name="X", quantity=1, unit_price=10, discount_type="bogus")


def test_charge_percentage_bounds():
    with pytest.raises(Exception):
        IncludedCharges(admin_percentage=150)
    with pytest.raises(Exception):
        IncludedCharges(admin_percentage=-1)


@pytest.mark.parametrize("item,ok", [
    ({"quantity": 2, "unit_price": 50, "discount_type": "percentage", "discount_value": 100}, True),
    ({"quantity": 2, "unit_price": 50, "discount_type": "percentage", "discount_value": 101}, False),
    ({"quantity": 2, "unit_price": 50, "discount_type": "fixed", "discount_value": 100}, True),
    ({"quantity": 2, "unit_price": 50, "discount_type": "fixed", "discount_value": 100.5}, False),
])
def test_discount_ceilings(item, ok):
    if ok:
        svc._validate_item_discounts([item])
    else:
        with pytest.raises(HTTPException) as exc:
            svc._validate_item_discounts([item])
        assert exc.value.code == "QUOTE_DISCOUNT_INVALID"


# ---------------- joins (Q8) ----------------

def test_quote_reads_use_left_joins():
    import inspect
    detail = inspect.getsource(svc.get_quote_with_contact)
    listing = inspect.getsource(svc.get_all_quotes)
    assert "LEFT JOIN contacts" in detail and "LEFT JOIN clients" in detail
    assert "LEFT JOIN clients" in listing
