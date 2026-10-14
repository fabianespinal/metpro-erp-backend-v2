"""Step 4: clients and products handlers return generic detail; CSV row errors use a fixed reason."""
import asyncio
import importlib
import logging
import os
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SECRET_TEXT = "password authentication failed for user postgres.abc123 at 10.0.0.5"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EXPOSE_ERROR_DETAIL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)


def _broken_db(*args, **kwargs):
    raise RuntimeError(SECRET_TEXT)


def _assert_generic(exc_info, expected_context):
    err = exc_info.value
    assert isinstance(err, HTTPException)
    assert err.status_code == 500
    assert err.detail == expected_context
    assert SECRET_TEXT not in str(err.detail)
    assert "RuntimeError" not in str(err.detail)


# ---------- clients / products single-record handlers ----------

def test_create_client_returns_generic_detail(monkeypatch):
    cs = importlib.import_module("clients.service")
    monkeypatch.setattr(cs, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        cs.create_client("Acme", None, None, None, None, None, None)

    _assert_generic(exc_info, "Failed to create client")


def test_delete_client_returns_generic_detail(monkeypatch):
    cs = importlib.import_module("clients.service")
    monkeypatch.setattr(cs, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        cs.delete_client(1)

    _assert_generic(exc_info, "Delete failed")


def test_create_product_returns_generic_detail(monkeypatch):
    ps = importlib.import_module("products.service")
    monkeypatch.setattr(ps, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        ps.create_product("Widget", "desc", 1.0)

    _assert_generic(exc_info, "Failed to create product")


def test_delete_product_returns_generic_detail(monkeypatch):
    ps = importlib.import_module("products.service")
    monkeypatch.setattr(ps, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        ps.delete_product(1)

    _assert_generic(exc_info, "Delete failed")


# ---------- CSV import: row-level failure ----------

class _InsertFailsCursor:
    """Cursor that raises on any client INSERT, returns no duplicates."""

    def execute(self, sql, params=None):
        if "INSERT INTO clients" in sql:
            raise RuntimeError(SECRET_TEXT)

    def fetchone(self):
        return None


class _Conn:
    def cursor(self, *a, **k):
        return _InsertFailsCursor()

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_client_csv_row_error_uses_fixed_reason_and_logs_detail(monkeypatch, caplog):
    cs = importlib.import_module("clients.service")
    monkeypatch.setattr(cs, "get_db_connection", lambda: _Conn())

    csv_bytes = b"company_name,contact_name,email,phone,address,tax_id,notes\nAcme,,,,,,\n"

    with caplog.at_level(logging.ERROR, logger="metpro.clients"):
        result = asyncio.run(cs.import_clients_from_csv(csv_bytes, "clients.csv", True, {"sub": "tester"}))

    assert result["success"] is True
    assert result["errors"] == ["Row 2 (Acme): row could not be saved"]
    assert SECRET_TEXT not in " ".join(result["errors"])
    assert result["summary"]["skipped"] == 1

    records = [r for r in caplog.records if r.name == "metpro.clients"]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert str(records[0].exc_info[1]) == SECRET_TEXT


# ---------- CSV import: outer failure ----------

def test_client_csv_outer_failure_returns_generic_detail(monkeypatch):
    cs = importlib.import_module("clients.service")
    monkeypatch.setattr(cs, "get_db_connection", _broken_db)

    csv_bytes = b"company_name\nAcme\n"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(cs.import_clients_from_csv(csv_bytes, "clients.csv", True, {"sub": "tester"}))

    _assert_generic(exc_info, "Import failed")


def test_no_str_e_left_in_step4_files():
    here = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("clients/service.py", "products/service.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as fh:
            assert "str(e)" not in fh.read(), rel
