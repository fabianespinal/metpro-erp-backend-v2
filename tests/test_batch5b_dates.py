"""Debug pass 5b (E-03): every printed PDF date is dd/mm/aaaa."""
import os
import sys
from datetime import date, datetime

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402
from core.dates import fmt_day  # noqa: E402
from pdf.utils.layout_utils import build_quote_invoice_pdf  # noqa: E402


def test_fmt_day():
    assert fmt_day("2026-10-18") == "18/10/2026"
    assert fmt_day("2026-10-18T00:00:00+00:00") == "18/10/2026"
    assert fmt_day(date(2026, 10, 18)) == "18/10/2026"
    assert fmt_day(datetime(2026, 10, 18, 23, 0)) == "18/10/2026"
    assert fmt_day("18/10/2026") == "18/10/2026"  # already formatted: unchanged
    assert fmt_day(None) == "" and fmt_day("") == ""


def test_pdf_prints_doc_date_valid_until_and_payment_dates_as_ddmmyyyy():
    import zlib, re
    pdf = build_quote_invoice_pdf(
        doc_type="FACTURA", doc_id="F-1", doc_date="2026-10-17", client={"company_name": "C"},
        project_name="P", notes="", items=[], charges={}, items_total=0, total_discounts=0,
        items_after_discount=0, supervision=0, supervision_pct=10, admin=0, admin_pct=4, insurance=0,
        insurance_pct=1, transport=0, transport_pct=3, contingency=0, contingency_pct=3,
        subtotal_general=0, itbis=0, grand_total=0, payment_terms=None, valid_until="2026-11-30",
        amount_paid=10, amount_due=0, payments=[{"payment_date": date(2026, 10, 18), "method": "x", "amount": 10}],
    ).getvalue()
    text = b"".join(zlib.decompress(m) for m in re.findall(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S)
                    if m[:2] in (b"x\x9c", b"x\xda")).decode("latin-1")
    for d in ("17/10/2026", "30/11/2026", "18/10/2026"):
        assert d in text, d
    assert "2026-10-17" not in text and "2026-11-30" not in text
