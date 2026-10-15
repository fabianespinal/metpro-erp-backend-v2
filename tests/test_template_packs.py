"""Template packs (quoting v1, phase 2).

Writes (create/update/delete) are admin-only. Reads are open to any
authenticated user. Service layer is mocked here; SQL is checked separately.
"""
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
from core.errors import api_error  # noqa: E402
from main import app  # noqa: E402

svc = importlib.import_module("template_packs.service")

PACK_BODY = {
    "name": "Warehouse Build",
    "description": "Materials for a warehouse",
    "categories": [
        {
            "name": "Steel",
            "sort_order": 1,
            "items": [
                {"product_id": 10, "default_qty": 4, "optional": False, "sort_order": 1},
                {"product_id": 11, "default_qty": 2, "optional": True, "sort_order": 2},
            ],
        }
    ],
}

PACK_OUT = {
    "id": 1,
    "name": "Warehouse Build",
    "description": "Materials for a warehouse",
    "categories": [
        {
            "id": 5,
            "name": "Steel",
            "sort_order": 1,
            "items": [
                {"id": 7, "product_id": 10, "product_name": "Beam", "unit_price": 12.5,
                 "default_qty": 4, "optional": False, "sort_order": 1},
            ],
        }
    ],
    "created_at": None,
    "updated_at": None,
}


def _data(resp):
    """Success responses are wrapped as {"data": ..., "success": true} (core/responses.py)."""
    body = resp.json()
    assert body["success"] is True
    return body["data"]


def _token(role):
    return create_access_token({"sub": f"{role}-user", "user_id": 1, "role": role})


def _auth(role):
    return {"Authorization": f"Bearer {_token(role)}"}


@pytest.fixture
def client(monkeypatch):
    # Bypass the DB active-user lookup; role and validation are what is under test.
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    return TestClient(app)


# ----------------------------
# Auth: reads
# ----------------------------

def test_list_requires_auth(client):
    resp = client.get("/template-packs/")
    assert resp.status_code == 401


def test_list_allowed_for_any_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(svc, "list_packs", lambda: [
        {"id": 1, "name": "Warehouse Build", "description": None,
         "category_count": 1, "item_count": 2, "updated_at": None}
    ])
    resp = client.get("/template-packs/", headers=_auth("user"))
    assert resp.status_code == 200
    assert _data(resp)[0]["item_count"] == 2


def test_get_allowed_for_any_authenticated_user(client, monkeypatch):
    monkeypatch.setattr(svc, "get_pack", lambda pack_id: PACK_OUT)
    resp = client.get("/template-packs/1", headers=_auth("user"))
    assert resp.status_code == 200
    assert _data(resp)["categories"][0]["items"][0]["product_name"] == "Beam"


def test_get_missing_pack_returns_404_with_code(client, monkeypatch):
    def _missing(pack_id):
        raise api_error(404, "Template pack not found", "TEMPLATE_PACK_NOT_FOUND")
    monkeypatch.setattr(svc, "get_pack", _missing)
    resp = client.get("/template-packs/999", headers=_auth("user"))
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Template pack not found"


# ----------------------------
# Auth: writes are admin only
# ----------------------------

@pytest.mark.parametrize("method, path, body", [
    ("POST", "/template-packs/", PACK_BODY),
    ("PUT", "/template-packs/1", PACK_BODY),
    ("DELETE", "/template-packs/1", None),
])
def test_non_admin_writes_forbidden(client, monkeypatch, method, path, body):
    called = []
    for name in ("create_pack", "update_pack", "delete_pack"):
        monkeypatch.setattr(svc, name, lambda *a, **k: called.append(a) or PACK_OUT)
    resp = client.request(method, path, json=body, headers=_auth("user"))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Insufficient permissions"
    assert called == []


@pytest.mark.parametrize("method, path, body", [
    ("POST", "/template-packs/", PACK_BODY),
    ("PUT", "/template-packs/1", PACK_BODY),
])
def test_writes_require_auth(client, method, path, body):
    resp = client.request(method, path, json=body)
    assert resp.status_code == 401


def test_admin_create_allowed(client, monkeypatch):
    monkeypatch.setattr(svc, "create_pack", lambda data: PACK_OUT)
    resp = client.post("/template-packs/", json=PACK_BODY, headers=_auth("admin"))
    assert resp.status_code == 200
    assert _data(resp)["id"] == 1


def test_admin_update_allowed(client, monkeypatch):
    monkeypatch.setattr(svc, "update_pack", lambda pack_id, data: PACK_OUT)
    resp = client.put("/template-packs/1", json=PACK_BODY, headers=_auth("admin"))
    assert resp.status_code == 200


def test_admin_delete_allowed(client, monkeypatch):
    monkeypatch.setattr(svc, "delete_pack", lambda pack_id: {"message": "Template pack deleted", "id": pack_id})
    resp = client.delete("/template-packs/1", headers=_auth("admin"))
    assert resp.status_code == 200
    assert _data(resp)["id"] == 1


# ----------------------------
# Validation
# ----------------------------

@pytest.mark.parametrize("mutate", [
    lambda b: b.update({"name": ""}),
    lambda b: b["categories"][0]["items"][0].update({"default_qty": 0}),
    lambda b: b["categories"][0]["items"][0].update({"default_qty": -1}),
    lambda b: b["categories"][0]["items"][0].update({"product_id": 0}),
    lambda b: b["categories"][0].update({"name": ""}),
])
def test_invalid_payload_rejected(client, monkeypatch, mutate):
    called = []
    monkeypatch.setattr(svc, "create_pack", lambda data: called.append(data) or PACK_OUT)
    body = __import__("copy").deepcopy(PACK_BODY)
    mutate(body)
    resp = client.post("/template-packs/", json=body, headers=_auth("admin"))
    assert resp.status_code == 422
    assert called == []


def test_pack_without_categories_is_valid(client, monkeypatch):
    monkeypatch.setattr(svc, "create_pack", lambda data: {**PACK_OUT, "categories": []})
    resp = client.post("/template-packs/", json={"name": "Empty"}, headers=_auth("admin"))
    assert resp.status_code == 200


def test_unknown_product_rejected_with_code(client, monkeypatch):
    def _bad(data):
        raise api_error(400, "Products not found: 10", "TEMPLATE_PRODUCT_NOT_FOUND")
    monkeypatch.setattr(svc, "create_pack", _bad)
    resp = client.post("/template-packs/", json=PACK_BODY, headers=_auth("admin"))
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Products not found: 10"


# ----------------------------
# Route wiring
# ----------------------------

def test_router_is_mounted():
    paths = {r.path for r in app.routes}
    assert "/template-packs/" in paths
    assert "/template-packs/{pack_id}" in paths
