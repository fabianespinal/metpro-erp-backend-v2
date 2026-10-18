"""P1 security checks: per-request is_active, env-driven JWT expiry, optional pool."""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None


class _FakeConn:
    def __init__(self, rows):
        self._cursor = _FakeCursor(rows)
        self.closed = False

    def cursor(self, *a, **k):
        return self._cursor

    def close(self):
        self.closed = True


@pytest.fixture
def auth(monkeypatch):
    mod = importlib.import_module("auth.service")
    monkeypatch.setattr(mod, "ENFORCE_ACTIVE_CHECK", True)
    return mod


def _patch_db(monkeypatch, rows):
    import database
    conn = _FakeConn(rows)
    monkeypatch.setattr(database, "get_db_connection", lambda: conn)
    return conn


def _bearer(auth, username="alice"):
    return "Bearer " + auth.create_access_token({"sub": username, "role": "admin"})


def test_active_user_is_accepted(auth, monkeypatch):
    _patch_db(monkeypatch, [{"is_active": True}])
    payload = auth.require_auth(_bearer(auth))
    assert payload["sub"] == "alice"


def test_deactivated_user_is_rejected(auth, monkeypatch):
    from fastapi import HTTPException
    _patch_db(monkeypatch, [{"is_active": False}])
    with pytest.raises(HTTPException) as e:
        auth.require_auth(_bearer(auth))
    assert e.value.status_code == 401
    assert e.value.detail == "Cuenta deshabilitada"


def test_deleted_user_is_rejected(auth, monkeypatch):
    from fastapi import HTTPException
    _patch_db(monkeypatch, [])
    with pytest.raises(HTTPException) as e:
        auth.require_auth(_bearer(auth))
    assert e.value.detail == "Usuario no encontrado"


def test_toggle_off_skips_db(auth, monkeypatch):
    monkeypatch.setattr(auth, "ENFORCE_ACTIVE_CHECK", False)
    import database
    called = []
    monkeypatch.setattr(database, "get_db_connection", lambda: called.append(1))
    auth.require_auth(_bearer(auth))
    assert called == []


def test_bearer_flow_also_checks_active(auth, monkeypatch):
    from fastapi import HTTPException
    _patch_db(monkeypatch, [{"is_active": False}])
    tok = auth.create_access_token({"sub": "alice", "role": "admin"})
    with pytest.raises(HTTPException):
        auth.require_auth("Bearer " + tok)


def test_expiry_is_env_driven(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15")
    mod = importlib.reload(importlib.import_module("auth.service"))
    assert mod.ACCESS_TOKEN_EXPIRE_MINUTES == 15
    monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES")
    importlib.reload(mod)


def test_pool_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DB_POOL_ENABLED", raising=False)
    import database
    importlib.reload(database)
    assert database.DB_POOL_ENABLED is False


def test_pooled_close_returns_to_pool():
    import database

    class _Pool:
        def __init__(self):
            self.returned = []

        def putconn(self, conn):
            self.returned.append(conn)

    pool = _Pool()
    raw = object()
    wrapped = database._PooledConnection(pool, raw)
    wrapped.close()
    wrapped.close()  # second close must not return twice
    assert pool.returned == [raw]
