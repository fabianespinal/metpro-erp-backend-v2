"""A1 Tax architecture: tax types are data, documents snapshot them.

Unit tests run everywhere. Integration tests need Postgres with the production schema
(METPRO_LEDGER_TEST_DB, same database as test_batch3_high.py); skipped otherwise.
"""
import ast
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
from main import app  # noqa: E402
from quotes.service import calculate_quote_totals  # noqa: E402
from quotes.totals import compute_totals  # noqa: E402

client = TestClient(app)

ITEMS = [{"product_name": "Viga", "quantity": 2, "unit_price": 500.0, "discount_type": "none", "discount_value": 0}]
NO_CHARGES = {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}
BODY = {"client_id": None, "contact_id": None, "project_name": "A1", "items": ITEMS, "included_charges": NO_CHARGES}


def _hdr(role="user"):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


# ---------------- arithmetic ----------------

def test_rate_is_a_parameter_of_the_totals():
    t18 = calculate_quote_totals(ITEMS, NO_CHARGES, 0.18)
    t18_default = calculate_quote_totals(ITEMS, NO_CHARGES)
    t018 = calculate_quote_totals(ITEMS, NO_CHARGES, 0.018)
    assert t18["itbis"] == pytest.approx(180.0) and t18["grand_total"] == pytest.approx(1180.0)
    assert t18_default == t18  # pre-A1 behavior is unchanged when no rate is passed
    assert t018["itbis"] == pytest.approx(18.0) and t018["grand_total"] == pytest.approx(1018.0)
    c = compute_totals(ITEMS, NO_CHARGES, 0.018)
    assert c["tax_amount"] == pytest.approx(18.0) and c["tax_rate"] == 0.018 and c["grand_total"] == pytest.approx(1018.0)


# ---------------- migration shape ----------------

def _migration_sql(name):
    path = os.path.join(ROOT, "migrations", name)
    lines = open(path, encoding="utf-8").read().splitlines()
    return "\n".join(l.split("--")[0] for l in lines).upper()


def test_migration_is_additive_seeds_two_types_and_keeps_rls_on():
    sql = _migration_sql("2026-10-22_tax_types.sql")
    assert "ALTER TABLE PUBLIC.TAX_TYPES ENABLE ROW LEVEL SECURITY" in sql
    for forbidden in ("DROP TABLE", "DROP COLUMN", "DELETE FROM", "UPDATE ", "TRUNCATE", "RENAME", "SET NOT NULL"):
        assert forbidden not in sql, forbidden
    # The only ALTER COLUMN allowed is dropping the history default on the six new columns.
    alters = re.findall(r"ALTER COLUMN (\w+)\s+(\w+ \w+)", sql)
    assert len(alters) == 6 and all(a[1] == "DROP DEFAULT" for a in alters)
    assert {a[0] for a in alters} == {"TAX_TYPE_CODE", "TAX_RATE", "TAX_LABEL"}
    assert "'ITBIS_18'" in sql and "'CONSTRUCTION_17_2017'" in sql
    # The 1.8% type is seeded inactive: activating it is the explicit switch.
    assert "'LEY 17-2017 (1.8%)', 0.0180, FALSE, FALSE, 2" in sql


def test_rollback_refuses_when_non_default_documents_exist():
    sql = _migration_sql("2026-10-22_tax_types.rollback.sql")
    assert "RAISE EXCEPTION" in sql and "TAX_TYPE_CODE <> 'ITBIS_18'" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN")


# ---------------- no stray rate in code ----------------

def _py_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in ("tests", "venv", ".git", "__pycache__", "node_modules", "migrations")]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(base, f)


def test_only_the_known_legacy_places_hardcode_the_rate():
    hits = {}
    for path in _py_files():
        for n, line in enumerate(open(path, encoding="utf-8"), start=1):
            code = line.split("#")[0]
            if re.search(r"(?<![\d.])0\.18(?![\d])", code) or "18%" in code:
                hits.setdefault(os.path.relpath(path, ROOT), []).append(n)
    allowed = {
        "quotes/service.py": 1,    # LEGACY_TAX_RATE
        "quotes/totals.py": 1,     # TAX_RATE default for callers that pass no rate
        "invoices/service.py": 1,  # _legacy_calculate_invoice_totals, kept for the parity test
    }
    assert {k: len(v) for k, v in hits.items()} == allowed, hits


def test_every_pdf_call_passes_the_tax_label():
    """Each call that builds a quote or invoice PDF passes tax_label, so none falls back to a generic label."""
    names = {"create_quote_pdf", "create_invoice_pdf", "build_quote_invoice_pdf"}
    seen = 0
    for path in _py_files():
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", None)
                if name in names:
                    # conduce and the wrappers' own forwarding calls are covered by the same rule
                    assert any(k.arg == "tax_label" for k in node.keywords), f"{os.path.relpath(path, ROOT)}:{node.lineno}"
                    seen += 1
    assert seen >= 7


def test_pdf_prints_the_stored_label(monkeypatch):
    from fpdf import FPDF
    from pdf.builder_invoice import create_invoice_pdf

    texts = []
    real = FPDF.cell

    def spy(self, *a, **k):
        t = k.get("txt") or k.get("text") or (a[2] if len(a) > 2 else "")
        texts.append(str(t))
        return real(self, *a, **k)

    monkeypatch.setattr(FPDF, "cell", spy)
    t = calculate_quote_totals(ITEMS, NO_CHARGES, 0.018)
    kwargs = dict(
        doc_type="FACTURA", doc_id="F-1", doc_date="2026-10-22",
        client={"company_name": "X", "address": "", "tax_id": "", "contact_name": "", "email": "", "phone": ""},
        project_name="P", notes="", items=ITEMS, charges=NO_CHARGES,
        items_total=t["items_total"], total_discounts=0, items_after_discount=t["items_after_discount"],
        supervision=0, supervision_pct=10, admin=0, admin_pct=4, insurance=0, insurance_pct=1,
        transport=0, transport_pct=3, contingency=0, contingency_pct=3,
        subtotal_general=t["subtotal_general"], itbis=t["itbis"], grand_total=t["grand_total"],
    )
    create_invoice_pdf(tax_label="Ley 17-2017 (1.8%)", **kwargs)
    assert "Ley 17-2017 (1.8%):" in texts
    assert "ITBIS (18%):" not in texts
    texts.clear()
    create_invoice_pdf(**kwargs)  # no label: generic text, never a wrong percentage
    assert "ITBIS:" in texts and "ITBIS (18%):" not in texts


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
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                "('00000000-0000-0000-0000-000000000001', 't_user', 'x', 't_user@test.local', 'user', true) "
                "ON CONFLICT DO NOTHING")
    cur.execute("UPDATE tax_types SET rate = 0.1800, label = 'ITBIS (18%)', active = true WHERE code = 'itbis_18'")
    cur.execute("UPDATE tax_types SET rate = 0.0180, label = 'Ley 17-2017 (1.8%)', active = true "
                "WHERE code = 'construction_17_2017'")
    cur.execute("INSERT INTO clients (company_name, tax_id) VALUES ('Cliente A1', '1-31-00001-1') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name, email) VALUES (%s, 'Ana', 'a@x.com') RETURNING id", (cid,))
    ctid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    yield {"cid": cid, "ctid": ctid, "connect": connect}
    conn = connect()
    cur = conn.cursor()
    cur.execute("UPDATE tax_types SET rate = 0.1800, label = 'ITBIS (18%)', active = true WHERE code = 'itbis_18'")
    cur.execute("UPDATE tax_types SET rate = 0.0180, label = 'Ley 17-2017 (1.8%)', active = true "
                "WHERE code = 'construction_17_2017'")
    conn.commit()
    conn.close()


def _body(db, **over):
    b = dict(BODY, client_id=db["cid"], contact_id=db["ctid"])
    b.update(over)
    return b


def _row(db, sql, params=()):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        conn.close()


@needs_db
def test_tax_types_endpoint_lists_active_types_only(db):
    r = client.get("/tax-types", headers=_hdr())
    assert r.status_code == 200
    data = r.json()["data"]
    assert [t["code"] for t in data] == ["itbis_18", "construction_17_2017"]
    assert data[0]["is_default"] is True and data[1]["rate"] == 0.018
    conn = db["connect"]()
    conn.cursor().execute("UPDATE tax_types SET active = false WHERE code = 'construction_17_2017'")
    conn.commit()
    conn.close()
    assert [t["code"] for t in client.get("/tax-types", headers=_hdr()).json()["data"]] == ["itbis_18"]
    assert client.get("/tax-types").status_code in (401, 403)


@needs_db
def test_new_quote_defaults_to_the_default_type(db):
    q = client.post("/quotes/", json=_body(db), headers=_hdr()).json()["data"]
    assert q["tax_type_code"] == "itbis_18" and float(q["tax_rate"]) == 0.18
    assert float(q["tax_amount"]) == pytest.approx(180.0) and float(q["grand_total"]) == pytest.approx(1180.0)


@needs_db
def test_quote_with_construction_type_taxes_at_its_rate(db):
    q = client.post("/quotes/", json=_body(db, tax_type_code="construction_17_2017"), headers=_hdr()).json()["data"]
    assert q["tax_type_code"] == "construction_17_2017" and q["tax_label"] == "Ley 17-2017 (1.8%)"
    assert float(q["tax_amount"]) == pytest.approx(18.0) and float(q["grand_total"]) == pytest.approx(1018.0)


@needs_db
def test_unknown_or_inactive_type_is_rejected(db):
    r = client.post("/quotes/", json=_body(db, tax_type_code="nope"), headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "TAX_TYPE_INVALID"
    conn = db["connect"]()
    conn.cursor().execute("UPDATE tax_types SET active = false WHERE code = 'construction_17_2017'")
    conn.commit()
    conn.close()
    r = client.post("/quotes/", json=_body(db, tax_type_code="construction_17_2017"), headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "TAX_TYPE_INVALID"
    r = client.post("/quotes/totals/preview", json={"items": ITEMS, "included_charges": NO_CHARGES,
                                                    "tax_type_code": "construction_17_2017"}, headers=_hdr())
    assert r.status_code == 400


@needs_db
def test_preview_uses_the_chosen_type(db):
    r = client.post("/quotes/totals/preview", json={"items": ITEMS, "included_charges": NO_CHARGES,
                                                    "tax_type_code": "construction_17_2017"}, headers=_hdr())
    d = r.json()["data"]
    assert d["tax_rate"] == pytest.approx(0.018) and d["tax_amount"] == pytest.approx(18.0)
    assert d["tax_type_code"] == "construction_17_2017" and d["tax_label"] == "Ley 17-2017 (1.8%)"
    d = client.post("/quotes/totals/preview", json={"items": ITEMS, "included_charges": NO_CHARGES},
                    headers=_hdr()).json()["data"]
    assert d["tax_rate"] == pytest.approx(0.18) and d["tax_type_code"] == "itbis_18"


@needs_db
def test_draft_can_change_type_and_totals_follow(db):
    q = client.post("/quotes/", json=_body(db), headers=_hdr()).json()["data"]
    qid = q["quote_id"]
    r = client.put(f"/quotes/{qid}", json={"tax_type_code": "construction_17_2017"}, headers=_hdr())
    assert r.status_code == 200, r.text
    row = _row(db, "SELECT tax_type_code, tax_rate, tax_amount, grand_total FROM quotes WHERE quote_id = %s", (qid,))
    assert row["tax_type_code"] == "construction_17_2017"
    assert float(row["tax_amount"]) == pytest.approx(18.0) and float(row["grand_total"]) == pytest.approx(1018.0)
    # an edit that does not name a type keeps the snapshot
    client.put(f"/quotes/{qid}", json={"items": [dict(ITEMS[0], quantity=4)]}, headers=_hdr())
    row = _row(db, "SELECT tax_type_code, tax_amount FROM quotes WHERE quote_id = %s", (qid,))
    assert row["tax_type_code"] == "construction_17_2017" and float(row["tax_amount"]) == pytest.approx(36.0)


@needs_db
def test_type_is_locked_after_finalize(db):
    q = client.post("/quotes/", json=_body(db), headers=_hdr()).json()["data"]
    qid = q["quote_id"]
    assert client.post(f"/quotes/{qid}/finalize", headers=_hdr()).status_code == 200
    r = client.put(f"/quotes/{qid}", json={"tax_type_code": "construction_17_2017"}, headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "QUOTE_FINALIZED"
    assert _row(db, "SELECT tax_type_code FROM quotes WHERE quote_id = %s", (qid,))["tax_type_code"] == "itbis_18"


@needs_db
def test_snapshot_survives_a_rate_change_and_reaches_the_invoice(db):
    q = client.post("/quotes/", json=_body(db, tax_type_code="construction_17_2017"), headers=_hdr()).json()["data"]
    qid = q["quote_id"]
    assert client.post(f"/quotes/{qid}/finalize", headers=_hdr()).status_code == 200
    conn = db["connect"]()
    conn.cursor().execute("UPDATE tax_types SET rate = 0.5, label = 'Cambiado' WHERE code = 'construction_17_2017'")
    conn.commit()
    conn.close()
    assert client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr()).status_code == 200
    inv = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()).json()["data"]
    row = _row(db, "SELECT tax_type_code, tax_rate, tax_label, itbis_total, grand_total, total_amount FROM invoices WHERE id = %s",
               (inv["invoice_id"],))
    assert row["tax_type_code"] == "construction_17_2017" and float(row["tax_rate"]) == pytest.approx(0.018)
    assert row["tax_label"] == "Ley 17-2017 (1.8%)"
    assert float(row["itbis_total"]) == pytest.approx(18.0) and float(row["grand_total"]) == pytest.approx(1018.0)
    quote = _row(db, "SELECT tax_rate, tax_label, tax_amount FROM quotes WHERE quote_id = %s", (qid,))
    assert float(quote["tax_rate"]) == pytest.approx(0.018) and quote["tax_label"] == "Ley 17-2017 (1.8%)"


@needs_db
def test_invoice_pdf_totals_use_the_invoice_rate_not_18(db):
    from invoices.service import get_invoice_with_contact, invoice_lines_and_totals
    q = client.post("/quotes/", json=_body(db, tax_type_code="construction_17_2017"), headers=_hdr()).json()["data"]
    qid = q["quote_id"]
    client.post(f"/quotes/{qid}/finalize", headers=_hdr())
    client.patch(f"/quotes/{qid}/status", json={"status": "Approved"}, headers=_hdr())
    inv = client.post(f"/quotes/{qid}/convert-to-invoice", headers=_hdr()).json()["data"]
    invoice = get_invoice_with_contact(inv["invoice_id"])
    raw = invoice["included_charges"]
    _items, totals = invoice_lines_and_totals(invoice, raw)
    assert totals["itbis"] == pytest.approx(18.0) and totals["grand_total"] == pytest.approx(1018.0)
    assert totals["tax_label"] == "Ley 17-2017 (1.8%)" and totals["tax_rate"] == pytest.approx(0.018)
    for url in (f"/pdf/invoices/{inv['invoice_id']}", f"/invoices/{inv['invoice_id']}/pdf"):
        r = client.get(url, headers=_hdr())
        assert r.status_code in (200, 404), url


@needs_db
def test_duplicate_keeps_the_original_snapshot(db):
    q = client.post("/quotes/", json=_body(db, tax_type_code="construction_17_2017"), headers=_hdr()).json()["data"]
    d = client.post(f"/quotes/{q['quote_id']}/duplicate", headers=_hdr()).json()["data"]
    assert d["tax_type_code"] == "construction_17_2017" and float(d["tax_rate"]) == pytest.approx(0.018)
    row = _row(db, "SELECT tax_amount, grand_total FROM quotes WHERE quote_id = %s", (d["quote_id"],))
    assert float(row["tax_amount"]) == pytest.approx(18.0) and float(row["grand_total"]) == pytest.approx(1018.0)


@needs_db
def test_public_payload_carries_label_and_rate(db):
    q = client.post("/quotes/", json=_body(db, tax_type_code="construction_17_2017"), headers=_hdr()).json()["data"]
    fin = client.post(f"/quotes/{q['quote_id']}/finalize", headers=_hdr()).json()["data"]
    token = _row(db, "SELECT public_token FROM quotes WHERE quote_id = %s", (q["quote_id"],))["public_token"]
    pub = client.get(f"/quotes/public/{token}").json()["data"]
    assert pub["tax_label"] == "Ley 17-2017 (1.8%)" and float(pub["tax_rate"]) == pytest.approx(0.018)
    assert "quote_id" not in pub and fin["tax_type_code"] == "construction_17_2017"


@needs_db
def test_new_rows_must_name_their_tax_type(db):
    """The history default was dropped: a path that forgets the snapshot fails loudly, never stamps 18%."""
    import psycopg2
    conn = db["connect"]()
    try:
        with pytest.raises(psycopg2.errors.NotNullViolation):
            conn.cursor().execute("INSERT INTO quotes (quote_id, client_id, status) VALUES ('x-no-tax', %s, 'Draft')",
                                  (db["cid"],))
    finally:
        conn.rollback()
        conn.close()
