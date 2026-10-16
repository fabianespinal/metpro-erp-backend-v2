"""Item 9, module 4: quotes, invoices, pdf carry stable codes. Messages and statuses unchanged."""
import importlib
import os
import re
import sys
import time

from fastapi.testclient import TestClient
from jose import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
FILES = ["invoices/router.py", "invoices/service.py", "pdf/service.py", "quotes/service.py"]

# (file, status, message literal without quotes or f-prefix, code)
EXPECTED = {
    ("invoices/router.py", 404, "Invoice not found", "INVOICE_NOT_FOUND"),
    ("invoices/service.py", 404, "Quote not found", "QUOTE_NOT_FOUND"),
    ("invoices/service.py", 400, "Only approved quotes can be converted to invoices", "QUOTE_NOT_APPROVED"),
    ("invoices/service.py", 400, "Invoice already exists for this quote", "INVOICE_EXISTS"),
    ("invoices/service.py", 404, "Invoice not found", "INVOICE_NOT_FOUND"),
    ("invoices/service.py", 400, "Invalid status. Must be one of: {valid_statuses}", "INVOICE_STATUS_INVALID"),
    ("pdf/service.py", 404, "Quote not found", "QUOTE_NOT_FOUND"),
    ("pdf/service.py", 404, "Client not found", "CLIENT_NOT_FOUND"),
    ("pdf/service.py", 404, "Invoice not found", "INVOICE_NOT_FOUND"),
    ("quotes/service.py", 404, "Client not found", "CLIENT_NOT_FOUND"),
    ("quotes/service.py", 400, "Contact {contact_id} does not belong to client {client_id}", "CONTACT_CLIENT_MISMATCH"),
    ("quotes/service.py", 404, "Quote not found", "QUOTE_NOT_FOUND"),
    ("quotes/service.py", 400, "Only Draft quotes can be edited", "QUOTE_NOT_DRAFT"),
    ("quotes/service.py", 400, "Invalid status. Must be one of: {valid_statuses}", "QUOTE_STATUS_INVALID"),
    ("quotes/service.py", 400, "Only approved quotes can be converted to invoices", "QUOTE_NOT_APPROVED"),
    ("quotes/service.py", 400, "Finalized quotes cannot be edited", "QUOTE_FINALIZED"),
    ("quotes/service.py", 400, "Only Draft quotes can be finalized", "QUOTE_NOT_DRAFT"),
    ("quotes/service.py", 400, "Use the finalize endpoint to set Final", "QUOTE_USE_FINALIZE"),
    ("quotes/service.py", 400, "Finalized quotes can only move to Approved, Rejected or Invoiced", "QUOTE_FINALIZED"),
    ("quotes/service.py", 400, "Quote must have at least one item to finalize", "QUOTE_EMPTY"),
    ("quotes/service.py", 400, "Product not found", "PRODUCT_NOT_FOUND"),
    ("quotes/service.py", 400, "Invoice already exists for this quote", "INVOICE_EXISTS"),
}

CALL = re.compile(r"api_error\((\d+), (f?)([\"'])(.*?)\3, \"([A-Z_]+)\"\)", re.S)


def _calls(path):
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    return [(int(s), msg, code) for s, _p, _q, msg, code in CALL.findall(src)]


def test_no_bare_http_exception_raises_left():
    for path in FILES:
        src = open(os.path.join(ROOT, path), encoding="utf-8").read()
        assert "raise HTTPException(" not in src, path


def test_every_call_is_expected():
    for path in FILES:
        for status, msg, code in _calls(path):
            assert any(f == path and s == status and m == msg and c == code for f, s, m, c in EXPECTED), (path, status, msg, code)


def test_every_expected_entry_is_used():
    used = set()
    for path in FILES:
        for status, msg, code in _calls(path):
            used.add((path, status, msg, code))
    assert used == EXPECTED


# ---------- behavior ----------

class _Seq:
    def __init__(self, rows):
        self._rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def __init__(self, rows):
        self._cursor = _Seq(rows)

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _auth_headers():
    tok = jwt.encode({"sub": "alice", "role": "admin", "exp": int(time.time()) + 600},
                     "test-secret-key", algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _patch_auth_db(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn([{"is_active": True}]))


def _patch_service_db(monkeypatch, module_name, rows=()):
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "get_db_connection", lambda: _Conn(list(rows)))


def test_get_quote_missing_has_code(monkeypatch):
    _patch_auth_db(monkeypatch)
    _patch_service_db(monkeypatch, "quotes.service")
    resp = TestClient(app).get("/quotes/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Quote not found", "code": "QUOTE_NOT_FOUND"}


def test_get_invoice_missing_has_code(monkeypatch):
    _patch_auth_db(monkeypatch)
    _patch_service_db(monkeypatch, "invoices.service")
    resp = TestClient(app).get("/invoices/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Invoice not found", "code": "INVOICE_NOT_FOUND"}


def test_api_error_keeps_dynamic_message():
    from core.errors import api_error
    exc = api_error(400, f"Invalid status. Must be one of: {['Draft']}", "QUOTE_STATUS_INVALID")
    assert exc.detail == "Invalid status. Must be one of: ['Draft']"
    assert exc.code == "QUOTE_STATUS_INVALID"
