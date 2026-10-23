"""PDF update M2: project heading, MEDIDAS column and the print_items checkbox on quote and invoice PDFs.

Old documents (no units, checkbox on, switches off) must render byte-identical to before this change.
"""
import importlib
import os
import re
import sys
import zlib

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core.public_payload import public_payload  # noqa: E402
from main import app  # noqa: E402
import pdf.utils.layout_utils as layout  # noqa: E402

client = TestClient(app)
NO_CHARGES = {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}
ITEMS = [
    {"product_name": "Viga W10x12 largo", "quantity": 2, "unit_price": 500.0, "category": "Estructura"},
    {"product_name": "Tornillo", "quantity": 10, "unit_price": 5.0},
]
PROJECT = "Nave industrial en Santiago, proyecto de prueba con nombre largo"
# sha256 of the PDF built by the code before this change (main b745b09 / M1), CreationDate and /ID removed.
GOLDEN_OLD_PDF = "5c453ec1c69133f37d3f980cd1ef602268f9b65c7f79437d4686ac7ea107999e"


@pytest.fixture(autouse=True)
def _no_db_pages(monkeypatch):
    """The cover and terms pages read the database; fail them the same way everywhere so the bytes are stable."""
    def boom():
        raise RuntimeError("no db in this test")
    for mod in ("cover_page.service", "terms_page.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", boom, raising=False)
    for name in ("PDF_MEDIDAS_ENABLED", "PDF_PRINT_ITEMS_ENABLED", "PDF_PROJECT_DESC_ENABLED"):
        monkeypatch.delenv(name, raising=False)


def build(**kw):
    args = dict(
        doc_type="COTIZACION", doc_id="Q-1", doc_date="23/10/2026", client={"company_name": "Cliente"},
        project_name=PROJECT, notes="n", items=[dict(i) for i in ITEMS], charges={}, items_total=1050.0,
        total_discounts=0, items_after_discount=1050.0, supervision=0, supervision_pct=10, admin=0, admin_pct=4,
        insurance=0, insurance_pct=1, transport=0, transport_pct=3, contingency=0, contingency_pct=3,
        subtotal_general=1050.0, itbis=189.0, grand_total=1239.0,
    )
    args.update(kw)
    return layout.build_quote_invoice_pdf(**args).getvalue()


def text(pdf_bytes: bytes) -> str:
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except Exception:
            pass
    return "\n".join(out)


def normalized(b: bytes) -> bytes:
    b = re.sub(rb"/CreationDate ?\(.*?\)", b"", b)
    return re.sub(rb"/ID \[<[0-9A-F]+><[0-9A-F]+>\]", b"", b)


def test_old_documents_are_byte_identical():
    import hashlib
    assert hashlib.sha256(normalized(build())).hexdigest() == GOLDEN_OLD_PDF


def test_switches_off_ignore_units_heading_and_stay_identical(monkeypatch):
    base = normalized(build())
    with_units = [dict(i, unit_of_measure="Ft") for i in ITEMS]
    assert normalized(build(items=with_units)) == base          # Medidas switch off: no column
    assert normalized(build(print_items=True)) == base


def test_heading_moves_out_of_the_header_and_prints_in_full(monkeypatch):
    monkeypatch.setenv("PDF_PROJECT_DESC_ENABLED", "true")
    t = text(build())
    assert "Proyecto desc.: " in t and "Proyecto:" not in t
    assert t.count("Proyecto desc.") == 1
    assert "largo" in t  # the whole name, no 60-character cut


def test_heading_wraps_a_very_long_name(monkeypatch):
    monkeypatch.setenv("PDF_PROJECT_DESC_ENABLED", "true")
    long_name = "Proyecto " + " ".join(f"palabra{i}" for i in range(60))
    t = text(build(project_name=long_name))
    assert "palabra59" in t


def test_medidas_column_prints_only_with_the_switch_and_a_unit(monkeypatch):
    units = [dict(ITEMS[0], unit_of_measure="Ft"), dict(ITEMS[1])]
    assert "MEDIDAS" not in text(build(items=units))           # switch off
    monkeypatch.setenv("PDF_MEDIDAS_ENABLED", "true")
    t = text(build(items=units))
    assert "MEDIDAS" in t and "(Ft)" in t
    assert "MEDIDAS" not in text(build(items=[dict(i) for i in ITEMS]))  # no line has a unit
    assert "MEDIDAS" not in text(build(items=[dict(i, unit_of_measure="  ") for i in ITEMS]))


def test_hidden_lines_do_not_decide_the_column(monkeypatch):
    monkeypatch.setenv("PDF_MEDIDAS_ENABLED", "true")
    items = [dict(ITEMS[0], print_on_pdf=False, unit_of_measure="Ft"), dict(ITEMS[1])]
    assert "MEDIDAS" not in text(build(items=items))


def test_print_items_false_removes_the_table_but_keeps_heading_and_totals(monkeypatch):
    monkeypatch.setenv("PDF_PROJECT_DESC_ENABLED", "true")
    t = text(build(print_items=False))
    assert "Viga" not in t and "Tornillo" not in t and "Detalle de Items" not in t and "DESCRIP" not in t
    assert "Proyecto desc.: " in t and "Resumen Financiero" in t and "1,239.00" in t and "1,050.00" in t


def test_print_items_false_works_even_if_its_switch_is_off(monkeypatch):
    # The switch gates setting the checkbox, never honouring it (same rule as A3 hidden lines).
    t = text(build(print_items=False))
    assert "Viga" not in t and "1,239.00" in t


def test_the_checkbox_does_not_change_any_total():
    on, off = text(build()), text(build(print_items=False))
    for figure in ("1,050.00", "189.00", "1,239.00"):
        assert figure in on and figure in off


def test_public_payload_checkbox_off_ships_no_items_but_full_totals():
    doc = {"quote_id": "x", "print_items": False, "items": [{"product_name": "Viga", "unit_price": 500}], "project_name": "P"}
    out = public_payload(doc, lambda: {"grand_total": 1239.0})
    assert out["items"] == [] and out["display_totals"] == {"grand_total": 1239.0} and out["print_items"] is False


def test_public_payload_unchanged_when_checkbox_on():
    doc = {"quote_id": "x", "print_items": True, "items": [{"product_name": "Viga", "unit_price": 500, "print_on_pdf": True}], "project_name": "P"}
    out = public_payload(doc, lambda: {"grand_total": 1.0})
    assert out == {"items": [{"product_name": "Viga", "unit_price": 500}], "project_name": "P"}


# ---------------- integration: every route ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


def _hdr():
    token = create_access_token({"sub": "t_user", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "invoices.router", "pdf.service", "products.service",
                "projects.service", "reports.service", "tax.service", "quotes.router"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    for name in ("PDF_MEDIDAS_ENABLED", "PDF_PRINT_ITEMS_ENABLED", "PDF_PROJECT_DESC_ENABLED"):
        monkeypatch.setenv(name, "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "('00000000-0000-0000-0000-000000000001', 't_user', 'x', 't_user@test.local', 'user', true) "
                "ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO clients (company_name, tax_id) VALUES ('Cliente M2', '1-31-00001-1') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"cid": cid, "ctid": ctid, "connect": connect}


def _rows(db, sql, params=()):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


@needs_db
@pytest.mark.parametrize("print_items", [True, False])
def test_every_quote_and_invoice_route_follows_the_checkbox(db, print_items):
    body = {"client_id": db["cid"], "contact_id": db["ctid"], "project_name": "Torre Norte", "included_charges": NO_CHARGES,
            "print_items": print_items,
            "items": [{"product_name": "Viga unica", "quantity": 2, "unit_price": 500.0, "unit_of_measure": "Ft"}]}
    qid = client.post("/quotes/", json=body, headers=_hdr()).json()["data"]["quote_id"]
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    token = _rows(db, "SELECT public_token FROM quotes WHERE quote_id = %s", (qid,))[0]["public_token"]

    def check(resp):
        assert resp.status_code == 200, resp.text
        t = text(resp.content)
        assert "Torre Norte" in t and "Resumen Financiero" in t
        assert ("Viga unica" in t) is print_items
        assert ("MEDIDAS" in t) is print_items

    check(client.get(f"/quotes/{qid}/pdf", headers=_hdr()))
    check(client.get(f"/pdf/quotes/{qid}", headers=_hdr()))
    check(client.get(f"/quotes/public/{token}/pdf"))
    pub = client.get(f"/quotes/public/{token}").json()["data"]
    assert (len(pub["items"]) == 1) is print_items

    assert client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr()).status_code == 200
    iid = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()).json()["data"]["invoice_id"]
    check(client.get(f"/pdf/invoices/{iid}", headers=_hdr()))
    itoken = _rows(db, "SELECT public_token FROM invoices WHERE id = %s", (iid,))[0]["public_token"]
    check(client.get(f"/invoices/public/{itoken}/pdf"))
    ipub = client.get(f"/invoices/public/{itoken}").json()["data"]
    assert (len(ipub["items"]) == 1) is print_items
