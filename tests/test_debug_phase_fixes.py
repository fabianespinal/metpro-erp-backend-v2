"""Debug phase (2026-10-18) regressions: terms PUT shape, project delete gating, client IP source."""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402  (import order: avoids a circular import via pdf)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from core import rate_limit as rl  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)


def _hdr(role):
    token = create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})
    return {"Authorization": f"Bearer {token}"}


def _active(monkeypatch):
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda username: None)


# ---- Terms: PUT returns the same shape as GET (the editor crashed on save) ----

def test_terms_put_returns_order_titles_defaults(monkeypatch):
    _active(monkeypatch)
    saved = {"enabled_quote": True, "enabled_invoice": False, "sections": {"legal": "x"},
             "is_default": False, "updated_at": None, "updated_by": "t_admin"}
    monkeypatch.setattr("terms_page.service.save_settings", lambda *a, **k: dict(saved))
    monkeypatch.setattr("terms_page.service.get_settings", lambda: dict(saved))
    put = client.put("/terms/", json={"sections": {"legal": "x"}, "enabled_quote": True}, headers=_hdr("admin"))
    get = client.get("/terms/", headers=_hdr("admin"))
    assert put.status_code == 200 and get.status_code == 200
    p, g = put.json()["data"], get.json()["data"]
    for key in ("order", "titles", "defaults", "sections", "enabled_quote"):
        assert key in p, key
    assert set(p) == set(g)


# ---- Projects: delete is admin only, like the other deletes ----

def test_project_delete_forbidden_for_user(monkeypatch):
    _active(monkeypatch)
    called = []
    monkeypatch.setattr("projects.service.delete_project", lambda pid: called.append(pid) or {"message": "ok"})
    r = client.delete("/projects/1", headers=_hdr("user"))
    assert r.status_code == 403
    assert called == []


def test_project_delete_allowed_for_admin_and_superadmin(monkeypatch):
    _active(monkeypatch)
    monkeypatch.setattr("projects.service.delete_project", lambda pid: {"message": "ok"})
    for role in ("admin", "superadmin"):
        assert client.delete("/projects/1", headers=_hdr(role)).status_code == 200


# ---- Client IP: Railway's X-Real-IP wins over the forwarded chain ----

class _Req:
    def __init__(self, headers, host="10.0.0.2"):
        self.headers = headers
        self.client = type("C", (), {"host": host})()


def test_client_ip_prefers_x_real_ip():
    req = _Req({"x-real-ip": "68.237.111.150", "x-forwarded-for": "68.237.111.150, 152.233.47.67"})
    assert rl.client_ip(req) == "68.237.111.150"


def test_client_ip_without_real_ip_keeps_previous_rule():
    assert rl.client_ip(_Req({"x-forwarded-for": "6.6.6.6, 203.0.113.9"})) == "203.0.113.9"
    assert rl.client_ip(_Req({}, host="198.51.100.7")) == "198.51.100.7"
    assert rl.client_ip(_Req({"x-real-ip": "  "}, host="198.51.100.8")) == "198.51.100.8"
