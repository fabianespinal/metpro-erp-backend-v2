"""Numbering chain Q-/F-/C-, signer name from the logged-in user, category headings, Cargos Indirectos."""
import io
import os
import pathlib
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from core.numbering import (  # noqa: E402
    conduce_label, conduce_label_from_invoice_number, invoice_label, quote_label,
)
from pdf.utils import layout_utils as lu  # noqa: E402
from pdf.builder_conduce import create_conduce_pdf  # noqa: E402
import pdf.utils.signer as signer  # noqa: E402


def test_chain_shares_one_suffix():
    assert (quote_label(10002), invoice_label(10002), conduce_label(10002)) == ("Q-10002", "F-10002", "C-10002")


def test_conduce_label_from_invoice_number():
    assert conduce_label_from_invoice_number("F-10002") == "C-10002"
    assert conduce_label_from_invoice_number("INV-2026") == "CD-2026"


class _Pdf:
    """Records text drawn so layout can be asserted without parsing a PDF."""
    def __init__(self):
        self.texts = []
    def __getattr__(self, name):
        def f(*a, **k):
            if name == "cell" and len(a) >= 3:
                self.texts.append(str(a[2]))
            return 0
        return f
    def get_y(self):
        return 10


def test_signature_uses_given_name_and_never_hardcoded():
    pdf = _Pdf()
    lu.add_footer_with_signature(pdf, "Ana Perez")
    assert "Ana Perez" in pdf.texts and "Karmary Mata" not in pdf.texts
    pdf = _Pdf()
    lu.add_footer_with_signature(pdf, None)
    assert "Karmary Mata" not in pdf.texts


def test_category_headings_group_and_other():
    pdf = _Pdf()
    cur = None
    for cat in ["Acero", "Acero", "Pintura", None]:
        cur = lu._category_heading(pdf, {"category": cat}, cur, 190)
    assert [t for t in pdf.texts] == ["Acero", "Pintura", "Otros"]


def test_no_categories_no_headings():
    pdf = _Pdf()
    cur = None
    for _ in range(3):
        cur = lu._category_heading(pdf, {"category": None}, cur, 190)
    assert pdf.texts == []


def _quote_pdf(charges, items, signer_name="Ana Perez"):
    return lu.build_quote_invoice_pdf(
        doc_type="COTIZACION", doc_id="Q-10002", doc_date="2026-10-17",
        client={"company_name": "ACME"}, project_name="P", notes=None, items=items, charges=charges,
        items_total=100, total_discounts=0, items_after_discount=100,
        supervision=10, supervision_pct=10, admin=0, admin_pct=4, insurance=0, insurance_pct=1,
        transport=0, transport_pct=3, contingency=0, contingency_pct=3,
        subtotal_general=110, itbis=19.8, grand_total=129.8, signer_name=signer_name,
    )


def test_full_quote_pdf_renders_with_categories_and_cargos():
    items = [{"product_name": "Viga", "quantity": 1, "unit_price": 100, "category": "Acero"}]
    out = _quote_pdf({"supervision": True}, items)
    data = out.getvalue() if hasattr(out, "getvalue") else bytes(out)
    assert data.startswith(b"%PDF")


def test_conduce_renders_with_categories_and_name():
    out = create_conduce_pdf("C-10002", "2026-10-17", {"company_name": "ACME"}, "P", None,
                             [{"product_name": "Viga", "quantity": 2, "category": "Acero"}], signer_name="Ana Perez")
    assert out.getvalue().startswith(b"%PDF")


def test_signer_prefers_db_full_name(monkeypatch):
    class Cur:
        def execute(self, *a): pass
        def fetchone(self): return {"full_name": "Maria Lopez"}
    class Conn:
        def cursor(self): return Cur()
        def close(self): pass
    monkeypatch.setattr(signer, "get_db_connection", lambda: Conn())
    assert signer.resolve_signer_name({"sub": "mlopez", "name": "Old"}, "Creator") == "Maria Lopez"


def test_signer_falls_back_to_claim_then_creator(monkeypatch):
    class Cur:
        def execute(self, *a): pass
        def fetchone(self): return None
    class Conn:
        def cursor(self): return Cur()
        def close(self): pass
    monkeypatch.setattr(signer, "get_db_connection", lambda: Conn())
    assert signer.resolve_signer_name({"sub": "u", "name": "Claim Name"}) == "Claim Name"
    assert signer.resolve_signer_name(None, "Creator Name") == "Creator Name"
    assert signer.resolve_signer_name(None, None) is None


def test_quote_label_for_falls_back_to_row_id():
    from core.numbering import quote_label_for
    assert quote_label_for({"quote_number": 10002, "id": 9}) == "Q-10002"
    assert quote_label_for({"quote_number": None, "id": 9}) == "Q-9"
    assert quote_label_for({}) == "Q-S/N"
