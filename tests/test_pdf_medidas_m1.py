"""PDF update M1: Medidas (unit of measure) and the per-quote print_items checkbox. Data and API only.

Unit tests run everywhere. Integration tests need Postgres with the production schema plus
2026-10-23_pdf_medidas_print_items (METPRO_LEDGER_TEST_DB); skipped otherwise.
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
from core import pdf_options  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
NO_CHARGES = {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}
LINE = {"product_name": "Viga W10", "quantity": 2, "unit_price": 500.0, "discount_type": "none", "discount_value": 0}


def _hdr():
    token = create_access_token({"sub": "t_user", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


def _sql(name):
    lines = open(os.path.join(ROOT, "migrations", name), encoding="utf-8").read().splitlines()
    return "\n".join(l.split("--")[0] for l in lines).upper()


# ---------------- switches and helpers ----------------

@pytest.mark.parametrize("fn,env", [(pdf_options.medidas_enabled, "PDF_MEDIDAS_ENABLED"),
                                    (pdf_options.print_items_enabled, "PDF_PRINT_ITEMS_ENABLED"),
                                    (pdf_options.project_desc_enabled, "PDF_PROJECT_DESC_ENABLED")])
def test_switches_default_off(monkeypatch, fn, env):
    monkeypatch.delenv(env, raising=False)
    assert fn() is False
    monkeypatch.setenv(env, "true")
    assert fn() is True


def test_clean_unit():
    assert pdf_options.clean_unit(None) is None and pdf_options.clean_unit("  ") is None
    assert pdf_options.clean_unit(" Ft ") == "Ft" and len(pdf_options.clean_unit("x" * 50)) == 20


def test_with_units_is_a_no_op_when_off_or_empty(monkeypatch):
    sql, rows = "INSERT INTO t (a) VALUES %s", [(1,), (2,)]
    monkeypatch.delenv("PDF_MEDIDAS_ENABLED", raising=False)
    assert pdf_options.with_units(sql, rows, [{"unit_of_measure": "Ft"}, {}]) == (sql, rows)
    monkeypatch.setenv("PDF_MEDIDAS_ENABLED", "true")
    assert pdf_options.with_units(sql, rows, [{}, {"unit_of_measure": " "}]) == (sql, rows)
    assert pdf_options.with_units(sql, rows, [{"unit_of_measure": "Ft"}, {}]) == (
        "INSERT INTO t (a, unit_of_measure) VALUES %s", [(1, "Ft"), (2, None)])


# ---------------- migration ----------------

def test_migration_is_additive():
    sql = re.sub(r"\s+", " ", _sql("2026-10-23_pdf_medidas_print_items.sql"))
    for forbidden in ("DROP ", "DELETE FROM", "UPDATE ", "TRUNCATE", "RENAME"):
        assert forbidden not in sql
    assert sql.count("UNIT_OF_MEASURE TEXT") == 3
    assert sql.count("PRINT_ITEMS BOOLEAN NOT NULL DEFAULT TRUE") == 2


def test_rollback_refuses_while_data_uses_the_columns():
    sql = _sql("2026-10-23_pdf_medidas_print_items.rollback.sql")
    assert sql.count("UNIT_OF_MEASURE IS NOT NULL") == 3 and sql.count("WHERE PRINT_ITEMS = FALSE)") == 2
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN")


# ---------------- integration ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.service", "invoices.service", "invoices.router", "pdf.service", "products.service",
                "projects.service", "reports.service", "tax.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("PDF_MEDIDAS_ENABLED", "true")
    monkeypatch.setenv("PDF_PRINT_ITEMS_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "('00000000-0000-0000-0000-000000000001', 't_user', 'x', 't_user@test.local', 'user', true) "
                "ON CONFLICT DO NOTHING")
    cur.execute("INSERT INTO clients (company_name, tax_id) VALUES ('Cliente M1', '1-31-00001-1') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"cid": cid, "ctid": ctid, "connect": connect}


def _quote(db, items, **over):
    body = {"client_id": db["cid"], "contact_id": db["ctid"], "project_name": "M1", "items": items,
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


def _units(db, qid):
    return [r["unit_of_measure"] for r in _rows(db, "SELECT unit_of_measure FROM quote_items WHERE quote_id = %s ORDER BY id", (qid,))]


def _product(unit=None, name="Viga W10"):
    body = {"name": name, "description": None, "unit_price": 500.0}
    if unit is not None:
        body["unit_of_measure"] = unit
    r = client.post("/products/", json=body, headers=_hdr())
    assert r.status_code == 200, r.text
    return r.json()["data"] if "data" in r.json() else r.json()


@needs_db
def test_flags_endpoint(db, monkeypatch):
    monkeypatch.setenv("PDF_PROJECT_DESC_ENABLED", "false")
    r = client.get("/quotes/pdf-options", headers=_hdr())
    assert r.status_code == 200
    assert r.json()["data"] == {"medidas_enabled": True, "print_items_enabled": True, "project_desc_enabled": False}


@needs_db
def test_product_unit_is_free_text_and_clearable(db):
    p = _product("Ft")
    assert p["unit_of_measure"] == "Ft"
    r = client.put(f"/products/{p['id']}", json={"name": "Viga W10", "unit_price": 500.0, "unit_of_measure": "Tramo"}, headers=_hdr())
    assert r.status_code == 200 and _rows(db, "SELECT unit_of_measure FROM products")[0]["unit_of_measure"] == "Tramo"
    # an older client that omits the field keeps the stored unit
    client.put(f"/products/{p['id']}", json={"name": "Viga W10", "unit_price": 510.0}, headers=_hdr())
    assert _rows(db, "SELECT unit_of_measure FROM products")[0]["unit_of_measure"] == "Tramo"
    client.put(f"/products/{p['id']}", json={"name": "Viga W10", "unit_price": 510.0, "unit_of_measure": ""}, headers=_hdr())
    assert _rows(db, "SELECT unit_of_measure FROM products")[0]["unit_of_measure"] is None


@needs_db
def test_line_unit_explicit_from_product_and_cleared(db):
    p = _product("Ft")
    qid = _quote(db, [dict(LINE, product_id=p["id"]),                       # no unit sent: takes the product's
                      dict(LINE, product_id=p["id"], unit_of_measure="M"),  # explicit wins
                      dict(LINE, product_id=p["id"], unit_of_measure=""),   # cleared on purpose stays blank
                      dict(LINE)]).json()["data"]["quote_id"]               # custom line, no unit
    assert _units(db, qid) == ["Ft", "M", None, None]
    got = client.get(f"/quotes/{qid}", headers=_hdr()).json()["data"]
    assert [i["unit_of_measure"] for i in got["items"]] == ["Ft", "M", None, None]


@needs_db
def test_edit_keeps_and_changes_units(db):
    qid = _quote(db, [dict(LINE, unit_of_measure="Ft")]).json()["data"]["quote_id"]
    r = client.put(f"/quotes/{qid}", json={"items": [dict(LINE, unit_of_measure="Ton")]}, headers=_hdr())
    assert r.status_code == 200, r.text
    assert _units(db, qid) == ["Ton"]


@needs_db
def test_switch_off_ignores_units_and_changes_nothing(db, monkeypatch):
    monkeypatch.setenv("PDF_MEDIDAS_ENABLED", "false")
    p = _product("Ft")  # not stored while off
    assert p.get("unit_of_measure") is None
    qid = _quote(db, [dict(LINE, unit_of_measure="Ft")]).json()["data"]["quote_id"]
    assert _units(db, qid) == [None]


@needs_db
def test_print_items_default_true_and_totals_never_change(db):
    a = _quote(db, [LINE]).json()["data"]["quote_id"]
    b = _quote(db, [LINE], print_items=False).json()["data"]["quote_id"]
    assert _rows(db, "SELECT print_items FROM quotes WHERE quote_id = %s", (a,))[0]["print_items"] is True
    assert _rows(db, "SELECT print_items FROM quotes WHERE quote_id = %s", (b,))[0]["print_items"] is False
    ta = _rows(db, "SELECT subtotal, grand_total FROM quotes WHERE quote_id = %s", (a,))[0]
    tb = _rows(db, "SELECT subtotal, grand_total FROM quotes WHERE quote_id = %s", (b,))[0]
    assert ta == tb
    assert client.get(f"/quotes/{b}", headers=_hdr()).json()["data"]["print_items"] is False
    assert client.get(f"/quotes/{a}", headers=_hdr()).json()["data"]["print_items"] is True


@needs_db
def test_hiding_items_needs_its_switch_showing_never_does(db, monkeypatch):
    qid = _quote(db, [LINE], print_items=False).json()["data"]["quote_id"]
    monkeypatch.setenv("PDF_PRINT_ITEMS_ENABLED", "false")
    bad = _quote(db, [LINE], print_items=False)
    assert bad.status_code == 400 and bad.json()["code"] == "PDF_PRINT_ITEMS_DISABLED"
    bad2 = client.put(f"/quotes/{qid}", json={"print_items": False}, headers=_hdr())
    assert bad2.status_code == 400 and bad2.json()["code"] == "PDF_PRINT_ITEMS_DISABLED"
    ok = client.put(f"/quotes/{qid}", json={"print_items": True}, headers=_hdr())  # turning it back on is always allowed
    assert ok.status_code == 200, ok.text
    assert _rows(db, "SELECT print_items FROM quotes WHERE quote_id = %s", (qid,))[0]["print_items"] is True


@needs_db
def test_update_without_the_field_keeps_the_checkbox(db):
    qid = _quote(db, [LINE], print_items=False).json()["data"]["quote_id"]
    r = client.put(f"/quotes/{qid}", json={"notes": "x", "items": [LINE]}, headers=_hdr())
    assert r.status_code == 200, r.text
    assert _rows(db, "SELECT print_items FROM quotes WHERE quote_id = %s", (qid,))[0]["print_items"] is False


@needs_db
def test_duplicate_and_invoice_inherit_checkbox_and_units(db):
    qid = _quote(db, [dict(LINE, unit_of_measure="Ft"), dict(LINE, product_name="Otro")], print_items=False).json()["data"]["quote_id"]
    dup = client.post(f"/quotes/{qid}/duplicate", headers=_hdr()).json()["data"]["quote_id"]
    assert _rows(db, "SELECT print_items FROM quotes WHERE quote_id = %s", (dup,))[0]["print_items"] is False
    assert _units(db, dup) == ["Ft", None]
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    assert client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr()).status_code == 200
    r = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr())
    assert r.status_code == 200, r.text
    iid = r.json()["data"]["invoice_id"]
    assert _rows(db, "SELECT print_items FROM invoices WHERE id = %s", (iid,))[0]["print_items"] is False
    assert [x["unit_of_measure"] for x in _rows(db, "SELECT unit_of_measure FROM invoice_items WHERE invoice_id = %s ORDER BY line_no", (iid,))] == ["Ft", None]
    from invoices.service import _invoice_lines
    conn = db["connect"]()
    try:
        lines, _ = _invoice_lines(conn.cursor(), {"id": iid, "quote_id": qid})
    finally:
        conn.close()
    assert [l["unit_of_measure"] for l in lines] == ["Ft", None]


@needs_db
def test_default_quotes_convert_exactly_as_before(db):
    qid = _quote(db, [LINE]).json()["data"]["quote_id"]
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr())
    iid = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()).json()["data"]["invoice_id"]
    assert _rows(db, "SELECT print_items FROM invoices WHERE id = %s", (iid,))[0]["print_items"] is True
    assert _rows(db, "SELECT unit_of_measure FROM invoice_items WHERE invoice_id = %s", (iid,))[0]["unit_of_measure"] is None
