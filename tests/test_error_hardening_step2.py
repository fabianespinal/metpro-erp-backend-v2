"""Step 2: quote and invoice handlers return generic 500 detail, never exception text."""
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


@pytest.mark.parametrize("func_name, args, context", [
    ("delete_quote", ("Q-1",), "No se pudo eliminar"),
    ("update_quote_status", ("Q-1", "Approved"), "No se pudo actualizar el estado"),
])
def test_quote_handlers_return_generic_detail(monkeypatch, func_name, args, context):
    import quotes.service as qs

    monkeypatch.setattr(qs, "get_db_connection", _broken_db)
    func = getattr(qs, func_name)

    with pytest.raises(HTTPException) as exc_info:
        func(*args)

    _assert_generic(exc_info, context)


@pytest.mark.parametrize("func_name, args, context", [
    ("update_invoice_status", (1, "Paid"), "No se pudo actualizar"),
    ("delete_invoice", (1,), "No se pudo eliminar"),
])
def test_invoice_handlers_return_generic_detail(monkeypatch, func_name, args, context):
    import invoices.service as inv

    monkeypatch.setattr(inv, "get_db_connection", _broken_db)
    func = getattr(inv, func_name)

    with pytest.raises(HTTPException) as exc_info:
        func(*args)

    _assert_generic(exc_info, context)


def test_no_str_e_left_in_step2_files():
    here = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("quotes/service.py", "invoices/service.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as fh:
            assert "str(e)" not in fh.read(), rel
