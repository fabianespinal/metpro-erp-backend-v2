"""Debug pass batch 5c (cross-module): X-03 project client lock, X-04 invoice ITBIS on the list,
X-05 archive used products. Integration tests: need METPRO_LEDGER_TEST_DB (production schema plus
migrations up to 2026-10-18_products_archive.sql); skipped otherwise.
"""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
USER_ID = "00000000-0000-0000-0000-000000000001"


def _hdr(role="user"):
    return {"Authorization": "Bearer " + create_access_token({"sub": f"t_{role}", "role": role, "user_id": USER_ID})}


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "quotes.router", "quotes.service", "invoices.service", "projects.service",
                "projects.ledger", "reports.service", "products.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO clients (company_name) VALUES ('Cliente A'), ('Cliente B') RETURNING id")
    a, b = [r["id"] for r in cur.fetchall()]
    cur.execute("INSERT INTO products (name, unit_price, cost) VALUES ('Viga', 100, 60), ('Suelto', 10, 5) RETURNING id")
    viga, suelto = [r["id"] for r in cur.fetchall()]
    cur.execute("INSERT INTO quotes (quote_id, client_id, status, subtotal, tax_amount, grand_total, total_amount, "
                "included_charges, quote_number) VALUES ('q-5c', %s, 'Invoiced', 100, 18, 118, 118, '{}', 10008)", (a,))
    cur.execute("INSERT INTO quote_items (quote_id, product_id, product_name, quantity, unit_price) "
                "VALUES ('q-5c', %s, 'Viga', 1, 100)", (viga,))
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, status, total_amount, itbis_total, invoice_date) "
                "VALUES ('F-10008', 'q-5c', %s, 'Pending', 118, 18, '2026-10-17')", (a,))
    cur.execute("INSERT INTO projects (client_id, name, start_date, quote_id, quote_number) "
                "VALUES (%s, 'Desde cotización', '2026-10-01', 'q-5c', 10008) RETURNING id", (a,))
    linked = cur.fetchone()["id"]
    cur.execute("INSERT INTO projects (client_id, name, start_date) VALUES (%s, 'Manual', '2026-10-01') RETURNING id", (a,))
    manual = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"a": a, "b": b, "viga": viga, "suelto": suelto, "linked": linked, "manual": manual}


@needs_db
def test_x03_quote_project_client_is_locked(db):
    r = client.put(f"/projects/{db['linked']}", json={"client_id": db["b"]}, headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "PROJECT_CLIENT_LOCKED"
    assert client.put(f"/projects/{db['linked']}", json={"client_id": db["a"], "name": "Ok"}, headers=_hdr()).status_code == 200
    assert client.put(f"/projects/{db['manual']}", json={"client_id": db["b"]}, headers=_hdr()).status_code == 200


@needs_db
def test_x04_invoice_list_has_itbis(db):
    rows = client.get("/invoices/", headers=_hdr()).json()["data"]
    assert rows[0]["itbis_total"] == 18.0


@needs_db
def test_x05_used_product_is_archived_and_keeps_coverage(db):
    admin, user = _hdr("admin"), _hdr()
    before = client.get("/quotes/q-5c/cost-estimate", headers=user).json()["data"]
    assert before["estimated_cost"] == 60.0 and before["lines_costed"] == 1

    r = client.delete(f"/products/{db['viga']}", headers=admin)
    assert r.status_code == 200 and r.json()["data"]["archived"] is True

    after = client.get("/quotes/q-5c/cost-estimate", headers=user).json()["data"]
    assert after["estimated_cost"] == 60.0 and after["lines_costed"] == 1        # coverage kept
    names = [p["name"] for p in client.get("/products/", headers=user).json()["data"]]
    assert names == ["Suelto"]                                                    # out of the catalog
    report = client.get("/reports/product-profitability", headers=user).json()["data"]
    assert [p["name"] for p in report["products"]] == ["Suelto"]
    assert client.delete(f"/products/{db['viga']}", headers=admin).status_code == 404  # already archived

    # A CSV with the same name creates a new active product instead of reviving the archived one.
    out = client.post("/products/import-csv", headers=user,
                      files={"file": ("p.csv", b"name,unit_price\nViga,120\n")}).json()["data"]
    assert out["imported"] == 1 and out["updated"] == 0


@needs_db
def test_x05_unused_product_is_deleted(db):
    r = client.delete(f"/products/{db['suelto']}", headers=_hdr("admin"))
    assert r.status_code == 200 and r.json()["data"]["archived"] is False
    assert client.get(f"/products/{db['suelto']}", headers=_hdr()).status_code == 404
