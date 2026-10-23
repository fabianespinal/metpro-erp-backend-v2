"""P3a RFQ. Integration tests need METPRO_LEDGER_TEST_DB with migrations/2026-10-23_suppliers*.sql and 2026-10-24_rfq.sql."""
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

from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
UID = "00000000-0000-0000-0000-000000000001"
PRICE_WORDS = ("price", "precio", "cost", "costo", "amount", "monto", "subtotal", "total", "importe")


def _hdr(role="user"):
    return {"Authorization": "Bearer " + create_access_token({"sub": "t_" + role, "role": role, "user_id": UID})}


def _d(r):
    j = r.json()
    return j["data"] if isinstance(j, dict) and "data" in j and "success" in j else j


def _pdf_text(b: bytes) -> str:
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", b, re.S):
        try:
            out.append(zlib.decompress(m.group(1)).decode("latin-1"))
        except Exception:
            pass
    return "\n".join(out)


def test_switch_default_off(monkeypatch):
    from core.rfq_features import rfq_enabled
    monkeypatch.delenv("RFQ_ENABLED", raising=False)
    assert rfq_enabled() is False
    monkeypatch.setenv("RFQ_ENABLED", "true")
    assert rfq_enabled() is True


def test_label_format():
    from rfq.models import rfq_label
    assert rfq_label(1) == "RFQ-0001" and rfq_label(123) == "RFQ-0123" and rfq_label(12345) == "RFQ-12345"


def test_models_have_no_price_fields_and_reject_them():
    from pydantic import ValidationError
    from rfq.models import RfqIn, RfqItemIn, RfqItemOut, RfqOut
    for model in (RfqIn, RfqItemIn, RfqItemOut, RfqOut):
        bad = [f for f in model.model_fields if any(w in f.lower() for w in PRICE_WORDS)]
        assert not bad, (model.__name__, bad)
    with pytest.raises(ValidationError):
        RfqItemIn(item="x", quantity=1, unit_price=5)
    with pytest.raises(ValidationError):
        RfqIn(supplier_id=1, items=[], total=5)


def test_requires_auth():
    assert client.get("/rfq/options").status_code in (401, 403)


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("rfq.service", "suppliers.service", "pdf.utils.signer", "company_settings.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("RFQ_ENABLED", "true")
    monkeypatch.setenv("SUPPLIERS_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM rfqs WHERE vendor_name LIKE '%T-%' OR notes LIKE 'T-%'")
    cur.execute("DELETE FROM suppliers WHERE company_name LIKE 'T-%'")
    cur.execute("INSERT INTO suppliers (company_name, contact_name, tax_id, email) VALUES ('T-Supplier', 'Ana', 'T-RFQ-1', 't-rfq@x.com') RETURNING id")
    sid = cur.fetchone()["id"]
    cur.execute("INSERT INTO suppliers (company_name, is_active, tax_id) VALUES ('T-Inactive', false, 'T-RFQ-2') RETURNING id")
    inactive = cur.fetchone()["id"]
    cur.execute("SELECT id, name FROM products ORDER BY id LIMIT 1")
    prod = cur.fetchone()
    if not prod:
        cur.execute("INSERT INTO products (name, description, unit_price) VALUES ('T-Prod', 'desc', 10) RETURNING id, name")
        prod = cur.fetchone()
    conn.commit()
    yield {"conn": conn, "sid": sid, "inactive": inactive, "pid": prod["id"]}
    cur = conn.cursor()
    cur.execute("DELETE FROM rfqs WHERE vendor_name LIKE '%T-%' OR notes LIKE 'T-%'")
    cur.execute("DELETE FROM suppliers WHERE company_name LIKE 'T-%'")
    cur.execute("DELETE FROM products WHERE name = 'T-Prod'")
    conn.commit()
    conn.close()


def _body(ctx, **kw):
    b = {"supplier_id": ctx["sid"], "notes": "T-note", "payment_terms": "30 días",
         "items": [{"product_id": ctx["pid"], "item": "Viga IPE 200", "description": "Acero A36", "quantity": 4, "unit": "m"},
                   {"item": "Pernos", "description": None, "quantity": 100.5, "unit": "und"}]}
    b.update(kw)
    return b


@needs_db
def test_off_switch_and_options(db, monkeypatch):
    o = _d(client.get("/rfq/options", headers=_hdr()))
    assert o["rfq_enabled"] is True and "METPRO" in o["default_bill_to"]
    monkeypatch.setenv("RFQ_ENABLED", "false")
    assert _d(client.get("/rfq/options", headers=_hdr()))["rfq_enabled"] is False
    r = client.get("/rfq/", headers=_hdr())
    assert r.status_code == 404 and r.json()["code"] == "RFQ_DISABLED"
    assert client.post("/rfq/", json=_body(db), headers=_hdr()).status_code == 404


@needs_db
def test_create_read_edit_status_delete(db):
    r = client.post("/rfq/", json=_body(db), headers=_hdr("user"))  # all users
    assert r.status_code == 200, r.text
    q = _d(r)
    assert q["label"].startswith("RFQ-") and q["status"] == "Draft" and q["vendor_name"] == "T-Supplier"
    assert q["title"] == "Solicitud de cotización" and "METPRO" in q["bill_to"]
    assert [i["item"] for i in q["items"]] == ["Viga IPE 200", "Pernos"] and q["items"][1]["quantity"] == 100.5
    assert not any(any(w in k.lower() for w in PRICE_WORDS) for k in q) and \
        not any(any(w in k.lower() for w in PRICE_WORDS) for i in q["items"] for k in i)
    rid = q["id"]
    # the supplier snapshot does not follow later supplier edits
    cur = db["conn"].cursor()
    cur.execute("UPDATE suppliers SET company_name='T-Renamed' WHERE id=%s", (db["sid"],))
    db["conn"].commit()
    assert _d(client.get(f"/rfq/{rid}", headers=_hdr()))["vendor_name"] == "T-Supplier"
    # edit lines in Draft (items fully editable, product link kept)
    b = _body(db, title="Pedido de precios")
    b["items"][0]["item"] = "IPE-200 6m"
    e = client.put(f"/rfq/{rid}", json=b, headers=_hdr())
    assert e.status_code == 200 and _d(e)["items"][0]["item"] == "IPE-200 6m" and _d(e)["vendor_name"] == "T-Renamed"
    assert _d(e)["title"] == "Pedido de precios"
    # list
    rows = _d(client.get("/rfq/", headers=_hdr()))
    assert any(x["id"] == rid and x["item_count"] == 2 for x in rows)
    # lock after Sent
    s = client.put(f"/rfq/{rid}/status", json={"status": "Sent"}, headers=_hdr())
    assert s.status_code == 200 and _d(s)["status"] == "Sent"
    assert client.put(f"/rfq/{rid}", json=b, headers=_hdr()).json()["code"] == "RFQ_LOCKED"
    assert client.delete(f"/rfq/{rid}", headers=_hdr()).json()["code"] == "RFQ_LOCKED"
    # supplier with an RFQ cannot be deleted
    d = client.delete(f"/suppliers/{db['sid']}", headers=_hdr("admin"))
    assert d.status_code == 400 and d.json()["code"] == "SUPPLIER_IN_USE"
    # back to Draft, then delete
    assert _d(client.put(f"/rfq/{rid}/status", json={"status": "Draft"}, headers=_hdr()))["status"] == "Draft"
    assert client.delete(f"/rfq/{rid}", headers=_hdr()).status_code == 200
    assert client.get(f"/rfq/{rid}", headers=_hdr()).status_code == 404


@needs_db
def test_validation(db):
    assert client.post("/rfq/", json=_body(db, items=[]), headers=_hdr()).json()["code"] == "RFQ_NO_ITEMS"
    assert client.post("/rfq/", json=_body(db, supplier_id=99999999), headers=_hdr()).json()["code"] == "SUPPLIER_NOT_FOUND"
    assert client.post("/rfq/", json=_body(db, supplier_id=db["inactive"]), headers=_hdr()).json()["code"] == "SUPPLIER_INACTIVE"
    bad = _body(db); bad["items"][0]["quantity"] = 0
    assert client.post("/rfq/", json=bad, headers=_hdr()).status_code == 422
    bad = _body(db); bad["items"][0]["item"] = "  "
    assert client.post("/rfq/", json=bad, headers=_hdr()).status_code == 422
    bad = _body(db); bad["items"][0]["unit_price"] = 9.99
    assert client.post("/rfq/", json=bad, headers=_hdr()).status_code == 422
    bad = _body(db); bad["items"][0]["product_id"] = 99999999
    assert client.post("/rfq/", json=bad, headers=_hdr()).json()["code"] == "RFQ_PRODUCT_NOT_FOUND"
    assert client.get("/rfq/99999999", headers=_hdr()).json()["code"] == "RFQ_NOT_FOUND"


@needs_db
def test_pdf_has_content_and_no_prices(db):
    q = _d(client.post("/rfq/", json=_body(db, payment_terms="30 dias", notes="T-note"), headers=_hdr()))
    r = client.get(f"/rfq/{q['id']}/pdf", headers=_hdr())
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
    assert q["label"] in r.headers["content-disposition"]
    t = _pdf_text(r.content)
    assert t  # content streams readable
    low = t.lower()
    for word in ("precio", "unitario", "subtotal", "importe", "rd$", "itbis"):
        assert word not in low, word
    assert client.get("/rfq/99999999/pdf", headers=_hdr()).status_code == 404
