"""A3 Visibility controls: print_on_pdf = false lines stay in totals and internal screens, never reach customers.

Unit tests run everywhere. Integration tests need Postgres with the production schema plus
2026-10-22_print_on_pdf (METPRO_LEDGER_TEST_DB); skipped otherwise.
"""
import importlib
import os
import re
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core.visibility import customer_items, has_hidden, is_printable, print_controls_enabled  # noqa: E402
from main import app  # noqa: E402
from quotes.service import calculate_quote_totals  # noqa: E402

client = TestClient(app)
NO_CHARGES = {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}
SHOWN = {"product_name": "Viga visible", "quantity": 2, "unit_price": 500.0, "discount_type": "none", "discount_value": 0,
         "print_on_pdf": True}
HIDDEN = {"product_name": "Costo indirecto secreto", "quantity": 1, "unit_price": 300.0, "discount_type": "none",
          "discount_value": 0, "print_on_pdf": False}


def _hdr(role="user"):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


def _sql(name):
    lines = open(os.path.join(ROOT, "migrations", name), encoding="utf-8").read().splitlines()
    return "\n".join(l.split("--")[0] for l in lines).upper()


# ---------------- helper ----------------

def test_only_a_literal_false_hides():
    assert is_printable({}) and is_printable({"print_on_pdf": True}) and is_printable({"print_on_pdf": None})
    assert not is_printable({"print_on_pdf": False})
    assert customer_items([SHOWN, HIDDEN]) == [SHOWN] and has_hidden([SHOWN, HIDDEN]) and not has_hidden([SHOWN])


@pytest.mark.parametrize("value,expected", [(None, False), ("true", True), ("1", True), ("false", False), ("", False)])
def test_toggle_values(monkeypatch, value, expected):
    if value is None:
        monkeypatch.delenv("PRINT_CONTROLS_ENABLED", raising=False)
    else:
        monkeypatch.setenv("PRINT_CONTROLS_ENABLED", value)
    assert print_controls_enabled() is expected


# ---------------- migration ----------------

def test_migration_is_additive_with_a_visible_default():
    sql = re.sub(r"\s+", " ", _sql("2026-10-22_print_on_pdf.sql"))
    for forbidden in ("DROP ", "DELETE FROM", "UPDATE ", "TRUNCATE", "RENAME"):
        assert forbidden not in sql
    assert sql.count("ADD COLUMN IF NOT EXISTS PRINT_ON_PDF BOOLEAN NOT NULL DEFAULT TRUE") == 3
    for table in ("TEMPLATE_PACK_ITEMS", "QUOTE_ITEMS", "INVOICE_ITEMS"):
        assert f"PUBLIC.{table} ADD COLUMN" in sql


def test_rollback_refuses_while_lines_are_hidden():
    sql = _sql("2026-10-22_print_on_pdf.rollback.sql")
    assert sql.count("WHERE PRINT_ON_PDF = FALSE") == 3
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN")


# ---------------- PDFs ----------------

def _capture_text(monkeypatch):
    from fpdf import FPDF
    texts = []
    real = FPDF.cell

    def spy(self, *a, **k):
        t = k.get("txt") or k.get("text") or (a[2] if len(a) > 2 else "")
        texts.append(str(t))
        return real(self, *a, **k)

    monkeypatch.setattr(FPDF, "cell", spy)
    return texts


def _pdf_kwargs(items):
    t = calculate_quote_totals(items, NO_CHARGES, 0.18)  # totals from ALL lines, as every caller does
    return t, dict(
        doc_id="X-1", doc_date="2026-10-22",
        client={"company_name": "X", "address": "", "tax_id": "", "contact_name": "", "email": "", "phone": ""},
        project_name="P", notes="", items=items, charges=NO_CHARGES,
        items_total=t["items_total"], total_discounts=0, items_after_discount=t["items_after_discount"],
        supervision=0, supervision_pct=10, admin=0, admin_pct=4, insurance=0, insurance_pct=1,
        transport=0, transport_pct=3, contingency=0, contingency_pct=3,
        subtotal_general=t["subtotal_general"], itbis=t["itbis"], grand_total=t["grand_total"], tax_label="ITBIS (18%)",
    )


@pytest.mark.parametrize("kind", ["quote", "invoice"])
def test_pdf_omits_hidden_lines_but_prints_the_full_totals(monkeypatch, kind):
    from pdf.builder_invoice import create_invoice_pdf
    from pdf.builder_quote import create_quote_pdf
    texts = _capture_text(monkeypatch)
    t, kw = _pdf_kwargs([SHOWN, HIDDEN])
    if kind == "quote":
        create_quote_pdf(doc_type="COTIZACION", **kw)
    else:
        create_invoice_pdf(doc_type="FACTURA", **kw)
    joined = "\n".join(texts)
    assert "Viga visible" in joined
    assert "Costo indirecto secreto" not in joined and "$300.00" not in joined  # name and its amount
    assert f"${t['items_total']:,.2f}" in joined and f"${t['grand_total']:,.2f}" in joined  # 1,300 / 1,534: hide only


def test_hidden_category_prints_no_heading(monkeypatch):
    from pdf.builder_quote import create_quote_pdf
    texts = _capture_text(monkeypatch)
    _, kw = _pdf_kwargs([dict(SHOWN, category="Visible cat"), dict(HIDDEN, category="Solo oculta")])
    create_quote_pdf(doc_type="COTIZACION", **kw)
    joined = "\n".join(texts).upper()
    assert "VISIBLE CAT" in joined and "SOLO OCULTA" not in joined


def test_conduce_omits_hidden_lines(monkeypatch):
    from pdf.builder_conduce import create_conduce_pdf
    texts = _capture_text(monkeypatch)
    create_conduce_pdf("C-1", "2026-10-22", {"company_name": "X"}, "P", "", [SHOWN, HIDDEN])
    joined = "\n".join(texts)
    assert "Viga visible" in joined and "Costo indirecto secreto" not in joined


def test_every_customer_builder_filters_through_the_one_helper():
    import inspect
    from pdf.builder_conduce import create_conduce_pdf
    from pdf.utils import layout_utils
    assert "customer_items(items)" in inspect.getsource(layout_utils.build_quote_invoice_pdf)
    assert "customer_items(items)" in inspect.getsource(create_conduce_pdf)


# ---------------- public payload ----------------

def test_public_payload_removes_hidden_lines_and_ships_full_totals():
    from core.public_payload import public_payload
    doc = {"id": 1, "items": [dict(SHOWN, id=1, product_id=None), dict(HIDDEN, id=2, product_id=None)], "grand_total": 1534.0}
    out = public_payload(doc, lambda: {"grand_total": 1534.0, "items_total": 1300.0})
    assert [i["product_name"] for i in out["items"]] == ["Viga visible"]
    assert out["display_totals"]["items_total"] == 1300.0
    assert "print_on_pdf" not in out["items"][0] and "Costo indirecto secreto" not in str(out)


def test_public_payload_is_unchanged_when_nothing_is_hidden():
    from core.public_payload import public_payload
    doc = {"id": 1, "items": [dict(SHOWN, id=1, product_id=None)]}
    out = public_payload(doc, lambda: pytest.fail("totals must not be computed when nothing is hidden"))
    assert "display_totals" not in out and len(out["items"]) == 1


# ---------------- integration ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "invoices.router", "pdf.service",
                "projects.service", "reports.service", "tax.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("PRINT_CONTROLS_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "('00000000-0000-0000-0000-000000000001', 't_user', 'x', 't_user@test.local', 'user', true) "
                "ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO clients (company_name, tax_id) VALUES ('Cliente A3', '1-31-00001-1') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"cid": cid, "ctid": ctid, "connect": connect}


def _quote(db, items, **over):
    body = {"client_id": db["cid"], "contact_id": db["ctid"], "project_name": "A3", "items": items,
            "included_charges": NO_CHARGES}
    body.update(over)
    return client.post("/quotes/", json=body, headers=_hdr())


def _rows(db, sql, params=()):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def _to_invoice(db, qid):
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())  # no-op when the test already finalized
    assert client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr()).status_code == 200
    r = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()["data"]["invoice_id"]


@needs_db
def test_hidden_line_is_stored_counted_and_visible_internally(db):
    r = _quote(db, [SHOWN, HIDDEN])
    assert r.status_code == 200, r.text
    qid = r.json()["data"]["quote_id"]
    assert float(_rows(db, "SELECT subtotal FROM quotes WHERE quote_id = %s", (qid,))[0]["subtotal"]) == 1300.0  # counted
    flags = {x["product_name"]: x["print_on_pdf"] for x in _rows(db, "SELECT * FROM quote_items WHERE quote_id = %s", (qid,))}
    assert flags == {"Viga visible": True, "Costo indirecto secreto": False}
    internal = client.get(f"/quotes/{qid}", headers=_hdr()).json()["data"]
    assert {i["product_name"] for i in internal["items"]} == {"Viga visible", "Costo indirecto secreto"}  # internal sees all


@needs_db
def test_existing_style_payload_without_the_flag_prints(db):
    item = {k: v for k, v in SHOWN.items() if k != "print_on_pdf"}
    qid = _quote(db, [item]).json()["data"]["quote_id"]
    assert _rows(db, "SELECT print_on_pdf FROM quote_items WHERE quote_id = %s", (qid,))[0]["print_on_pdf"] is True


@needs_db
def test_hiding_needs_the_switch_but_existing_hidden_quotes_stay_editable(db, monkeypatch):
    qid = _quote(db, [SHOWN, HIDDEN]).json()["data"]["quote_id"]
    monkeypatch.setenv("PRINT_CONTROLS_ENABLED", "false")
    # Create carries lines hidden by a pack or a duplicate, so it is not gated.
    assert _quote(db, [SHOWN, HIDDEN]).status_code == 200
    # Editing the quote that already hides one line is fine while the switch is off ...
    ok = client.put(f"/quotes/{qid}", json={"items": [dict(SHOWN, quantity=3), HIDDEN]}, headers=_hdr())
    assert ok.status_code == 200, ok.text
    # ... hiding one more is not.
    bad = client.put(f"/quotes/{qid}", json={"items": [dict(SHOWN, print_on_pdf=False), HIDDEN]}, headers=_hdr())
    assert bad.status_code == 400 and bad.json()["code"] == "PRINT_CONTROLS_DISABLED"
    assert _rows(db, "SELECT COUNT(*) AS n FROM quote_items WHERE quote_id = %s AND print_on_pdf = false", (qid,))[0]["n"] == 1


@needs_db
def test_a_client_that_omits_the_flag_cannot_unhide_lines(db):
    qid = _quote(db, [SHOWN, HIDDEN]).json()["data"]["quote_id"]
    stale = [{k: v for k, v in i.items() if k != "print_on_pdf"} for i in (SHOWN, HIDDEN)]
    r = client.put(f"/quotes/{qid}", json={"items": stale}, headers=_hdr())
    assert r.status_code == 409 and r.json()["code"] == "PRINT_FLAG_REQUIRED"
    assert _rows(db, "SELECT COUNT(*) AS n FROM quote_items WHERE quote_id = %s AND print_on_pdf = false", (qid,))[0]["n"] == 1


@needs_db
def test_duplicate_and_convert_keep_the_flag(db):
    qid = _quote(db, [SHOWN, HIDDEN]).json()["data"]["quote_id"]
    dup = client.post(f"/quotes/{qid}/duplicate", headers=_hdr()).json()["data"]["quote_id"]
    assert [r["print_on_pdf"] for r in _rows(db, "SELECT print_on_pdf FROM quote_items WHERE quote_id = %s ORDER BY id", (dup,))] == [True, False]
    iid = _to_invoice(db, qid)
    rows = _rows(db, "SELECT description, print_on_pdf, total FROM invoice_items WHERE invoice_id = %s ORDER BY line_no", (iid,))
    assert [(r["description"], r["print_on_pdf"]) for r in rows] == [("Viga visible", True), ("Costo indirecto secreto", False)]
    inv = _rows(db, "SELECT total_amount, grand_total FROM invoices WHERE id = %s", (iid,))[0]
    assert float(inv["grand_total"]) == pytest.approx(1300 * 1.18)  # the hidden 300 is billed


@needs_db
def test_public_pages_never_receive_hidden_lines_but_keep_the_billed_total(db):
    qid = _quote(db, [SHOWN, HIDDEN]).json()["data"]["quote_id"]
    token = _rows(db, "SELECT public_token FROM quotes WHERE quote_id = %s", (qid,))
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    token = _rows(db, "SELECT public_token FROM quotes WHERE quote_id = %s", (qid,))[0]["public_token"]
    r = client.get(f"/quotes/public/{token}")
    assert r.status_code == 200
    assert "Costo indirecto secreto" not in r.text and "300" not in str([i["unit_price"] for i in r.json()["data"]["items"]])
    pub = r.json()["data"]
    assert [i["product_name"] for i in pub["items"]] == ["Viga visible"]
    assert pub["display_totals"]["items_total"] == 1300.0 and pub["display_totals"]["grand_total"] == pytest.approx(1534.0)

    iid = _to_invoice(db, qid)
    itoken = _rows(db, "SELECT public_token FROM invoices WHERE id = %s", (iid,))[0]["public_token"]
    ri = client.get(f"/invoices/public/{itoken}")
    assert ri.status_code == 200 and "Costo indirecto secreto" not in ri.text
    assert ri.json()["data"]["display_totals"]["grand_total"] == pytest.approx(1534.0)


@needs_db
def test_all_customer_pdf_routes_hide_the_line(db, monkeypatch):
    texts = _capture_text(monkeypatch)
    qid = _quote(db, [SHOWN, HIDDEN]).json()["data"]["quote_id"]
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    token = _rows(db, "SELECT public_token FROM quotes WHERE quote_id = %s", (qid,))[0]["public_token"]
    iid = _to_invoice(db, qid)
    itoken = _rows(db, "SELECT public_token FROM invoices WHERE id = %s", (iid,))[0]["public_token"]
    urls = [f"/quotes/public/{token}/pdf", f"/invoices/public/{itoken}/pdf", f"/quotes/{qid}/pdf",
            f"/pdf/quotes/{qid}", f"/pdf/invoices/{iid}", f"/pdf/invoices/{iid}/conduce"]
    ok = 0
    for url in urls:
        texts.clear()
        r = client.get(url, headers=_hdr())
        if r.status_code == 200:
            ok += 1
            assert "Costo indirecto secreto" not in "\n".join(texts), url
    assert ok >= 4


@needs_db
def test_print_options_endpoint(db, monkeypatch):
    assert client.get("/quotes/print-options", headers=_hdr()).json()["data"] == {"print_controls_enabled": True}
    monkeypatch.setenv("PRINT_CONTROLS_ENABLED", "false")
    assert client.get("/quotes/print-options", headers=_hdr()).json()["data"] == {"print_controls_enabled": False}
    assert client.get("/quotes/print-options").status_code in (401, 403)


@needs_db
def test_existing_rows_default_to_printable(db):
    conn = db["connect"]()
    cur = conn.cursor()
    cur.execute("INSERT INTO quotes (quote_id, client_id, status, tax_type_code, tax_rate, tax_label) "
                "VALUES ('legacy-1', %s, 'Draft', 'itbis_18', 0.18, 'ITBIS (18%%)')", (db["cid"],))
    cur.execute("INSERT INTO quote_items (quote_id, product_name, quantity, unit_price) VALUES ('legacy-1', 'viejo', 1, 10)")
    conn.commit()
    conn.close()
    assert _rows(db, "SELECT print_on_pdf FROM quote_items WHERE quote_id = 'legacy-1'")[0]["print_on_pdf"] is True


# ---------------- template packs (ci schema has no pack pricing columns, so cursor-level) ----------------

class _Cur:
    def __init__(self, hidden_existing=0):
        self.sql, self.hidden_existing, self._last = [], hidden_existing, ""

    def execute(self, q, p=None):
        self._last = " ".join(q.split())
        self.sql.append((self._last, p))

    def fetchone(self):
        return {"n": self.hidden_existing}


def _pack_categories(*flags):
    from template_packs.models import PackCategoryIn, PackItemIn
    return [PackCategoryIn(name="C", items=[PackItemIn(product_id=i + 1, print_on_pdf=f) for i, f in enumerate(flags)])]


def test_pack_hiding_needs_the_switch(monkeypatch):
    from fastapi import HTTPException
    from template_packs import service as svc
    monkeypatch.setenv("PRINT_CONTROLS_ENABLED", "false")
    with pytest.raises(HTTPException) as exc:
        svc._check_print_flags(_Cur(), None, _pack_categories(True, False))
    assert exc.value.code == "PRINT_CONTROLS_DISABLED"
    svc._check_print_flags(_Cur(), None, _pack_categories(True, True))  # nothing hidden: fine
    svc._check_print_flags(_Cur(hidden_existing=1), 7, _pack_categories(True, False))  # already hides one: fine
    monkeypatch.setenv("PRINT_CONTROLS_ENABLED", "true")
    svc._check_print_flags(_Cur(), None, _pack_categories(False, False))


def test_pack_update_without_flag_cannot_unhide(monkeypatch):
    from fastapi import HTTPException
    from template_packs import service as svc
    with pytest.raises(HTTPException) as exc:
        svc._check_print_flags(_Cur(hidden_existing=1), 7, _pack_categories(None, True))
    assert exc.value.status_code == 409 and exc.value.code == "PRINT_FLAG_REQUIRED"
    svc._check_print_flags(_Cur(hidden_existing=0), 7, _pack_categories(None, True))  # nothing to protect


def test_pack_insert_writes_the_flag():
    from template_packs import service as svc
    cur = _Cur()
    cur.fetchone = lambda: {"id": 5}
    svc._insert_categories(cur, 1, _pack_categories(True, False, None))
    inserts = [p for q, p in cur.sql if q.startswith("INSERT INTO template_pack_items")]
    assert [p[-1] for p in inserts] == [True, False, True]  # None never hides
