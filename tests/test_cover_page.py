import re

import pytest
from fastapi import HTTPException

import quotes  # noqa: F401  (import order: avoids a circular import via pdf)
from cover_page import service
from cover_page.defaults import DEFAULT_BODY, MAX_BODY_CHARS
from pdf import builder_cover
from pdf.utils import layout_utils


def _pages(pdf_bytes: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?!s)", pdf_bytes))


def _build(doc_type, **kw):
    items = [{"name": "Viga", "description": "", "quantity": 1, "unit_price": 100, "discount_type": None,
              "discount_value": 0, "unit": "u", "category": None, "total": 100}]
    args = dict(
        doc_type=doc_type, doc_id="Q-10001", doc_date="2026-10-17",
        client={"company_name": "ACME", "contact_name": "Ana", "address": "", "email": "", "phone": ""},
        project_name="P", notes="", items=items, charges={}, items_total=100, total_discounts=0,
        items_after_discount=100, supervision=0, supervision_pct=0, admin=0, admin_pct=0, insurance=0,
        insurance_pct=0, transport=0, transport_pct=0, contingency=0, contingency_pct=0,
        subtotal_general=100, itbis=18, grand_total=118, signer_name="Fabian",
    )
    args.update(kw)
    return bytes(layout_utils.build_quote_invoice_pdf(**args).getvalue())


def test_default_text_uses_approved_wording():
    assert "Gracias por confiar en Metpro." in DEFAULT_BODY["quote"]
    assert "{No_Cotizacion}" in DEFAULT_BODY["quote"]
    assert "{No_Factura}" in DEFAULT_BODY["invoice"]
    assert DEFAULT_BODY["invoice"].startswith("Estimado Cliente:")


def test_defaults_pass_validation():
    for t in ("quote", "invoice"):
        assert service.validate_body(t, DEFAULT_BODY[t]) == DEFAULT_BODY[t]


@pytest.mark.parametrize(
    "doc_type,body,code",
    [
        ("quote", "   ", "COVER_BODY_EMPTY"),
        ("quote", "x" * (MAX_BODY_CHARS + 1), "COVER_BODY_TOO_LONG"),
        ("quote", "Hola {Nombre}", "COVER_FIELD_UNKNOWN"),
        ("quote", "Factura {No_Factura}", "COVER_FIELD_UNKNOWN"),
        ("invoice", "Cotización {No_Cotizacion}", "COVER_FIELD_UNKNOWN"),
        ("otro", "x", "COVER_DOC_TYPE_INVALID"),
    ],
)
def test_validation_errors_are_spanish_and_coded(doc_type, body, code):
    with pytest.raises(HTTPException) as e:
        service.validate_body(doc_type, body)
    assert e.value.code == code
    assert e.value.status_code in (404, 422)


def test_render_replaces_known_and_keeps_unknown():
    out = service.render_text("Hola {Client} {Foo} {Date}", {"Client": "ACME", "Date": "01/01/2026"})
    assert out == "Hola ACME {Foo} 01/01/2026"


def test_cover_date_format():
    assert builder_cover.format_cover_date("2026-10-17") == "17/10/2026"
    assert builder_cover.format_cover_date("2026-10-17 08:00:00") == "17/10/2026"
    assert builder_cover.format_cover_date("") == ""


def test_pdf_has_cover_as_page_one(monkeypatch):
    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: DEFAULT_BODY[kind])
    with_cover = _build("COTIZACION")
    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: None)
    without = _build("COTIZACION")
    assert _pages(with_cover) == _pages(without) + 1


def test_disabled_cover_keeps_original_pdf(monkeypatch):
    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: None)
    assert _pages(_build("FACTURA", doc_id="F-10001")) == 1


def test_cover_failure_never_blocks_the_document(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("fail")

    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: DEFAULT_BODY[kind])
    monkeypatch.setattr("pdf.builder_cover.add_cover_page", boom)
    assert _pages(_build("COTIZACION")) >= 1


def test_invoice_uses_invoice_kind(monkeypatch):
    seen = []
    monkeypatch.setattr("cover_page.service.get_active_body", lambda kind: seen.append(kind) or None)
    _build("FACTURA", doc_id="F-10001")
    _build("COTIZACION")
    assert seen == ["invoice", "quote"]


def test_get_active_body_falls_back_when_db_fails(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(service, "get_db_connection", boom)
    assert service.get_active_body("quote") == DEFAULT_BODY["quote"]


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


def test_get_active_body_uses_row_and_respects_enabled(monkeypatch):
    monkeypatch.setattr(service, "get_db_connection", lambda: _Conn({"body": "Texto propio", "enabled": True}))
    assert service.get_active_body("quote") == "Texto propio"
    monkeypatch.setattr(service, "get_db_connection", lambda: _Conn({"body": "Texto propio", "enabled": False}))
    assert service.get_active_body("quote") is None
    monkeypatch.setattr(service, "get_db_connection", lambda: _Conn(None))
    assert service.get_active_body("invoice") == DEFAULT_BODY["invoice"]


def test_standalone_cover_pdf_is_one_page_and_handles_curly_quotes():
    out = builder_cover.create_cover_pdf("quote", "Estimado {Client}: “hola” — ok", "ACME", "Ana", "Fabian", "2026-10-17", "Q-1")
    assert _pages(out.getvalue()) == 1


def test_cover_routes_require_admin():
    from cover_page.router import router
    for r in router.routes:
        deps = " ".join(repr(d.call) for d in r.dependant.dependencies)
        assert "require_role" in deps or "dependency" in deps
