"""Users admin (reset, last-superadmin guard, self-delete guard) and created_by passthrough.

Service and router level tests with a scripted fake DB cursor. No database.
"""
import importlib
import os
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import users.service as usvc  # noqa: E402
urouter = importlib.import_module("users.router")  # noqa: E402
from users.models import UserPasswordReset  # noqa: E402
import quotes.service as qsvc  # noqa: E402
import invoices.service as isvc  # noqa: E402

UID = "11111111-2222-3333-4444-555555555555"
OTHER_UID = "99999999-8888-7777-6666-555555555555"
CREATOR = "creator-uuid"


def R(needle, one=None, many=None, rowcount=1):
    """Route: when the normalized SQL contains needle, return these results."""
    return (needle, one, many if many is not None else [], rowcount)


class Scripted:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self._one = None
        self._many = []
        self.rowcount = 0

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

    def executed(self, needle):
        return bool(self.sql_with(needle))


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _patch_db(monkeypatch, module, cursor):
    conn = FakeConn(cursor)
    monkeypatch.setattr(module, "get_db_connection", lambda: conn)
    return conn


def _target(role, active=True):
    return R("SELECT id, role, is_active FROM users WHERE id",
          one={"id": UID, "role": role, "is_active": active})


UPDATED_ROW = {"id": UID, "username": "u", "email": "e", "full_name": "n",
               "role": "user", "is_active": True, "created_at": None}


# ============================================================
# Admin password reset
# ============================================================

@pytest.fixture
def hasher(monkeypatch):
    monkeypatch.setattr(usvc, "get_password_hash", lambda p: "HASH:" + p)


def test_reset_password_unknown_user_404(monkeypatch, hasher):
    cur = Scripted([R("SELECT id FROM users WHERE id", one=None)])
    _patch_db(monkeypatch, usvc, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.reset_user_password(UID, "new-pass")
    assert exc.value.status_code == 404
    assert exc.value.code == "USER_NOT_FOUND"


def test_reset_password_writes_hash_only(monkeypatch, hasher):
    cur = Scripted([
        R("SELECT id FROM users WHERE id", one={"id": UID}),
        R("UPDATE users SET password_hash", rowcount=1),
    ])
    conn = _patch_db(monkeypatch, usvc, cur)
    result = usvc.reset_user_password(UID, "new-pass")
    updates = cur.sql_with("UPDATE users SET password_hash")
    assert len(updates) == 1
    sql, params = updates[0]
    assert "updated_at" not in sql
    assert params == ("HASH:new-pass", UID)
    assert conn.committed is True
    assert result == {"message": "Password reset successfully"}


def test_reset_route_passes_through_to_service(monkeypatch):
    seen = {}

    def fake_reset(user_id, new_password):
        seen["args"] = (user_id, new_password)
        return {"message": "Password reset successfully"}

    monkeypatch.setattr(usvc, "reset_user_password", fake_reset)
    out = urouter.reset_password(
        user_id=UID,
        password_reset=UserPasswordReset(new_password="new-pass"),
        _admin={"role": "admin"},
    )
    assert seen["args"] == (UID, "new-pass")
    assert out == {"message": "Password reset successfully"}


# ============================================================
# Last-superadmin guard (update)
# ============================================================

def test_update_demote_last_superadmin_blocked(monkeypatch):
    cur = Scripted([
        _target("superadmin", True),
        R("count(*) AS n FROM users WHERE role = 'superadmin'", one={"n": 0}),
    ])
    _patch_db(monkeypatch, usvc, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.update_user(UID, None, None, "user", None)
    assert exc.value.code == "LAST_SUPERADMIN"
    assert not cur.executed("UPDATE users SET")


def test_update_deactivate_last_superadmin_blocked(monkeypatch):
    cur = Scripted([
        _target("superadmin", True),
        R("count(*) AS n FROM users WHERE role = 'superadmin'", one={"n": 0}),
    ])
    _patch_db(monkeypatch, usvc, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.update_user(UID, None, None, None, False)
    assert exc.value.code == "LAST_SUPERADMIN"
    assert not cur.executed("UPDATE users SET")


def test_update_demote_allowed_when_other_active_superadmin(monkeypatch):
    cur = Scripted([
        _target("superadmin", True),
        R("count(*) AS n FROM users WHERE role = 'superadmin'", one={"n": 1}),
        R("UPDATE users SET", rowcount=1),
        R("SELECT id, username, email, full_name, role, is_active, created_at", one=UPDATED_ROW),
    ])
    conn = _patch_db(monkeypatch, usvc, cur)
    out = usvc.update_user(UID, None, None, "user", None)
    assert cur.executed("UPDATE users SET")
    assert conn.committed is True
    assert out == UPDATED_ROW


def test_update_non_superadmin_skips_guard(monkeypatch):
    cur = Scripted([
        _target("user", True),
        R("UPDATE users SET", rowcount=1),
        R("SELECT id, username, email, full_name, role, is_active, created_at", one=UPDATED_ROW),
    ])
    _patch_db(monkeypatch, usvc, cur)
    usvc.update_user(UID, None, None, None, False)
    assert not cur.executed("count(*)")


# ============================================================
# Last-superadmin guard (delete) and self-delete guard
# ============================================================

def test_delete_last_superadmin_blocked(monkeypatch):
    cur = Scripted([
        R("SELECT role, is_active FROM users WHERE id", one={"role": "superadmin", "is_active": True}),
        R("count(*) AS n FROM users WHERE role = 'superadmin'", one={"n": 0}),
        R("DELETE FROM users WHERE id", rowcount=1),
    ])
    _patch_db(monkeypatch, usvc, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.delete_user(UID)
    assert exc.value.code == "LAST_SUPERADMIN"
    assert not cur.executed("DELETE FROM users WHERE id")


def test_delete_non_superadmin_skips_guard(monkeypatch):
    cur = Scripted([
        R("SELECT role, is_active FROM users WHERE id", one={"role": "user", "is_active": True}),
        R("DELETE FROM users WHERE id", rowcount=1),
    ])
    _patch_db(monkeypatch, usvc, cur)
    assert usvc.delete_user(UID) == {"message": "User deleted successfully"}
    assert not cur.executed("count(*)")


def test_self_delete_blocked_at_router():
    with pytest.raises(HTTPException) as exc:
        urouter.delete_user(user_id=UID, current_user={"user_id": UID, "role": "superadmin"})
    assert exc.value.status_code == 400
    assert exc.value.code == "CANNOT_DELETE_SELF"


# ============================================================
# created_by passthrough
# ============================================================

DUP_ORIGINAL = {
    "quote_id": "orig-1", "client_id": 7, "contact_id": 3, "project_name": "Warehouse",
    "notes": "n", "status": "Sent", "included_charges": {"supervision": True},
    "total_amount": 1500.0, "payment_terms": "30 days", "valid_until": None,
    "terms": "t", "subtotal": 100.0, "discount_total": 5.0, "tax_amount": 18.0,
    "grand_total": 118.0,
}
DUP_ITEMS = [
    {"id": 1, "quote_id": "orig-1", "product_id": 42, "product_name": "IPE 200",
     "quantity": 4.0, "unit_price": 100.0, "discount_type": "percentage",
     "discount_value": 5.0, "item_type": "product", "description": None},
]


def test_duplicate_writes_created_by(monkeypatch):
    cur = Scripted([
        R("valid_until, terms, subtotal", one=DUP_ORIGINAL),
        R("SELECT * FROM quote_items", many=DUP_ITEMS),
        R("INSERT INTO quotes"),
        R("SELECT quote_id, client_id, project_name", one={
            "quote_id": "new-1", "client_id": 7, "project_name": "W", "notes": "n",
            "status": "Draft", "included_charges": {}, "total_amount": 1.0,
            "payment_terms": None, "valid_until": None, "created_at": None, "updated_at": None,
        }),
    ])
    _patch_db(monkeypatch, qsvc, cur)
    monkeypatch.setattr(qsvc, "generate_quote_id", lambda: "new-1")
    monkeypatch.setattr(qsvc, "execute_values", lambda *a, **k: None)
    qsvc.duplicate_quote("orig-1", CREATOR)
    sql, params = cur.sql_with("INSERT INTO quotes")[0]
    assert params[15] == CREATOR
    assert sql.endswith("NULL)")  # public_token still written as literal NULL


def test_create_invoice_from_quote_writes_created_by(monkeypatch):
    cur = Scripted([
        R("SELECT * FROM quotes WHERE quote_id", one={"quote_id": "q1", "client_id": 7, "status": "Approved", "included_charges": {}}),
        R("SELECT id FROM invoices WHERE quote_id", one=None),
        R("SELECT * FROM quote_items", many=[
            {"product_name": "X", "quantity": 1, "unit_price": 100.0, "discount_value": 0},
        ]),
        R("INSERT INTO invoices", one={
            "id": 9, "invoice_number": "INV-1", "quote_id": "q1", "client_id": 7,
            "total_amount": 100.0, "amount_paid": 0, "amount_due": 100.0, "status": "Pending",
            "invoice_date": "2026-10-16", "notes": None, "created_at": None, "updated_at": None,
        }),
        R("UPDATE quotes SET status"),
    ])
    _patch_db(monkeypatch, isvc, cur)
    monkeypatch.setattr(isvc, "calculate_invoice_totals", lambda items, charges: {"grand_total": 100.0})
    monkeypatch.setattr(isvc, "generate_invoice_number", lambda: "INV-1")
    isvc.create_invoice_from_quote("q1", None, CREATOR)
    sql, params = cur.sql_with("INSERT INTO invoices")[0]
    assert params[9] == CREATOR
    assert len(params) == 10


def test_convert_quote_to_invoice_writes_created_by(monkeypatch):
    cur = Scripted([
        R("included_charges, total_amount, grand_total, payment_terms, valid_until", one={
            "quote_id": "q1", "client_id": 7, "contact_id": 3, "project_name": "W",
            "notes": None, "status": "Approved", "included_charges": {},
            "total_amount": 118.0, "grand_total": 118.0, "payment_terms": "30 days",
            "valid_until": None,
        }),
        R("SELECT id FROM invoices WHERE quote_id", one=None),
        R("SELECT * FROM quote_items", many=[]),
        R("INSERT INTO invoices", one={"id": 5}),
        R("UPDATE quotes SET status = 'Invoiced'"),
        R("SELECT i.*, q.payment_terms", one={"id": 5, "quote_id": "q1", "client_id": 7}),
        R("SELECT * FROM invoice_items", many=[]),
    ])
    _patch_db(monkeypatch, qsvc, cur)
    monkeypatch.setattr(qsvc, "execute_values", lambda *a, **k: None)
    qsvc.convert_quote_to_invoice("q1", CREATOR)
    sql, params = cur.sql_with("INSERT INTO invoices")[0]
    assert params[10] == CREATOR
    assert len(params) == 11


def test_update_user_sql_has_no_updated_at(monkeypatch):
    cur = Scripted([
        _target("user", True),
        R("UPDATE users SET", rowcount=1),
        R("SELECT id, username, email, full_name, role, is_active, created_at", one=UPDATED_ROW),
    ])
    _patch_db(monkeypatch, usvc, cur)
    usvc.update_user(UID, None, "New Name", None, None)
    sql, _ = cur.sql_with("UPDATE users SET")[0]
    assert "updated_at" not in sql


def test_invoice_model_exposes_client_name():
    from invoices.models import Invoice
    assert "client_name" in Invoice.model_fields


def test_invoice_detail_query_returns_created_by_name(monkeypatch):
    import invoices.service as isvc2
    cur = Scripted([
        R("FROM invoices i WHERE i.id", one={
            "id": 3, "quote_id": "q1", "client_id": 7, "total_amount": 100.0,
            "created_by_name": "Ana Test",
        }),
        R("SELECT included_charges FROM quotes", one=None),
    ])
    _patch_db(monkeypatch, isvc2, cur)
    out = isvc2.get_invoice_by_id(3)
    assert out["created_by_name"] == "Ana Test"
    sql, _ = cur.sql_with("FROM invoices i WHERE i.id")[0]
    assert "u.id = i.created_by_user_id" in sql
