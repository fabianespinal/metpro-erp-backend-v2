"""Totals preview endpoint (quoting v1, phase 6 prerequisite). Stateless."""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402
from quotes.totals import compute_totals  # noqa: E402

BODY = {
    "items": [
        {"product_name": "IPE", "quantity": 4, "unit_price": 100.0,
         "discount_type": "percentage", "discount_value": 5.0, "item_type": "product"},
        {"product_name": "Survey", "quantity": 1, "unit_price": 250.0,
         "discount_type": "none", "discount_value": 0.0, "item_type": "service"},
    ],
    "included_charges": {"supervision": True, "admin": True, "insurance": False,
                         "transport": True, "contingency": False},
}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    token = create_access_token({"sub": "tester", "role": "user"})
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def test_preview_requires_auth():
    resp = TestClient(app).post("/quotes/totals/preview", json=BODY)
    assert resp.status_code in (401, 403)


def test_preview_matches_compute_totals(client, monkeypatch):
    # No DB: the endpoint must not touch the database at all.
    import quotes.service as svc
    monkeypatch.setattr(svc, "get_db_connection", lambda: (_ for _ in ()).throw(AssertionError("DB touched")))
    resp = client.post("/quotes/totals/preview", json=BODY)
    assert resp.status_code == 200
    data = resp.json()
    data = data.get("data", data)
    items = [dict(i) for i in BODY["items"]]
    exp = compute_totals(items, BODY["included_charges"])
    assert data["grand_total"] == pytest.approx(exp["grand_total"])
    assert data["subtotal"] == pytest.approx(exp["subtotal_general"])
    assert data["tax_rate"] == 0.18


def test_preview_rejects_negative_quantity(client):
    bad = {"items": [dict(BODY["items"][0], quantity=-1)], "included_charges": BODY["included_charges"]}
    resp = client.post("/quotes/totals/preview", json=bad)
    assert resp.status_code == 422
