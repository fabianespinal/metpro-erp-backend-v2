"""Set 8 hygiene: one totals implementation, escaped emails, no connection leak."""
import importlib
import os
import pathlib
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import invoices.service as isvc  # noqa: E402
import email_service  # noqa: E402

auth_router = importlib.import_module("auth.router")

CHARGES = [
    {},
    {"supervision": True, "supervision_percentage": 10, "admin": True, "admin_percentage": 4,
     "insurance": True, "insurance_percentage": 1, "transport": True, "transport_percentage": 3,
     "contingency": True, "contingency_percentage": 3},
    {"supervision": True, "supervision_percentage": 12.5, "admin": False, "transport": True, "transport_percentage": 0},
]
ITEMS = [
    [],
    [{"quantity": 3, "unit_price": 99.99, "discount_type": "none", "discount_value": 0}],
    [{"quantity": 2, "unit_price": 50, "discount_type": "percentage", "discount_value": 7.5},
     {"quantity": 1, "unit_price": 1200, "discount_type": "fixed", "discount_value": 100}],
]


@pytest.mark.parametrize("charges", CHARGES)
@pytest.mark.parametrize("items", ITEMS)
def test_invoice_totals_identical_to_previous_copy(items, charges):
    assert isvc.calculate_invoice_totals(items, charges) == isvc._legacy_calculate_invoice_totals(items, charges)


def test_email_escapes_client_text(monkeypatch):
    sent = {}
    monkeypatch.setattr(email_service.resend.Emails, "send", lambda params: sent.update(params) or {"id": "x"})
    email_service.send_quote_email("a@b.co", "<b>Ana</b>", "ACME", "<script>x</script>", "10001", "tok", b"%PDF")
    assert "<script>" not in sent["html"] and "&lt;script&gt;" in sent["html"]
    assert "&lt;b&gt;Ana&lt;/b&gt;" in sent["html"]


def test_invoice_email_uses_invoice_number():
    src = (ROOT / "invoices" / "router.py").read_text()
    assert 'invoice_id=str(invoice["invoice_number"])' in src
    assert 'invoice_id=str(invoice["id"])' not in src


class _Cur:
    def __init__(self, row):
        self.row = row

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row, self.closed, self.rolled_back = row, False, False

    def cursor(self, cursor_factory=None):
        return _Cur(self.row)

    def commit(self):
        pass

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_change_password_closes_connection_on_error(monkeypatch):
    conn = _Conn({"password_hash": "h"})
    monkeypatch.setattr(auth_router, "get_db_connection", lambda: conn)
    monkeypatch.setattr(auth_router, "verify_password", lambda a, b: False)
    data = auth_router.ChangePasswordRequest(old_password="x", new_password="y")
    with pytest.raises(HTTPException):
        auth_router.change_password(data, {"sub": "alice"})
    assert conn.closed and conn.rolled_back


def test_dead_sqlite_config_removed():
    assert not (ROOT / "config" / "database.py").exists()


def test_search_path_migration_parses():
    pglast = pytest.importorskip("pglast")
    sql = (ROOT / "migrations" / "2026-10-16_function_search_path.sql").read_text()
    assert len(pglast.parse_sql(sql)) == 4
