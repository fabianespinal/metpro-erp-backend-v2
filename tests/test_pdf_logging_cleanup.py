"""PDF utilities: print() calls replaced by logger.error with unchanged message text."""
import importlib
import logging
import os
import sys

from fpdf import FPDF

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_font_load_failure_logs_error_not_stdout(monkeypatch, caplog, capsys):
    lu = importlib.import_module("pdf.utils.layout_utils")

    pdf = FPDF()
    pdf.add_page()

    def _bad_font(*args, **kwargs):
        raise RuntimeError("font file missing")

    monkeypatch.setattr(pdf, "add_font", _bad_font)

    with caplog.at_level(logging.ERROR):
        lu.add_footer_with_signature(pdf)

    messages = [r.getMessage() for r in caplog.records if r.name == lu.logger.name]
    assert "Font load failed: font file missing" in messages
    assert capsys.readouterr().out == ""


def test_conduce_logo_failure_logs_error_not_stdout(monkeypatch, caplog, capsys):
    bc = importlib.import_module("pdf.builder_conduce")

    monkeypatch.setattr(bc.os.path, "exists", lambda p: True)

    def _bad_image(self, *args, **kwargs):
        raise RuntimeError("corrupt logo")

    monkeypatch.setattr(FPDF, "image", _bad_image)

    with caplog.at_level(logging.ERROR):
        try:
            bc.create_conduce_pdf("D-1", "2026-10-14", {"company_name": "Acme"}, "Project", "", [])
        except Exception:
            # Document body may need more fixture data. The logo branch has already run.
            pass

    messages = [r.getMessage() for r in caplog.records if r.name == bc.logger.name]
    assert "Logo loading failed: corrupt logo" in messages
    assert capsys.readouterr().out == ""


def test_conduce_logo_not_found_logs_error(monkeypatch, caplog, capsys):
    bc = importlib.import_module("pdf.builder_conduce")

    monkeypatch.setattr(bc.os.path, "exists", lambda p: False)

    with caplog.at_level(logging.ERROR):
        try:
            create_conduce_pdf = bc.create_conduce_pdf
            create_conduce_pdf("D-1", "2026-10-14", {"company_name": "Acme"}, "Project", "", [])
        except Exception:
            # The rest of the document may need more fixture data; only the logo branch matters here.
            pass

    messages = [r.getMessage() for r in caplog.records if r.name == bc.logger.name]
    assert any(m.startswith("Logo not found at: ") for m in messages)
    assert "Logo not found" not in capsys.readouterr().out


def test_no_print_left_in_pdf_utilities():
    here = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("pdf/utils/layout_utils.py", "pdf/builder_conduce.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as fh:
            assert "print(" not in fh.read(), rel
