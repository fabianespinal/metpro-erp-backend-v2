"""Step 3: projects and users handlers return generic 500 detail, never exception text."""
import importlib
import os
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

SECRET_TEXT = "password authentication failed for user postgres.abc123 at 10.0.0.5"


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("EXPOSE_ERROR_DETAIL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)


def _broken_db(*args, **kwargs):
    raise RuntimeError(SECRET_TEXT)


def _assert_generic(exc_info, expected_context):
    err = exc_info.value
    assert isinstance(err, HTTPException)
    assert err.status_code == 500
    assert err.detail == expected_context
    assert SECRET_TEXT not in str(err.detail)
    assert "RuntimeError" not in str(err.detail)


# ---------- service layer ----------

@pytest.mark.parametrize("func_name, args, context", [
    ("delete_project", (1,), "No se pudo eliminar"),
])
def test_projects_service_returns_generic_detail(monkeypatch, func_name, args, context):
    import projects.service as ps

    monkeypatch.setattr(ps, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        getattr(ps, func_name)(*args)

    _assert_generic(exc_info, context)


@pytest.mark.parametrize("func_name, args, context", [
    ("delete_user", ("1",), "No se pudo eliminar el usuario"),
])
def test_users_service_returns_generic_detail(monkeypatch, func_name, args, context):
    import users.service as us

    monkeypatch.setattr(us, "get_db_connection", _broken_db)

    with pytest.raises(HTTPException) as exc_info:
        getattr(us, func_name)(*args)

    _assert_generic(exc_info, context)


# ---------- router layer ----------

def test_projects_router_delete_returns_generic_detail(monkeypatch):
    pr = importlib.import_module("projects.router")

    def _boom(*args, **kwargs):
        raise RuntimeError(SECRET_TEXT)

    monkeypatch.setattr(pr.service, "delete_project", _boom)

    with pytest.raises(HTTPException) as exc_info:
        pr.delete_project(1, current_user={"sub": "tester"})

    _assert_generic(exc_info, "No se pudo eliminar")


def test_projects_router_get_all_returns_generic_detail(monkeypatch):
    pr = importlib.import_module("projects.router")

    def _boom(*args, **kwargs):
        raise RuntimeError(SECRET_TEXT)

    monkeypatch.setattr(pr.service, "get_all_projects", _boom)

    with pytest.raises(HTTPException) as exc_info:
        pr.get_projects(None, None)

    _assert_generic(exc_info, "No se pudo obtener la información")


def test_no_str_e_left_in_step3_files():
    here = os.path.join(os.path.dirname(__file__), "..")
    for rel in ("projects/router.py", "projects/service.py", "users/service.py"):
        with open(os.path.join(here, rel), encoding="utf-8") as fh:
            assert "str(e)" not in fh.read(), rel
