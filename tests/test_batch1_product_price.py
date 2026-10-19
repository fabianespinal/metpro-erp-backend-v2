"""Debug pass B-01: product prices and costs must be finite and non-negative.

A NaN price stored in products made GET /products/ fail for every user.
"""
import asyncio
import importlib
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

psvc = importlib.import_module("products.service")
client = TestClient(app)


def _hdr():
    token = create_access_token({"sub": "t_user", "role": "user", "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), -0.01])
def test_model_rejects_bad_price_and_cost(bad):
    with pytest.raises(ValidationError):
        ProductBase(name="Viga", unit_price=bad)
    with pytest.raises(ValidationError):
        ProductBase(name="Viga", unit_price=10, cost=bad)


def test_model_accepts_valid_values():
    assert ProductBase(name="Viga", unit_price=0).unit_price == 0
    assert ProductBase(name="Viga", unit_price=95.5, cost=60).cost == 60
    assert ProductBase(name="Viga", unit_price=95.5, cost=None).cost is None


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-1"])
def test_api_rejects_bad_price(monkeypatch, raw):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    called = []
    monkeypatch.setattr(psvc, "create_product", lambda *a, **k: called.append(a))
    body = '{"name": "Viga", "unit_price": %s}' % raw
    for method, path in (("POST", "/products/"), ("PUT", "/products/1")):
        r = client.request(method, path, content=body, headers=_hdr())
        assert r.status_code == 422, (method, raw, r.text)
        assert r.json()["code"] == "VALIDATION_ERROR"
    assert called == []


class _Cur:
    def __init__(self):
        self.inserted = []

    def execute(self, sql, params=None):
        if sql.strip().startswith("INSERT"):
            self.inserted.append(params)

    def fetchone(self):
        return None  # no existing product with that name


class _Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def test_csv_skips_nan_inf_and_negative_prices(monkeypatch):
    cur = _Cur()
    monkeypatch.setattr(psvc, "get_db_connection", lambda: _Conn(cur))
    csv_bytes = (
        "name,unit_price,description\n"
        "Valido,95.50,ok\n"
        "Nan,nan,x\n"
        "Inf,inf,x\n"
        "MenosInf,-Infinity,x\n"
        "Negativo,-5,x\n"
        "Cero,0,ok\n"
    ).encode()
    out = asyncio.run(psvc.import_products_from_csv(csv_bytes, "p.csv"))
    assert out == {"imported": 2, "skipped": 4, "total": 6}
    assert [p[0] for p in cur.inserted] == ["Valido", "Cero"]
    assert [p[2] for p in cur.inserted] == [95.5, 0.0]
