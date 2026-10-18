"""Item 10, module 2: every JSON success response is {"data": payload, "success": true}.

Payloads are unchanged inside data. Errors, PDFs, streams, and empty bodies are not wrapped.
"""
import importlib
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.responses import apply_success_envelope  # noqa: E402
from main import app  # noqa: E402


def _mini():
    from core.errors import register_error_handlers
    mini = FastAPI()
    register_error_handlers(mini)

    @mini.get("/dict")
    def get_dict():
        return {"id": 1, "nested": {"a": [1, {"b": None}]}}

    @mini.get("/list")
    def get_list():
        return [1, "two", 3.5]

    @mini.get("/none")
    def get_none():
        return None

    @mini.post("/created", status_code=201)
    def created():
        return {"id": 9}

    @mini.get("/headers")
    def with_header():
        return JSONResponse({"x": 1}, headers={"X-Trace": "abc"})

    @mini.get("/pdf")
    def pdf():
        return StreamingResponse(iter([b"%PDF-1.4"]), media_type="application/pdf")

    @mini.get("/bytes")
    def raw():
        return Response(content=b"plain", media_type="text/plain")

    @mini.delete("/nocontent", status_code=204)
    def nocontent():
        return Response(status_code=204)

    @mini.get("/missing")
    def missing():
        raise HTTPException(status_code=404, detail="Gone")

    apply_success_envelope(mini)
    return mini


@pytest.fixture
def mini_client():
    return TestClient(_mini())


def test_dict_payload_wrapped_unchanged(mini_client):
    resp = mini_client.get("/dict")
    assert resp.status_code == 200
    assert resp.json() == {"data": {"id": 1, "nested": {"a": [1, {"b": None}]}}, "success": True}


def test_list_payload_wrapped(mini_client):
    assert mini_client.get("/list").json() == {"data": [1, "two", 3.5], "success": True}


def test_none_payload_wrapped(mini_client):
    assert mini_client.get("/none").json() == {"data": None, "success": True}


def test_status_201_preserved(mini_client):
    resp = mini_client.post("/created")
    assert resp.status_code == 201
    assert resp.json() == {"data": {"id": 9}, "success": True}


def test_custom_header_preserved(mini_client):
    resp = mini_client.get("/headers")
    assert resp.json() == {"data": {"x": 1}, "success": True}
    assert resp.headers["X-Trace"] == "abc"


def test_pdf_stream_not_wrapped(mini_client):
    resp = mini_client.get("/pdf")
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content == b"%PDF-1.4"


def test_plain_bytes_not_wrapped(mini_client):
    resp = mini_client.get("/bytes")
    assert resp.content == b"plain"
    assert resp.headers["content-type"].startswith("text/plain")


def test_204_not_wrapped(mini_client):
    resp = mini_client.delete("/nocontent")
    assert resp.status_code == 204
    assert resp.content == b""


def test_error_not_wrapped(mini_client):
    resp = mini_client.get("/missing")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Gone", "code": "NOT_FOUND"}
    assert "success" not in resp.json()


def test_apply_is_idempotent():
    mini = _mini()
    assert apply_success_envelope(mini) == 0


# ---------- real app ----------

def test_every_app_route_is_wrapped():
    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    assert routes
    assert all(getattr(r, "_success_envelope", False) for r in routes)


def test_health_wrapped():
    resp = TestClient(app).get("/health")
    assert resp.json() == {"data": {"status": "healthy"}, "success": True}


def test_root_wrapped():
    resp = TestClient(app).get("/")
    body = resp.json()
    assert body["success"] is True
    assert body["data"]["message"] == "¡La API de METPRO ERP está en funcionamiento!"
    assert body["data"]["version"] == "2.0.0"


def test_options_login_wrapped():
    resp = TestClient(app).options("/auth/login")
    assert resp.json() == {"data": {"message": "OK"}, "success": True}


class _Seq:
    def __init__(self, rows):
        self._rows = list(rows)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def close(self):
        pass


class _Conn:
    def __init__(self, rows):
        self._cursor = _Seq(rows)

    def cursor(self, *a, **k):
        return self._cursor

    def close(self):
        pass


def test_login_success_token_moves_under_data(monkeypatch):
    ar = importlib.import_module("auth.router")
    svc = importlib.import_module("auth.service")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    row = {"id": 1, "username": "admin", "password_hash": svc.get_password_hash("pw"),
           "is_active": True, "role": "admin"}
    monkeypatch.setattr(ar, "get_db_connection", lambda: _Conn([row]))

    resp = TestClient(app).post("/auth/login", json={"username": "admin", "password": "pw"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert set(body) == {"data", "success"}
    assert "access_token" not in body
    assert body["data"]["username"] == "admin"
    assert body["data"]["token_type"] == "bearer"
    assert isinstance(body["data"]["access_token"], str) and body["data"]["access_token"]


def test_login_failure_stays_error_shape(monkeypatch):
    ar = importlib.import_module("auth.router")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setattr(ar, "get_db_connection", lambda: _Conn([]))
    resp = TestClient(app).post("/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Usuario o contraseña incorrectos", "code": "INVALID_CREDENTIALS"}


def test_authenticated_success_wrapped(monkeypatch):
    import database
    from jose import jwt
    import time
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn([{"is_active": True}]))
    tok = jwt.encode({"sub": "alice", "role": "admin", "exp": int(time.time()) + 600},
                     "test-secret-key", algorithm="HS256")
    resp = TestClient(app).get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert resp.json() == {"data": {"username": "alice", "user_id": None, "role": "admin", "name": None}, "success": True}
