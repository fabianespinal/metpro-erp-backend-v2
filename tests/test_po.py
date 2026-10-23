"""P3b purchase orders. Integration tests need METPRO_LEDGER_TEST_DB with the suppliers, rfq and purchase_orders migrations."""
import importlib
import os
import subprocess
import sys
import tempfile
from decimal import Decimal

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
UID = "00000000-0000-0000-0000-000000000001"


def _hdr(role="admin"):
    return {"Authorization": "Bearer " + create_access_token({"sub": "t_" + role, "role": role, "user_id": UID})}


def _d(r):
    j = r.json()
    return j["data"] if isinstance(j, dict) and "data" in j and "success" in j else j


def test_switch_default_off(monkeypatch):
    from core.po_features import po_enabled
    monkeypatch.delenv("PO_ENABLED", raising=False)
    assert po_enabled() is False
    monkeypatch.setenv("PO_ENABLED", "true")
    assert po_enabled() is True


def test_label_and_rounding():
    from po.models import po_label
    from po.service import line_amount
    assert po_label(1) == "PO-0001" and po_label(12345) == "PO-12345"
    assert line_amount(3, 0.335) == Decimal("1.01")        # half up, not binary float
    assert line_amount(2.5, 100) == Decimal("250.00")
    assert line_amount(0.1, 0.2) == Decimal("0.02")
    assert line_amount(1000, 1234.5678) == Decimal("1234567.80")


def test_models_never_take_amounts():
    from pydantic import ValidationError
    from po.models import PoIn, PoItemIn
    with pytest.raises(ValidationError):
        PoItemIn(item="x", quantity=1, unit_price=1, amount=99)
    with pytest.raises(ValidationError):
        PoIn(supplier_id=1, items=[], total=5)
    with pytest.raises(ValidationError):
        PoIn(supplier_id=1, items=[], subtotal=5)
    with pytest.raises(ValidationError):
        PoItemIn(item="x", quantity=1, unit_price=-1)


def test_requires_auth():
    assert client.get("/po/options").status_code in (401, 403)


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("po.service", "rfq.service", "suppliers.service", "pdf.utils.signer", "company_settings.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("PO_ENABLED", "true")
    monkeypatch.setenv("RFQ_ENABLED", "true")
    monkeypatch.setenv("SUPPLIERS_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()

    def clean():
        cur.execute("DELETE FROM purchase_orders WHERE notes LIKE 'T-%' OR vendor_name LIKE 'T-%'")
        cur.execute("DELETE FROM rfqs WHERE notes LIKE 'T-%' OR vendor_name LIKE 'T-%'")
        cur.execute("DELETE FROM suppliers WHERE company_name LIKE 'T-%'")
        conn.commit()

    clean()
    cur.execute("INSERT INTO suppliers (company_name, tax_id) VALUES ('T-PoSupplier', 'T-PO-1') RETURNING id")
    sid = cur.fetchone()["id"]
    cur.execute("SELECT id FROM products ORDER BY id LIMIT 1")
    prod = cur.fetchone()
    conn.commit()
    yield {"sid": sid, "pid": prod["id"] if prod else None, "conn": conn}
    clean()
    conn.close()


def _body(ctx, **kw):
    b = {"supplier_id": ctx["sid"], "notes": "T-note", "payment_terms": "30 días",
         "items": [{"product_id": ctx["pid"], "item": "Viga IPE 200", "description": "Acero A36", "quantity": 3, "unit": "m", "unit_price": 0.335},
                   {"item": "Pernos", "quantity": 100, "unit": "und", "unit_price": 12.5}]}
    b.update(kw)
    return b


@needs_db
def test_switch_off_and_roles(db, monkeypatch):
    assert _d(client.get("/po/options", headers=_hdr("user")))["po_enabled"] is True   # flag is readable by any user
    assert client.get("/po/", headers=_hdr("user")).status_code == 403                  # data is admin only
    assert client.post("/po/", json=_body(db), headers=_hdr("user")).status_code == 403
    assert client.get("/po/", headers=_hdr("admin")).status_code == 200
    assert client.get("/po/", headers=_hdr("superadmin")).status_code == 200
    monkeypatch.setenv("PO_ENABLED", "false")
    assert _d(client.get("/po/options", headers=_hdr("user")))["po_enabled"] is False
    r = client.get("/po/", headers=_hdr("admin"))
    assert r.status_code == 404 and r.json()["code"] == "PO_DISABLED"


@needs_db
def test_create_totals_edit_issue_cancel(db):
    r = client.post("/po/", json=_body(db), headers=_hdr("admin"))
    assert r.status_code == 200, r.text
    p = _d(r)
    assert p["label"].startswith("PO-") and p["status"] == "Draft" and p["rfq_id"] is None
    assert [i["amount"] for i in p["items"]] == [1.01, 1250.0]
    assert p["subtotal"] == 1251.01 and p["total"] == 1251.01
    pid = p["id"]
    # edit: backend recomputes, product link and lines editable
    b = _body(db, title="Compra urgente")
    b["items"][0]["quantity"] = 10
    b["items"][0]["unit_price"] = 7.25
    e = _d(client.put(f"/po/{pid}", json=b, headers=_hdr("admin")))
    assert e["items"][0]["amount"] == 72.5 and e["subtotal"] == 1322.5 and e["total"] == 1322.5 and e["title"] == "Compra urgente"
    # cannot cancel a draft; cannot issue with a missing price
    assert client.put(f"/po/{pid}/status", json={"status": "Cancelled"}, headers=_hdr()).json()["code"] == "PO_BAD_TRANSITION"
    b0 = _body(db); b0["items"][1]["unit_price"] = 0
    client.put(f"/po/{pid}", json=b0, headers=_hdr())
    assert client.put(f"/po/{pid}/status", json={"status": "Issued"}, headers=_hdr()).json()["code"] == "PO_PRICE_MISSING"
    client.put(f"/po/{pid}", json=b, headers=_hdr())
    s = client.put(f"/po/{pid}/status", json={"status": "Issued"}, headers=_hdr())
    assert s.status_code == 200 and _d(s)["status"] == "Issued"
    # locked
    assert client.put(f"/po/{pid}", json=b, headers=_hdr()).json()["code"] == "PO_LOCKED"
    assert client.delete(f"/po/{pid}", headers=_hdr()).json()["code"] == "PO_LOCKED"
    assert client.put(f"/po/{pid}/status", json={"status": "Issued"}, headers=_hdr()).json()["code"] == "PO_BAD_TRANSITION"
    # supplier with a P.O cannot be deleted
    assert client.delete(f"/suppliers/{db['sid']}", headers=_hdr("admin")).json()["code"] == "SUPPLIER_IN_USE"
    # cancel
    assert _d(client.put(f"/po/{pid}/status", json={"status": "Cancelled"}, headers=_hdr()))["status"] == "Cancelled"
    assert client.put(f"/po/{pid}/status", json={"status": "Issued"}, headers=_hdr()).json()["code"] == "PO_BAD_TRANSITION"


@needs_db
def test_validation(db):
    assert client.post("/po/", json=_body(db, items=[]), headers=_hdr()).json()["code"] == "PO_NO_ITEMS"
    assert client.post("/po/", json=_body(db, supplier_id=99999999), headers=_hdr()).json()["code"] == "SUPPLIER_NOT_FOUND"
    bad = _body(db); bad["items"][0]["amount"] = 5
    assert client.post("/po/", json=bad, headers=_hdr()).status_code == 422
    assert client.post("/po/", json=_body(db, total=5), headers=_hdr()).status_code == 422
    bad = _body(db); bad["items"][0]["product_id"] = 99999999
    assert client.post("/po/", json=bad, headers=_hdr()).json()["code"] == "PO_PRODUCT_NOT_FOUND"
    assert client.get("/po/99999999", headers=_hdr()).json()["code"] == "PO_NOT_FOUND"


@needs_db
def test_convert_from_rfq(db):
    rfq = _d(client.post("/rfq/", json={"supplier_id": db["sid"], "notes": "T-rfq", "payment_terms": "15 días",
             "items": [{"item": "Plancha 4x8", "description": "3/16", "quantity": 5, "unit": "und"},
                       {"item": "Angular", "quantity": 12, "unit": "m"}]}, headers=_hdr("user")))
    assert client.post(f"/po/from-rfq/{rfq['id']}", headers=_hdr("user")).status_code == 403   # admin only
    r = client.post(f"/po/from-rfq/{rfq['id']}", headers=_hdr("admin"))
    assert r.status_code == 200, r.text
    p = _d(r)
    assert p["rfq_id"] == rfq["id"] and p["rfq_label"] == rfq["label"] and p["status"] == "Draft"
    assert p["vendor_name"] == "T-PoSupplier" and p["payment_terms"] == "15 días"
    assert [(i["item"], i["quantity"], i["unit_price"], i["amount"]) for i in p["items"]] == \
        [("Plancha 4x8", 5.0, 0.0, 0.0), ("Angular", 12.0, 0.0, 0.0)]
    assert p["total"] == 0
    # RFQ is Converted and locked; cannot convert twice
    assert _d(client.get(f"/rfq/{rfq['id']}", headers=_hdr("user")))["status"] == "Converted"
    assert client.post(f"/po/from-rfq/{rfq['id']}", headers=_hdr("admin")).json()["code"] == "RFQ_ALREADY_CONVERTED"
    assert client.put(f"/rfq/{rfq['id']}/status", json={"status": "Draft"}, headers=_hdr("user")).json()["code"] == "RFQ_LOCKED"
    # the user can add, change and remove products and type prices
    b = {"supplier_id": db["sid"], "notes": "T-rfq", "items": [
        {"item": "Plancha 4x8 (proveedor)", "quantity": 5, "unit": "und", "unit_price": 3200},
        {"item": "Pernos", "quantity": 50, "unit": "und", "unit_price": 12}]}
    e = _d(client.put(f"/po/{p['id']}", json=b, headers=_hdr("admin")))
    assert e["total"] == 16600.0 and len(e["items"]) == 2 and e["rfq_id"] == rfq["id"]
    # deleting the draft P.O gives the RFQ back
    assert client.delete(f"/po/{p['id']}", headers=_hdr("admin")).status_code == 200
    assert _d(client.get(f"/rfq/{rfq['id']}", headers=_hdr("user")))["status"] == "Sent"
    assert client.post(f"/po/from-rfq/{rfq['id']}", headers=_hdr("admin")).status_code == 200


@needs_db
def test_pdf_has_prices_and_totals(db):
    p = _d(client.post("/po/", json=_body(db), headers=_hdr("admin")))
    r = client.get(f"/po/{p['id']}/pdf", headers=_hdr("admin"))
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    assert p["label"] in r.headers["content-disposition"]
    assert client.get(f"/po/{p['id']}/pdf", headers=_hdr("user")).status_code == 403
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(r.content)
    out = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout
    for needle in ("ORDEN DE COMPRA", p["label"], "PRECIO UNIT.", "MONTO", "RD$1,251.01", "TOTAL:", "Subtotal:", "Firmado por"):
        assert needle in out, needle
    os.unlink(f.name)
    # the RFQ PDF is still price free
    rfq = _d(client.post("/rfq/", json={"supplier_id": db["sid"], "notes": "T-r", "items": [{"item": "x", "quantity": 1}]}, headers=_hdr("user")))
    rr = client.get(f"/rfq/{rfq['id']}/pdf", headers=_hdr("user"))
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(rr.content)
    t = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True).stdout.lower()
    os.unlink(f.name)
    assert "rd$" not in t and "precio" not in t and "total" not in t
