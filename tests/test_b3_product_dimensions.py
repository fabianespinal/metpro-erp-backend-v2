"""B3 Product dimensions: one additive migration, optional fields, switch-gated writes."""
import importlib
import os
import re
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
FIELDS = ("length", "width", "height", "thickness", "area", "volume", "unit_of_measure")
DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


def _hdr():
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": "t_user", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})}


def _sql(name):
    lines = open(os.path.join(ROOT, "migrations", name), encoding="utf-8").read().splitlines()
    return re.sub(r"\s+", " ", "\n".join(l.split("--")[0] for l in lines)).upper()


def test_one_migration_defines_every_field_and_changes_nothing_else():
    sql = _sql("2026-10-22_product_dimensions.sql")
    for f in FIELDS:
        assert f"ADD COLUMN IF NOT EXISTS {f.upper()} " in sql, f
    for forbidden in ("DROP ", "DELETE FROM", "UPDATE ", "TRUNCATE", "NOT NULL", "DEFAULT"):
        assert forbidden not in sql.replace("IF NOT EXISTS", ""), forbidden
    assert "NOT EXISTS (SELECT 1 FROM PG_CONSTRAINT" in sql  # idempotent constraints


def test_rollback_refuses_when_data_exists():
    sql = _sql("2026-10-22_product_dimensions.rollback.sql")
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN")
    for f in FIELDS:
        assert f"{f.upper()} IS NOT NULL" in sql


def test_model_validates_and_marks_which_fields_were_sent():
    from pydantic import ValidationError
    from products.models import ProductBase
    p = ProductBase(name="x", unit_price=1, width=2.5)
    assert p.model_fields_set >= {"width"} and "length" not in p.model_fields_set
    for bad in ({"length": -1}, {"area": float("nan")}, {"unit_of_measure": ""}, {"unit_of_measure": "x" * 21}):
        with pytest.raises(ValidationError):
            ProductBase(name="x", unit_price=1, **bad)


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "products.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("PRODUCT_DIMENSIONS_ENABLED", "true")
    conn = connect()
    conn.cursor().execute("TRUNCATE products RESTART IDENTITY CASCADE")
    conn.commit()
    conn.close()
    return connect


def _row(connect, pid):
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM products WHERE id = %s", (pid,))
        return cur.fetchone()
    finally:
        conn.close()


@needs_db
def test_create_without_dimensions_works_with_the_switch_off(db, monkeypatch):
    monkeypatch.setenv("PRODUCT_DIMENSIONS_ENABLED", "false")
    r = client.post("/products/", json={"name": "Plancha", "unit_price": 10}, headers=_hdr())
    assert r.status_code == 200, r.text
    assert all(r.json()["data"][f] is None for f in FIELDS) if "data" in r.json() else all(r.json()[f] is None for f in FIELDS)


def _body(r):
    j = r.json()
    return j["data"] if isinstance(j, dict) and "data" in j and "id" not in j else j


@needs_db
def test_create_and_update_store_dimensions_as_entered(db):
    r = client.post("/products/", json={"name": "Plancha", "unit_price": 10, "length": 2.44, "width": 1.22,
                                         "thickness": 0.0125, "area": 2.9768, "unit_of_measure": "m"}, headers=_hdr())
    assert r.status_code == 200, r.text
    pid = _body(r)["id"]
    row = _row(db, pid)
    assert float(row["length"]) == 2.44 and float(row["thickness"]) == 0.0125 and row["unit_of_measure"] == "m"
    assert row["height"] is None and row["volume"] is None  # nothing derived
    # Update that omits dimensions keeps them; one that sends a field changes only it; null clears it.
    base = {"name": "Plancha", "unit_price": 12}
    assert client.put(f"/products/{pid}", json=base, headers=_hdr()).status_code == 200
    assert float(_row(db, pid)["length"]) == 2.44
    assert client.put(f"/products/{pid}", json={**base, "height": 3}, headers=_hdr()).status_code == 200
    row = _row(db, pid)
    assert float(row["height"]) == 3 and float(row["length"]) == 2.44
    assert client.put(f"/products/{pid}", json={**base, "length": None}, headers=_hdr()).status_code == 200
    assert _row(db, pid)["length"] is None and float(_row(db, pid)["width"]) == 1.22


@needs_db
def test_switch_off_refuses_dimension_writes_but_reads_stay(db, monkeypatch):
    pid = _body(client.post("/products/", json={"name": "P", "unit_price": 1, "width": 4}, headers=_hdr()))["id"]
    monkeypatch.setenv("PRODUCT_DIMENSIONS_ENABLED", "false")
    r = client.put(f"/products/{pid}", json={"name": "P", "unit_price": 1, "width": 9}, headers=_hdr())
    assert r.status_code == 400 and r.json()["code"] == "PRODUCT_DIMENSIONS_DISABLED"
    assert float(_row(db, pid)["width"]) == 4
    assert client.put(f"/products/{pid}", json={"name": "P2", "unit_price": 1}, headers=_hdr()).status_code == 200
    got = _body(client.get(f"/products/{pid}", headers=_hdr()))
    assert float(got["width"]) == 4


@needs_db
def test_failed_dimension_write_rolls_back_the_whole_update(db, monkeypatch):
    pid = _body(client.post("/products/", json={"name": "Old", "unit_price": 1}, headers=_hdr()))["id"]
    monkeypatch.setenv("PRODUCT_DIMENSIONS_ENABLED", "false")
    client.put(f"/products/{pid}", json={"name": "New", "unit_price": 5, "width": 9}, headers=_hdr())
    row = _row(db, pid)
    assert row["name"] == "Old" and float(row["unit_price"]) == 1


@needs_db
def test_options_endpoint_and_db_check(db, monkeypatch):
    assert _body(client.get("/products/options", headers=_hdr())) == {"dimensions_enabled": True}
    monkeypatch.setenv("PRODUCT_DIMENSIONS_ENABLED", "false")
    assert _body(client.get("/products/options", headers=_hdr())) == {"dimensions_enabled": False}
    import psycopg2
    conn = db()
    try:
        with pytest.raises(psycopg2.errors.CheckViolation):
            conn.cursor().execute("INSERT INTO products (name, length) VALUES ('neg', -1)")
    finally:
        conn.rollback()
        conn.close()
