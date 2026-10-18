"""Set 2, users unblock: NULL-safe model, UUID on create, superadmin protection, DB role.

Scripted fake cursor. No database.
"""
import importlib
import os
import sys
import uuid
from datetime import datetime

import pytest
from fastapi import HTTPException
from psycopg2 import errors as pg_errors

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import users.service as usvc  # noqa: E402
from users.models import User, UserCreate, UserPasswordReset  # noqa: E402

auth_service = importlib.import_module("auth.service")

UID = "11111111-2222-3333-4444-555555555555"


def R(needle, one=None, many=None, rowcount=1, raises=None):
    return (needle, one, many if many is not None else [], rowcount, raises)


class Scripted:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self._one, self._many, self.rowcount = None, [], 0

    def execute(self, sql, params=None):
        norm = " ".join(sql.split())
        self.calls.append((norm, params))
        for needle, one, many, rowcount, raises in self.routes:
            if needle in norm:
                if raises:
                    raise raises
                self._one, self._many, self.rowcount = one, many, rowcount
                return
        self._one, self._many, self.rowcount = None, [], 0

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._many

    def sql_with(self, needle):
        return [(s, p) for s, p in self.calls if needle in s]


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


@pytest.fixture
def hasher(monkeypatch):
    monkeypatch.setattr(usvc, "get_password_hash", lambda p: "HASH:" + p)


def _patch(monkeypatch, cur):
    monkeypatch.setattr(usvc, "get_db_connection", lambda: FakeConn(cur))


# ---------------- U1: NULL full_name / email ----------------

def test_user_model_accepts_null_full_name_and_email():
    u = User(id=UID, username="admin", email=None, full_name=None, role="superadmin",
             is_active=True, created_at=datetime.now())
    assert u.full_name is None and u.email is None


def test_create_requires_min_password_and_valid_role():
    with pytest.raises(Exception):
        UserCreate(username="bob", password="short", email="b@x.co")
    with pytest.raises(Exception):
        UserCreate(username="bob", password="longenough", email="b@x.co", role="root")
    with pytest.raises(Exception):
        UserPasswordReset(new_password="short")


# ---------------- U7: UUID on create ----------------

def test_create_user_generates_uuid_and_uses_case_insensitive_checks(monkeypatch, hasher):
    created = {"id": None}
    cur = Scripted([
        R("lower(username) = lower(%s)", one=None),
        R("lower(email) = lower(%s)", one=None),
        R("INSERT INTO users", one={"id": "x"}),
        R("SELECT id, username, email, full_name, role, is_active, created_at", one={"id": "x"}),
    ])
    _patch(monkeypatch, cur)
    usvc.create_user("Bob", "longenough", "Bob@X.co", None, "user", actor_role="admin")
    sql, params = cur.sql_with("INSERT INTO users")[0]
    assert sql.startswith("INSERT INTO users (id, username")
    uuid.UUID(params[0])  # valid UUID
    assert params[1:] == ("Bob", "HASH:longenough", "Bob@X.co", None, "user", True)


def test_create_user_unique_violation_maps_to_400(monkeypatch, hasher):
    cur = Scripted([
        R("lower(username)", one=None),
        R("lower(email)", one=None),
        R("INSERT INTO users", raises=pg_errors.UniqueViolation()),
    ])
    _patch(monkeypatch, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.create_user("bob", "longenough", "b@x.co", None, "user", actor_role="admin")
    assert exc.value.code == "USER_EXISTS"


# ---------------- U2: superadmin protection ----------------

def test_admin_cannot_create_superadmin(monkeypatch, hasher):
    with pytest.raises(HTTPException) as exc:
        usvc.create_user("x", "longenough", "x@x.co", None, "superadmin", actor_role="admin")
    assert exc.value.status_code == 403 and exc.value.code == "SUPERADMIN_REQUIRED"


@pytest.mark.parametrize("target_role,new_role", [("user", "superadmin"), ("superadmin", None), ("superadmin", "admin")])
def test_admin_cannot_promote_or_modify_superadmin(monkeypatch, target_role, new_role):
    cur = Scripted([R("SELECT id, role, is_active FROM users WHERE id", one={"id": UID, "role": target_role, "is_active": True})])
    _patch(monkeypatch, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.update_user(UID, None, "Name", new_role, None, actor_role="admin")
    assert exc.value.code == "SUPERADMIN_REQUIRED"
    assert not cur.sql_with("UPDATE users SET")


def test_admin_cannot_reset_superadmin_password(monkeypatch, hasher):
    cur = Scripted([R("SELECT id, role FROM users WHERE id", one={"id": UID, "role": "superadmin"})])
    _patch(monkeypatch, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.reset_user_password(UID, "longenough", actor_role="admin")
    assert exc.value.code == "SUPERADMIN_REQUIRED"
    assert not cur.sql_with("UPDATE users SET password_hash")


def test_admin_cannot_delete_superadmin(monkeypatch):
    cur = Scripted([R("SELECT role, is_active FROM users WHERE id", one={"role": "superadmin", "is_active": True})])
    _patch(monkeypatch, cur)
    with pytest.raises(HTTPException) as exc:
        usvc.delete_user(UID, actor_role="admin")
    assert exc.value.code == "SUPERADMIN_REQUIRED"
    assert not cur.sql_with("DELETE FROM users")


def test_admin_can_manage_regular_users(monkeypatch, hasher):
    cur = Scripted([
        R("SELECT id, role FROM users WHERE id", one={"id": UID, "role": "user"}),
        R("UPDATE users SET password_hash", rowcount=1),
    ])
    _patch(monkeypatch, cur)
    assert usvc.reset_user_password(UID, "longenough", actor_role="admin") == {"message": "Contraseña restablecida correctamente"}


# ---------------- S3: role comes from the DB ----------------

def test_db_role_overrides_token_role(monkeypatch):
    token = auth_service.create_access_token({"sub": "alice", "role": "admin"})
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: "user")
    payload = auth_service._validate_access_token(token)
    assert payload["role"] == "user"


def test_token_role_kept_when_check_returns_nothing(monkeypatch):
    token = auth_service.create_access_token({"sub": "alice", "role": "admin"})
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda sub: None)
    assert auth_service._validate_access_token(token)["role"] == "admin"
