"""Item 9, module 1: unified error model. Shape is {"detail": str, "code": str}.

Covers the handlers in core/errors.py. Route-level messages are not changed here.
"""
import logging
import os
import sys

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.errors import error_code_for, register_error_handlers  # noqa: E402


class _Body(BaseModel):
    name: str
    count: int


def _build_app():
    app = FastAPI()
    register_error_handlers(app)

    class _Custom(HTTPException):
        def __init__(self):
            super().__init__(status_code=409, detail="Already exists")
            self.code = "CLIENT_DUPLICATE"

    @app.get("/not-found")
    def not_found():
        raise HTTPException(status_code=404, detail="Client not found")

    @app.get("/custom")
    def custom():
        raise _Custom()

    @app.get("/headers")
    def with_headers():
        raise HTTPException(status_code=429, detail="Too many requests", headers={"Retry-After": "7"})

    @app.get("/boom")
    def boom():
        raise RuntimeError("password authentication failed for user postgres.abc123")

    @app.post("/items")
    def items(body: _Body):
        return body

    return app


@pytest.fixture
def client():
    return TestClient(_build_app())


def test_http_exception_has_detail_and_code(client):
    resp = client.get("/not-found")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Client not found", "code": "NOT_FOUND"}


def test_explicit_code_attribute_wins(client):
    resp = client.get("/custom")
    assert resp.status_code == 409
    assert resp.json() == {"detail": "Already exists", "code": "CLIENT_DUPLICATE"}


def test_headers_are_preserved(client):
    resp = client.get("/headers")
    assert resp.status_code == 429
    assert resp.json() == {"detail": "Too many requests", "code": "RATE_LIMITED"}
    assert resp.headers["Retry-After"] == "7"


def test_validation_error_uses_same_shape(client):
    resp = client.post("/items", json={"name": "x"})
    assert resp.status_code == 422
    body = resp.json()
    assert set(body.keys()) == {"detail", "code"}
    assert body["code"] == "VALIDATION_ERROR"
    assert isinstance(body["detail"], str)
    assert "count" in body["detail"]


def test_unhandled_exception_returns_generic_body_and_logs(caplog):
    client = TestClient(_build_app(), raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="core.errors"):
        resp = client.get("/boom")
    assert resp.status_code == 500
    assert resp.json() == {"detail": "Internal server error", "code": "INTERNAL_ERROR"}
    assert "postgres" not in resp.text
    assert "password" not in resp.text
    assert any("RuntimeError" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("status, expected", [
    (400, "BAD_REQUEST"),
    (401, "UNAUTHORIZED"),
    (403, "FORBIDDEN"),
    (404, "NOT_FOUND"),
    (409, "CONFLICT"),
    (422, "VALIDATION_ERROR"),
    (429, "RATE_LIMITED"),
    (500, "INTERNAL_ERROR"),
    (418, "HTTP_ERROR"),
])
def test_status_to_code_mapping(status, expected):
    assert error_code_for(status) == expected


def test_explicit_code_overrides_mapping():
    assert error_code_for(404, "CLIENT_MISSING") == "CLIENT_MISSING"


def test_existing_login_shape_keeps_detail_string():
    """The login 401 message clients read today must still be a plain string in detail."""
    from main import app
    client = TestClient(app)
    resp = client.post("/auth/login", json={"username": "nobody", "password": "x"})
    body = resp.json()
    assert isinstance(body["detail"], str)
    assert "code" in body
