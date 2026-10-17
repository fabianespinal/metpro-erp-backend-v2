"""Per-pack pricing overrides and per-pack dynamic charges (2026-10-17).

API validation through the router (service mocked), plus the service's
pure helpers and SQL shape via a recording cursor.
"""
import copy
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402
from template_packs.models import PackIn  # noqa: E402

svc = importlib.import_module("template_packs.service")

BODY = {
    "name": "Nave Basica",
    "categories": [{"name": "Steel", "items": [
        {"product_id": 10, "default_qty": 4, "pack_price_override": 99.5},
        {"product_id": 11, "default_qty": 1},
    ]}],
    "charges": [
        {"name": "Izaje", "type": "percentage", "value": 5, "enabled_by_default": True},
        {"name": "Permisos", "value": 2.5, "enabled_by_default": False},
    ],
}

OUT = {
    "id": 1, "name": "Nave Basica", "description": None, "created_at": None, "updated_at": None,
    "categories": [{"id": 5, "name": "Steel", "sort_order": 0, "items": [
        {"id": 7, "product_id": 10, "product_name": "Beam", "unit_price": 99.5,
         "catalog_price": 120.0, "pack_price_override": 99.5,
         "default_qty": 4, "optional": False, "sort_order": 0},
    ]}],
    "charges": [{"id": 3, "name": "Izaje", "type": "percentage", "value": 5.0,
                 "enabled_by_default": True, "sort_order": 0}],
}


def _auth(role="admin"):
    tok = create_access_token({"sub": f"{role}-user", "user_id": 1, "role": role})
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    return TestClient(app)


# ---------- API validation ----------

def test_create_with_override_and_charges_accepted(client, monkeypatch):
    seen = []
    monkeypatch.setattr(svc, "create_pack", lambda data: seen.append(data) or OUT)
    resp = client.post("/template-packs/", json=BODY, headers=_auth())
    assert resp.status_code == 200
    data = seen[0]
    assert data.categories[0].items[0].pack_price_override == 99.5
    assert data.categories[0].items[1].pack_price_override is None
    assert [c.name for c in data.charges] == ["Izaje", "Permisos"]
    assert data.charges[1].type == "percentage"
    out = resp.json()["data"]
    assert out["charges"][0]["value"] == 5.0
    assert out["categories"][0]["items"][0]["catalog_price"] == 120.0


@pytest.mark.parametrize("mutate", [
    lambda b: b["categories"][0]["items"][0].update({"pack_price_override": -1}),
    lambda b: b["charges"].extend([{"name": "C", "value": 1}, {"name": "D", "value": 1}]),  # 4 charges
    lambda b: b["charges"][0].update({"type": "fixed"}),
    lambda b: b["charges"][0].update({"value": 101}),
    lambda b: b["charges"][0].update({"value": -0.5}),
    lambda b: b["charges"][0].update({"name": "   "}),
    lambda b: b["charges"][0].update({"name": "x" * 61}),
])
def test_invalid_pricing_or_charges_rejected(client, monkeypatch, mutate):
    called = []
    monkeypatch.setattr(svc, "create_pack", lambda data: called.append(data) or OUT)
    body = copy.deepcopy(BODY)
    mutate(body)
    resp = client.post("/template-packs/", json=body, headers=_auth())
    assert resp.status_code == 422
    assert called == []


def test_legacy_payload_without_new_fields_still_valid():
    data = PackIn(**{"name": "Old", "categories": [{"name": "A", "items": [{"product_id": 1}]}]})
    assert data.charges == []
    assert data.categories[0].items[0].pack_price_override is None


def test_three_charges_allowed():
    body = copy.deepcopy(BODY)
    body["charges"].append({"name": "Third", "value": 1})
    assert len(PackIn(**body).charges) == 3


def test_zero_override_is_kept():
    body = copy.deepcopy(BODY)
    body["categories"][0]["items"][0]["pack_price_override"] = 0
    assert PackIn(**body).categories[0].items[0].pack_price_override == 0


# ---------- effective price ----------

@pytest.mark.parametrize("catalog, override, expected", [
    (120.0, 99.5, 99.5),
    (120.0, None, 120.0),
    (120.0, 0, 0.0),        # explicit zero override wins (free item in the pack)
    (None, None, None),     # product without price
    (None, 50, 50.0),
])
def test_effective_price(catalog, override, expected):
    assert svc._effective_price(catalog, override) == expected


# ---------- SQL shape via a recording cursor ----------

class RecCursor:
    def __init__(self, fetch_queue):
        self.sql = []
        self.fetch_queue = list(fetch_queue)

    def execute(self, q, params=None):
        self.sql.append((" ".join(q.split()), params))

    def fetchone(self):
        return self.fetch_queue.pop(0)

    def fetchall(self):
        return self.fetch_queue.pop(0)


def test_insert_writes_override_and_charges():
    cur = RecCursor([{"id": 50}])
    data = PackIn(**BODY)
    svc._insert_categories(cur, 1, data.categories)
    svc._insert_charges(cur, 1, data.charges)
    item_inserts = [p for q, p in cur.sql if q.startswith("INSERT INTO template_pack_items")]
    assert item_inserts[0][-1] == 99.5 and item_inserts[1][-1] is None
    charge_inserts = [p for q, p in cur.sql if q.startswith("INSERT INTO template_pack_charges")]
    assert charge_inserts == [(1, "Izaje", "percentage", 5.0, True, 0),
                              (1, "Permisos", "percentage", 2.5, False, 1)]


def test_load_pack_returns_effective_price_and_charges():
    cur = RecCursor([
        {"id": 1, "name": "P", "description": None, "created_at": None, "updated_at": None},
        [{"id": 5, "name": "Steel", "sort_order": 0}],
        [
            {"id": 7, "category_id": 5, "product_id": 10, "product_name": "Beam",
             "catalog_price": 120, "pack_price_override": 99.5, "default_qty": 4,
             "optional": False, "sort_order": 0},
            {"id": 8, "category_id": 5, "product_id": 11, "product_name": "Bolt",
             "catalog_price": 3, "pack_price_override": None, "default_qty": 10,
             "optional": True, "sort_order": 1},
        ],
        [{"id": 3, "name": "Izaje", "type": "percentage", "value": 5,
          "enabled_by_default": True, "sort_order": 0}],
    ])
    pack = svc._load_pack(cur, 1)
    items = pack["categories"][0]["items"]
    assert items[0]["unit_price"] == 99.5 and items[0]["catalog_price"] == 120
    assert items[1]["unit_price"] == 3.0 and items[1]["pack_price_override"] is None
    assert pack["charges"][0]["name"] == "Izaje"
    assert any("FROM template_pack_charges" in q for q, _ in cur.sql)
