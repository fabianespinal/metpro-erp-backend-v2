"""Product Cost module (2026-10-18): product cost CRUD, quote estimate, project variance, reports.

Unit tests run everywhere. Integration tests need Postgres with the production schema plus
migrations 2026-10-18_expenses_project_fk.sql and 2026-10-18_product_cost.sql; set
METPRO_LEDGER_TEST_DB to its DSN (skipped otherwise).
"""
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402
from pydantic import ValidationError  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402
from products.models import ProductBase  # noqa: E402
from quotes import costing  # noqa: E402

client = TestClient(app)


def _hdr(role="user"):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


# ---------------- model ----------------

def test_cost_optional_and_non_negative():
    assert ProductBase(name="Viga", unit_price=95).cost is None
    assert ProductBase(name="Viga", unit_price=95, cost=60.5).cost == 60.5
    assert ProductBase(name="Viga", unit_price=95, cost=0).cost == 0
    with pytest.raises(ValidationError):
        ProductBase(name="Viga", unit_price=95, cost=-1)


def test_put_without_cost_keeps_stored_cost(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    seen = {}

    def fake(pid, name, desc, price, cost=None, cost_set=False):
        seen.update(cost=cost, cost_set=cost_set)
        return {"id": pid, "name": name, "description": desc, "unit_price": price, "cost": 70.0}

    monkeypatch.setattr("products.service.update_product", fake)
    r = client.put("/products/1", json={"name": "Viga", "unit_price": 95}, headers=_hdr())
    assert r.status_code == 200 and seen == {"cost": None, "cost_set": False}
    assert r.json()["data"]["cost"] == 70.0
    client.put("/products/1", json={"name": "Viga", "unit_price": 95, "cost": None}, headers=_hdr())
    assert seen == {"cost": None, "cost_set": True}          # explicit null clears
    r = client.put("/products/1", json={"name": "Viga", "unit_price": 95, "cost": -5}, headers=_hdr())
    assert r.status_code == 422


# ---------------- math ----------------

ITEMS = [
    {"product_id": 1, "product_name": "Viga", "quantity": 10, "unit_price": 100},
    {"product_id": 2, "product_name": "Plancha", "quantity": 4, "unit_price": 50},
    {"product_id": None, "product_name": "Montaje", "quantity": 1, "unit_price": 300},
    {"product_id": 3, "product_name": "Sin costo", "quantity": 2, "unit_price": 10},
]


def test_cost_lines_and_summary_exclude_and_flag_missing():
    lines = costing.cost_lines(ITEMS, {1: 60.0, 2: 30.0, 3: None})
    assert [l["line_cost"] for l in lines] == [600.0, 120.0, None, None]
    assert [l["reason"] for l in lines] == [None, None, "sin_producto", "sin_costo"]
    s = costing.summarize(lines, 1500.0)
    assert s["estimated_cost"] == 720.0
    assert s["estimated_margin"] == 780.0
    assert s["estimated_margin_pct"] == 52.0
    assert (s["lines_total"], s["lines_costed"], s["coverage_pct"], s["complete"]) == (4, 2, 50.0, False)


def test_summary_zero_subtotal_and_empty():
    s = costing.summarize([], 0)
    assert s["estimated_margin_pct"] is None and s["coverage_pct"] is None and s["complete"] is False


def test_variance_math():
    v = costing.variance(1000, 1200, 500, 300)
    assert v == {"variance": -200.0, "variance_pct": -20.0, "margin_accuracy_pct": 60.0}
    v = costing.variance(1000, 800, 0, 100)
    assert v["variance"] == 200.0 and v["margin_accuracy_pct"] is None
    v = costing.variance(0, 50, None, None)
    assert v["variance_pct"] is None and v["margin_accuracy_pct"] is None


def test_new_routes_require_auth():
    for m, path in (("GET", "/quotes/x/cost-estimate"), ("POST", "/quotes/cost-estimate/preview"),
                    ("GET", "/projects/1/cost-estimate"), ("GET", "/reports/product-profitability"),
                    ("GET", "/reports/project-variance")):
        assert client.request(m, path).status_code == 401, path


# ---------------- integration ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    import importlib
    # Patch module objects directly: some packages re-export "router" (an APIRouter) under the same name.
    for mod in ("database", "products.service", "quotes.router", "projects.ledger", "reports.service", "expenses.router"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO clients (company_name) VALUES ('Cliente Costos') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO products (name, unit_price, cost) VALUES ('Viga', 100, 60), ('Plancha', 50, 30), "
                "('Sin costo', 10, NULL) RETURNING id")
    p1, p2, p3 = [r["id"] for r in cur.fetchall()]
    # Quote: lines 1000 + 200 + 300 (service, no product) + 20 = 1520; charges off -> subtotal 1520
    cur.execute("INSERT INTO quotes (quote_id, client_id, status, subtotal, tax_amount, grand_total, total_amount, "
                "included_charges) VALUES ('q-cost', %s, 'Invoiced', 1520, 273.6, 1793.6, 1793.6, "
                "'{\"supervision\": false, \"admin\": false, \"insurance\": false, \"transport\": false, \"contingency\": false}') ",
                (cid,))
    cur.execute("INSERT INTO quote_items (quote_id, product_id, product_name, quantity, unit_price) VALUES "
                "('q-cost', %s, 'Viga', 10, 100), ('q-cost', %s, 'Plancha', 4, 50), ('q-cost', NULL, 'Montaje', 1, 300), "
                "('q-cost', %s, 'Sin costo', 2, 10)", (p1, p2, p3))
    cur.execute("INSERT INTO projects (client_id, name, start_date, quote_id) VALUES (%s, 'Nave Costos', '2026-10-01', 'q-cost') "
                "RETURNING id", (cid,))
    pid = cur.fetchone()["id"]
    cur.execute("INSERT INTO invoices (invoice_number, quote_id, client_id, status, total_amount, itbis_total, invoice_date) "
                "VALUES ('F-C', 'q-cost', %s, 'Pending', 1793.6, 273.6, '2026-10-05')", (cid,))
    cur.execute("INSERT INTO expenses (date, category, amount, project_id) VALUES ('2026-10-06', 'Materiales', 900, %s)", (pid,))
    conn.commit()
    conn.close()
    return {"pid": pid, "p1": p1, "p3": p3, "cid": cid}


@needs_db
def test_product_cost_crud(db):
    r = client.post("/products/", json={"name": "Codo", "unit_price": 3650, "cost": 2100.5}, headers=_hdr())
    assert r.status_code == 200 and r.json()["data"]["cost"] == 2100.5
    pid = r.json()["data"]["id"]
    assert client.get(f"/products/{pid}", headers=_hdr()).json()["data"]["cost"] == 2100.5
    assert client.put(f"/products/{pid}", json={"name": "Codo", "unit_price": 3700}, headers=_hdr()).json()["data"]["cost"] == 2100.5
    assert client.put(f"/products/{pid}", json={"name": "Codo", "unit_price": 3700, "cost": 2200}, headers=_hdr()).json()["data"]["cost"] == 2200.0
    listed = {p["id"]: p for p in client.get("/products/", headers=_hdr()).json()["data"]}
    assert listed[pid]["cost"] == 2200.0 and listed[db["p3"]]["cost"] is None


@needs_db
def test_quote_estimate_does_not_touch_totals(db):
    e = client.get("/quotes/q-cost/cost-estimate", headers=_hdr()).json()["data"]
    assert e["subtotal"] == 1520.0
    assert e["estimated_cost"] == 720.0                     # 10*60 + 4*30; service and no-cost lines excluded
    assert e["estimated_margin"] == 800.0
    assert e["estimated_margin_pct"] == round(800 / 1520 * 100, 2)
    assert (e["lines_total"], e["lines_costed"]) == (4, 2)
    assert client.get("/quotes/nope/cost-estimate", headers=_hdr()).status_code == 404
    import psycopg2
    with psycopg2.connect(DSN) as c, c.cursor() as cur:
        cur.execute("SELECT subtotal, grand_total, total_amount FROM quotes WHERE quote_id='q-cost'")
        assert [float(x) for x in cur.fetchone()] == [1520.0, 1793.6, 1793.6]


@needs_db
def test_preview_estimate(db):
    body = {"items": [{"product_id": db["p1"], "product_name": "Viga", "quantity": 2, "unit_price": 100}],
            "included_charges": {"supervision": True, "supervision_percentage": 10, "admin": False, "insurance": False,
                                 "transport": False, "contingency": False}}
    e = client.post("/quotes/cost-estimate/preview", json=body, headers=_hdr()).json()["data"]
    assert e["subtotal"] == 220.0 and e["estimated_cost"] == 120.0 and e["estimated_margin"] == 100.0


@needs_db
def test_project_estimated_vs_actual(db):
    d = client.get(f"/projects/{db['pid']}/cost-estimate", headers=_hdr()).json()["data"]
    assert d["estimated_cost"] == 720.0 and d["expenses_total"] == 900.0
    assert d["variance"] == -180.0 and d["variance_pct"] == -25.0
    assert d["billed_net"] == 1520.0
    assert d["estimated_margin"] == 800.0 and d["actual_margin"] == 620.0
    assert d["margin_accuracy_pct"] == 77.5
    assert client.get("/projects/9999/cost-estimate", headers=_hdr()).status_code == 404


@needs_db
def test_reports(db):
    pp = client.get("/reports/product-profitability", headers=_hdr()).json()["data"]
    viga = [p for p in pp["products"] if p["name"] == "Viga"][0]
    assert (viga["unit_price"], viga["cost"], viga["margin"], viga["margin_pct"]) == (100.0, 60.0, 40.0, 40.0)
    assert pp["summary"]["with_cost"] == 2 and pp["summary"]["without_cost"] == 1
    only = client.get("/reports/product-profitability?only_with_cost=true", headers=_hdr()).json()["data"]
    assert len(only["products"]) == 2
    pv = client.get("/reports/project-variance", headers=_hdr()).json()["data"]
    row = pv["projects"][0]
    assert (row["estimated_cost"], row["expenses"], row["variance"], row["margin_accuracy_pct"]) == (720.0, 900.0, -180.0, 77.5)
    assert row["coverage_pct"] == 50.0 and pv["summary"]["incomplete_estimates"] == 1
