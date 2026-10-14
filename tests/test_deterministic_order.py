"""
Regression guard: every SELECT from quote_items or invoice_items must order by id.

Covers the paths the Tier 1 scope names:
- quote and invoice item reads in quotes/service.py and invoices/service.py
- PDF queries in pdf/service.py (quote, invoice, conduce)
- public view queries (they call the same service functions)

Static check on source text. Runs without a database.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_DIRS = ["quotes", "invoices", "pdf"]

# A SELECT that reads from quote_items or invoice_items, up to the end of its SQL string literal.
ITEM_SELECT = re.compile(
    r"SELECT\b(?:(?!\bDELETE\b).)*?\bFROM\s+(quote_items|invoice_items)\b([^\"']*)",
    re.DOTALL,
)


def _python_sources():
    for d in SOURCE_DIRS:
        for path in sorted((ROOT / d).rglob("*.py")):
            yield path


def _item_selects():
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        for m in ITEM_SELECT.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            yield path.relative_to(ROOT), line, m.group(1), m.group(2)


def test_item_reads_exist():
    # Guard against the regex silently matching nothing.
    found = list(_item_selects())
    assert len(found) >= 10, f"expected many item reads, found {len(found)}"


def test_every_item_select_orders_by_id():
    violations = [
        f"{path}:{line} SELECT FROM {table} has no ORDER BY id"
        for path, line, table, tail in _item_selects()
        if not re.search(r"ORDER\s+BY\s+id\b", tail)
    ]
    assert not violations, "\n".join(violations)


def test_pdf_item_reads_are_ordered():
    pdf_reads = [
        (path, table, tail)
        for path, _line, table, tail in _item_selects()
        if path.parts[0] == "pdf"
    ]
    assert pdf_reads, "expected item reads in pdf/service.py"
    for path, table, tail in pdf_reads:
        assert re.search(r"ORDER\s+BY\s+id\b", tail), f"{path} {table} unordered"


def test_public_quote_read_is_ordered():
    # Public quote view reads items through get_quote_with_contact.
    text = (ROOT / "quotes" / "service.py").read_text(encoding="utf-8")
    body = text[text.index("def get_quote_with_contact"):]
    body = body[: body.index("\ndef ")]
    assert "FROM quote_items WHERE quote_id = %s ORDER BY id" in body
