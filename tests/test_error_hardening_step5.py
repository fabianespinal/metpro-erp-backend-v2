"""Step 5: reports and PDF handlers return generic detail; print/traceback replaced by logging."""
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


@pytest.mark.parametrize("func_name, args, context", [
    ("generate_quote_pdf", ("Q-1",), "Quote PDF generation failed"),
    ("generate_invoice_pdf", (1,), "Invoice PDF generation failed"),
    ("generate_conduce_pdf", (1,), "Conduce generation failed"),
])
def test_pdf_handlers_return_generic_detail(monkeypatch, capsys, func_name, args, context):
    ps = importlib.import_module("pdf.service")
    monkeypatch.setattr(ps, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        getattr(ps, func_name)(*args)

    _assert_generic(exc_info, context)
    captured = capsys.readouterr()
    assert SECRET_TEXT not in captured.out
    assert SECRET_TEXT not in captured.err
    assert "GENERATION ERROR" not in captured.out


def test_pdf_handler_logs_id_and_traceback(monkeypatch, caplog):
    ps = importlib.import_module("pdf.service")
    monkeypatch.setattr(ps, "get_db_connection", _broken_db)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(HTTPException):
            ps.generate_invoice_pdf(42)

    # Invoice id is logged by the PDF module (no traceback, no client exposure).
    id_records = [r for r in caplog.records if r.name == "metpro.pdf"]
    assert [r.getMessage() for r in id_records] == ["PDF generation failed for invoice 42"]
    assert all(r.exc_info is None for r in id_records)

    # Full traceback is logged once by the shared helper.
    tb_records = [r for r in caplog.records if r.name == "metpro.errors" and r.exc_info]
    assert len(tb_records) == 1
    assert str(tb_records[0].exc_info[1]) == SECRET_TEXT


def test_revenue_report_returns_generic_detail(monkeypatch):
    rs = importlib.import_module("reports.service")
    monkeypatch.setattr(rs, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        rs.get_revenue_report(None, None, None)

    _assert_generic(exc_info, "Revenue report failed")


def test_no_str_e_or_print_left_in_step5_files():
    here = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("pdf/service.py", "reports/service.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as fh:
            src = fh.read()
        assert "str(e)" not in src, rel
        assert "print(" not in src, rel
        assert "traceback" not in src, rel
