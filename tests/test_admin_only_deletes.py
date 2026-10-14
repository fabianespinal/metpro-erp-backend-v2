"""Item 5: delete routes for clients, products, quotes, and invoices require admin.

Create and update routes keep require_auth. Single-tenant: no ownership checks.
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
from main import app  # noqa: E402

DELETE_CASES = [
    # (router module, endpoint name, service module)
    ("clients.router", "delete_client", "clients.service"),
    ("products.router", "delete_product", "products.service"),
    ("quotes.router", "delete_quote", "quotes.service"),
    ("invoices.router", "delete_invoice", "invoices.service"),
]

CREATE_UPDATE_CASES = [
    ("clients.router", "create_client"),
    ("clients.router", "update_client"),
    ("products.router", "create_product"),
    ("products.router", "update_product"),
    ("quotes.router", "create_quote"),
    ("quotes.router", "update_quote"),
    ("invoices.router", "create_invoice"),
]


def _find_route(module, name):
    matches = [
        r for r in app.routes
        if getattr(r, "endpoint", None) is not None
        and r.endpoint.__module__ == module
        and r.endpoint.__name__ == name
    ]
    assert len(matches) == 1, (module, name, len(matches))
    return matches[0]


def _all_dep_names(route):
    out = []

    def walk(dep):
        for d in dep.dependencies:
            out.append(getattr(d.call, "__name__", ""))
            walk(d)

    walk(route.dependant)
    return out


def _dep_names(route):
    return [d.call.__name__ for d in route.dependant.dependencies if d.call is not None]


def _sample_path(route):
    import re
    return re.sub(r"\{[^}]+\}", "1", route.path)


def _token(role):
    return create_access_token({"sub": f"{role}-user", "user_id": 1, "role": role})


@pytest.fixture
def client(monkeypatch):
    # Bypass the DB active-user lookup; role checks are what is under test.
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    return TestClient(app)


@pytest.mark.parametrize("module, name, _svc", DELETE_CASES)
def test_delete_routes_use_require_role_admin(module, name, _svc):
    route = _find_route(module, name)
    assert route.dependant.dependencies, name
    names = _dep_names(route)
    assert "wrapper" in names, (name, names)
    assert "require_auth" in _all_dep_names(route), (name, _all_dep_names(route))


@pytest.mark.parametrize("module, name", CREATE_UPDATE_CASES)
def test_create_and_update_routes_unchanged(module, name):
    route = _find_route(module, name)
    assert "require_auth" in _dep_names(route), (name, _dep_names(route))


@pytest.mark.parametrize("module, name, svc_module", DELETE_CASES)
def test_non_admin_delete_is_forbidden(client, monkeypatch, module, name, svc_module):
    svc = importlib.import_module(svc_module)
    called = []
    monkeypatch.setattr(svc, name, lambda *a, **k: called.append(a) or {"deleted": True})

    route = _find_route(module, name)
    resp = client.request(
        "DELETE",
        _sample_path(route),
        headers={"Authorization": f"Bearer {_token('user')}"},
    )

    assert resp.status_code == 403
    assert resp.json()["detail"] == "Insufficient permissions"
    assert called == []


@pytest.mark.parametrize("module, name, svc_module", DELETE_CASES)
def test_admin_delete_is_allowed(client, monkeypatch, module, name, svc_module):
    svc = importlib.import_module(svc_module)
    monkeypatch.setattr(svc, name, lambda *a, **k: {"deleted": True})

    route = _find_route(module, name)
    resp = client.request(
        "DELETE",
        _sample_path(route),
        headers={"Authorization": f"Bearer {_token('admin')}"},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": True}
