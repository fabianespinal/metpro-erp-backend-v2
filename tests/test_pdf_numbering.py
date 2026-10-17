"""Set 4, PDFs and numbering: quote_number everywhere, invoice PDFs from invoice_items."""
import importlib
import inspect
import os
import pathlib
import re
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import invoices.service as isvc  # noqa: E402
import quotes.service as qsvc  # noqa: E402

pdf_service = importlib.import_module("pdf.service")
qrouter = importlib.import_module("quotes.router")
irouter = importlib.import_module("invoices.router")


def _src(path):
    return (ROOT / path).read_text()


# ---------------- F1 / Q12: quote_number everywhere ----------------

def test_no_quote_pdf_prints_the_uuid():
    pat = re.compile(r"doc_id\s*=\s*quote\[\s*['\"]quote_id['\"]\s*\]")
    for f in ("pdf/service.py", "quotes/router.py"):
        assert not pat.search(_src(f)), f


def test_every_quote_pdf_uses_quote_number():
    assert "doc_id=quote_label_for(quote)" in _src("pdf/service.py")
    assert _src("quotes/router.py").count('doc_id=quote_label_for(quote)') == 3


def test_quote_email_shows_number():
    assert 'quote_id=str(quote["quote_number"])' in inspect.getsource(qrouter.send_quote)


def test_quote_list_selects_number():
    assert "q.quote_number" in inspect.getsource(qsvc.get_all_quotes)


# ---------------- P5: invoice line amounts ----------------

@pytest.mark.parametrize("dtype,value,expected", [
    ("percentage", 5, (2.0, 50.0, 5.0, 95.0)),
    ("fixed", 5, (2.0, 50.0, 5.0, 95.0)),
    ("none", 5, (2.0, 50.0, 0.0, 100.0)),
    ("percentage", 0, (2.0, 50.0, 0.0, 100.0)),
])
def test_invoice_line_amounts(dtype, value, expected):
    item = {"quantity": 2, "unit_price": 50, "discount_type": dtype, "discount_value": value}
    assert qsvc._invoice_line_amounts(item) == expected


# ---------------- F2: invoice PDFs from invoice_items + billed total ----------------

class Cur:
    def __init__(self, item_rows, quote_rows=()):
        self.item_rows, self.quote_rows, self.sql = item_rows, list(quote_rows), []
        self._last = None

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))
        self._last = "items" if "FROM invoice_items" in sql else "quote"

    def fetchall(self):
        return self.item_rows if self._last == "items" else self.quote_rows


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def close(self):
        pass


def test_lines_from_invoice_items_and_billed_total(monkeypatch):
    cur = Cur([{"description": "IPE 200", "quantity": 2, "unit_price": 50, "discount": 5, "total": 95, "product_id": 1}])
    monkeypatch.setattr(isvc, "get_db_connection", lambda: Conn(cur))
    items, totals = isvc.invoice_lines_and_totals({"id": 9, "quote_id": "q", "total_amount": 112.10}, {})
    assert items[0]["product_name"] == "IPE 200" and items[0]["discount_type"] == "fixed"
    assert totals["items_after_discount"] == 95
    assert totals["grand_total"] == 112.10  # billed amount, ITBIS 18% on 95 = 112.10
    assert totals["lines_source"] == "invoice_items"
    assert "ORDER BY ctid" in cur.sql[0]
    assert not any("quote_items" in s for s in cur.sql)


def test_legacy_invoice_falls_back_to_quote_items(monkeypatch):
    cur = Cur([], [{"product_name": "X", "quantity": 1, "unit_price": 100, "discount_type": "none", "discount_value": 0}])
    monkeypatch.setattr(isvc, "get_db_connection", lambda: Conn(cur))
    items, totals = isvc.invoice_lines_and_totals({"id": 9, "quote_id": "q", "total_amount": 118}, {})
    assert totals["lines_source"] == "quote_items" and items[0]["product_name"] == "X"


def test_mismatch_is_logged_and_billed_total_wins(monkeypatch, caplog):
    cur = Cur([{"description": "X", "quantity": 1, "unit_price": 100, "discount": 0, "total": 100, "product_id": None}])
    monkeypatch.setattr(isvc, "get_db_connection", lambda: Conn(cur))
    with caplog.at_level("WARNING", logger="metpro.invoices"):
        _, totals = isvc.invoice_lines_and_totals({"id": 9, "quote_id": "q", "total_amount": 500}, {})
    assert totals["grand_total"] == 500
    assert "differs" in caplog.text


@pytest.mark.parametrize("fn", ["generate_invoice_pdf", "generate_conduce_pdf"])
def test_pdf_service_invoice_paths_use_helper(fn):
    src = inspect.getsource(getattr(pdf_service, fn))
    assert "invoice_lines_and_totals" in src
    assert "FROM quote_items" not in src


@pytest.mark.parametrize("fn", ["send_invoice", "_render_public_invoice_pdf"])
def test_invoice_router_paths_use_helper(fn):
    src = inspect.getsource(getattr(irouter, fn))
    assert "invoice_lines_and_totals" in src
    assert "calculate_invoice_totals(items" not in src
