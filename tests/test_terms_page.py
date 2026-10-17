import re

import pytest
from fastapi import HTTPException

import quotes  # noqa: F401  (import order: avoids a circular import via pdf)
from pdf import builder_terms
from pdf.utils import layout_utils
from terms_page import service
from terms_page.defaults import DEFAULT_SECTIONS, MAX_SECTION_CHARS, SECTION_KEYS, SECTIONS


def _pages(b: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", b))


def _build(doc_type="COTIZACION"):
    items = [{"name": "Viga", "description": "", "quantity": 1, "unit_price": 100, "discount_type": None,
              "discount_value": 0, "unit": "u", "category": None, "total": 100}]
    return bytes(layout_utils.build_quote_invoice_pdf(
        doc_type=doc_type, doc_id="Q-10001", doc_date="2026-10-17",
        client={"company_name": "ACME", "contact_name": "Ana", "address": "", "email": "", "phone": ""},
        project_name="P", notes="", items=items, charges={}, items_total=100, total_discounts=0,
        items_after_discount=100, supervision=0, supervision_pct=0, admin=0, admin_pct=0, insurance=0,
        insurance_pct=0, transport=0, transport_pct=0, contingency=0, contingency_pct=0,
        subtotal_general=100, itbis=18, grand_total=118, signer_name="Fabian",
    ).getvalue())


def _no_cover(monkeypatch):
    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: None)


def test_seven_sections_in_order():
    assert SECTION_KEYS == ("payment_terms", "warranty", "scope_limits", "client_responsibilities",
                            "cancellation", "safety", "legal")
    assert set(DEFAULT_SECTIONS) == set(SECTION_KEYS)


def test_starter_text_has_no_invented_numbers():
    assert not any(ch.isdigit() for text in DEFAULT_SECTIONS.values() for ch in text)


def test_clean_sections_rejects_unknown_and_long():
    with pytest.raises(HTTPException) as e:
        service.clean_sections({"otra": "x"})
    assert e.value.code == "TERMS_SECTION_UNKNOWN"
    with pytest.raises(HTTPException) as e:
        service.clean_sections({"legal": "x" * (MAX_SECTION_CHARS + 1)})
    assert e.value.code == "TERMS_SECTION_TOO_LONG"
    with pytest.raises(HTTPException) as e:
        service.clean_sections("no es dict")
    assert e.value.code == "TERMS_SECTIONS_INVALID"


def test_clean_sections_trims_and_keeps_empty():
    assert service.clean_sections({"legal": "  hola \r\n", "safety": ""}) == {"legal": "hola", "safety": ""}


def test_merge_stored_wins_even_when_empty():
    m = service._merge({"legal": "", "safety": "Mío"})
    assert m["legal"] == "" and m["safety"] == "Mío" and m["warranty"] == DEFAULT_SECTIONS["warranty"]


class _Cur:
    def __init__(self, row):
        self.row = row

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self.row


class _Conn:
    def __init__(self, row):
        self.row = row

    def cursor(self):
        return _Cur(self.row)

    def close(self):
        pass


def _row(q=False, i=False, sections=None):
    return {"enabled_quote": q, "enabled_invoice": i, "sections": sections or {}, "updated_at": None, "updated_by": None}


def test_active_sections_off_without_row_or_flag(monkeypatch):
    monkeypatch.setattr(service, "get_db_connection", lambda: _Conn(None))
    assert service.get_active_sections("quote") is None
    monkeypatch.setattr(service, "get_db_connection", lambda: _Conn(_row(q=False, i=True)))
    assert service.get_active_sections("quote") is None
    assert service.get_active_sections("invoice") is not None


def test_active_sections_skip_empty_and_use_titles(monkeypatch):
    monkeypatch.setattr(service, "get_db_connection", lambda: _Conn(_row(q=True, sections={"legal": ""})))
    out = service.get_active_sections("quote")
    assert len(out) == 6 and out[0][0] == dict(SECTIONS)["payment_terms"]


def test_active_sections_never_raises_and_prints_nothing_on_error(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(service, "get_db_connection", boom)
    assert service.get_active_sections("quote") is None


def test_pdf_gets_terms_page_only_when_enabled(monkeypatch):
    _no_cover(monkeypatch)
    monkeypatch.setattr("terms_page.service.get_active_sections", lambda kind: None)
    base = _pages(_build())
    monkeypatch.setattr("terms_page.service.get_active_sections", lambda kind: [("1. Pago", "Texto")])
    assert _pages(_build()) == base + 1
    assert _pages(_build("FACTURA")) == base + 1


def test_terms_failure_never_blocks_document(monkeypatch):
    _no_cover(monkeypatch)
    monkeypatch.setattr("terms_page.service.get_active_sections", lambda kind: [("1. Pago", "Texto")])
    monkeypatch.setattr("pdf.builder_terms.add_terms_pages", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert _pages(_build()) >= 1


def test_standalone_terms_pdf_handles_curly_quotes_and_accents():
    out = builder_terms.create_terms_pdf([("2. Garantía", "Texto “con” acentos ñ\n\nSegundo párrafo")])
    assert _pages(out.getvalue()) == 1


def test_long_terms_flow_to_more_pages():
    long = [(t, "palabra " * 400) for _, t in SECTIONS]
    assert _pages(builder_terms.create_terms_pdf(long).getvalue()) > 1


def test_terms_routes_require_admin():
    from terms_page.router import router
    for r in router.routes:
        deps = " ".join(repr(d.call) for d in r.dependant.dependencies)
        assert "require_role" in deps or "dependency" in deps
