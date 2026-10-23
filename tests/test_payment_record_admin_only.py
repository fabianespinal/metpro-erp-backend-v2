"""PAYMENT_RECORD_ADMIN_ONLY: recording a payment is admin/superadmin only when the switch is on (default off)."""
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
import importlib  # noqa: E402
irouter = importlib.import_module("invoices.router")
from auth.service import create_access_token  # noqa: E402
from invoices.payments import service as pay_service  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
BODY = {"amount": 10, "method": "Efectivo", "payment_date": "2026-10-23"}


def _hdr(role):
    token = create_access_token({"sub": "t_" + role, "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setattr(irouter, "get_db_connection", lambda: _Conn())
    monkeypatch.setattr(irouter, "create_payment", lambda conn, iid, data, uid: 77)


class _Conn:
    def rollback(self): pass
    def close(self): pass


def test_switch_defaults_off(monkeypatch):
    monkeypatch.delenv("PAYMENT_RECORD_ADMIN_ONLY", raising=False)
    assert pay_service.payment_record_admin_only() is False
    monkeypatch.setenv("PAYMENT_RECORD_ADMIN_ONLY", "true")
    assert pay_service.payment_record_admin_only() is True


def test_off_any_signed_in_user_can_record(monkeypatch):
    monkeypatch.delenv("PAYMENT_RECORD_ADMIN_ONLY", raising=False)
    r = client.post("/invoices/5/payments", json=BODY, headers=_hdr("user"))
    assert r.status_code == 200


@pytest.mark.parametrize("role,status", [("user", 403), ("manager", 403), ("admin", 200), ("superadmin", 200)])
def test_on_only_admin_and_superadmin(monkeypatch, role, status):
    monkeypatch.setenv("PAYMENT_RECORD_ADMIN_ONLY", "true")
    r = client.post("/invoices/5/payments", json=BODY, headers=_hdr(role))
    assert r.status_code == status, r.text
    if status == 403:
        assert "INSUFFICIENT_PERMISSIONS" in r.text


def test_payment_options_reports_the_switch(monkeypatch):
    monkeypatch.setenv("PAYMENT_RECORD_ADMIN_ONLY", "true")
    body = client.get("/invoices/payment-options", headers=_hdr("user")).json()
    body = body.get("data", body)
    assert body["record_admin_only"] is True
    monkeypatch.delenv("PAYMENT_RECORD_ADMIN_ONLY")
    body = client.get("/invoices/payment-options", headers=_hdr("user")).json()
    assert body.get("data", body)["record_admin_only"] is False
