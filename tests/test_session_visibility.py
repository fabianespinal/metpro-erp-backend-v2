"""Set 5: /auth/me fields and fresh name; invoice detail client, own lines, correct balance."""
import importlib
import os
import sys

from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import invoices.service as isvc  # noqa: E402
from invoices.models import Invoice  # noqa: E402

auth_service = importlib.import_module("auth.service")
auth_router = importlib.import_module("auth.router")


class Cur:
    def __init__(self, rows):
        self.rows = rows  # list of (needle, one, many)
        self.sql = []
        self._one, self._many = None, []

    def execute(self, sql, params=None):
        n = " ".join(sql.split())
        self.sql.append(n)
        for needle, one, many in self.rows:
            if needle in n:
                self._one, self._many = one, many
                return
        self._one, self._many = None, []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def close(self):
        pass


def _client(monkeypatch, full_name):
    from fastapi import FastAPI
    from core.errors import register_error_handlers
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_router.router)
    # Role source is require_auth's concern (DB role arrives with Set 2). Here: token role.
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    monkeypatch.setattr(auth_router, "get_db_connection",
                        lambda: Conn(Cur([("SELECT full_name FROM users", {"full_name": full_name}, [])])))
    token = auth_service.create_access_token({"sub": "admin", "user_id": "u-1", "role": "admin", "name": None})
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_me_returns_all_fields_with_fresh_name(monkeypatch):
    client, h = _client(monkeypatch, "Fabian E.")
    body = client.get("/auth/me", headers=h).json()
    assert body == {"username": "admin", "user_id": "u-1", "role": "admin", "name": "Fabian E."}


def test_me_name_null_when_no_full_name(monkeypatch):
    client, h = _client(monkeypatch, None)
    assert client.get("/auth/me", headers=h).json()["name"] is None


def _detail(monkeypatch, invoice_row, item_rows, quote_items=()):
    cur = Cur([
        ("FROM invoices i WHERE i.id", invoice_row, []),
        ("FROM invoice_items", None, item_rows),
        ("FROM quote_items", None, list(quote_items)),
        ("SELECT included_charges FROM quotes", None, []),
    ])
    monkeypatch.setattr(isvc, "get_db_connection", lambda: Conn(cur))
    return isvc.get_invoice_by_id(5), cur


BASE = {"id": 5, "quote_id": "q", "total_amount": 118.0, "client_id": 7}


def test_detail_has_client_name_and_invoice_lines(monkeypatch):
    inv, cur = _detail(monkeypatch, dict(BASE, client_name="ACME", amount_paid=0, amount_due=118.0),
                       [{"description": "IPE", "quantity": 1, "unit_price": 100, "discount": 0, "total": 100}])
    assert inv["client_name"] == "ACME"
    assert inv["items"][0]["product_name"] == "IPE" and inv["items"][0]["total"] == 100
    assert "client_name" in cur.sql[0]
    assert not any("FROM quote_items" in s for s in cur.sql)


def test_paid_invoice_shows_zero_due(monkeypatch):
    inv, _ = _detail(monkeypatch, dict(BASE, amount_paid=118.0, amount_due=0), [])
    assert inv["amount_due"] == 0.0


def test_null_due_falls_back_to_total_minus_paid(monkeypatch):
    inv, _ = _detail(monkeypatch, dict(BASE, amount_paid=18.0, amount_due=None), [])
    assert inv["amount_due"] == 100.0


def test_invoice_model_keeps_items():
    m = Invoice(id=1, quote_id="q", invoice_number="INV-1", invoice_date="2026-10-16T00:00:00",
                client_id=7, total_amount=1, status="Pending", created_at="2026-10-16T00:00:00",
                updated_at="2026-10-16T00:00:00", items=[{"product_name": "X"}])
    assert m.model_dump()["items"] == [{"product_name": "X"}]
