"""Item 7: unified token validation on every protected route.

Both entry points (verify_token and get_current_user_from_bearer) must
accept and reject the same tokens the same way. Public routes stay public.
"""
import importlib
import os
import re
import sys
import time

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from jose import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app  # noqa: E402

SECRET = "test-secret-key"


@pytest.fixture
def auth(monkeypatch):
    mod = importlib.import_module("auth.service")
    monkeypatch.setattr(mod, "ENFORCE_ACTIVE_CHECK", True)
    return mod


class _Cursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        pass

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, row):
        self._row = row

    def cursor(self, *a, **k):
        return _Cursor(self._row)

    def close(self):
        pass


def _db(monkeypatch, row):
    import database
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn(row))


def _token(claims, key=SECRET, alg="HS256"):
    return jwt.encode(claims, key, algorithm=alg)


def _good_claims(**extra):
    claims = {"sub": "alice", "role": "admin", "exp": int(time.time()) + 600}
    claims.update(extra)
    return claims


# Entry points under test. Each takes a raw token string.
def _via_bearer(auth, tok):
    return auth.get_current_user_from_bearer(tok)


def _via_header(auth, tok):
    return auth.verify_token(f"Bearer {tok}")


ENTRY_POINTS = [_via_bearer, _via_header]


# ---------- accepted ----------

@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_valid_token_is_accepted(auth, monkeypatch, entry):
    _db(monkeypatch, {"is_active": True})
    payload = entry(auth, _token(_good_claims()))
    assert payload["sub"] == "alice"
    assert payload["role"] == "admin"


# ---------- rejected: signature, algorithm, expiry, claims ----------

CASES = {
    "bad_signature": (lambda: _token(_good_claims(), key="wrong-key"), "Invalid token"),
    "alg_none": (lambda: _unsigned_none_token(), "Invalid token"),
    "wrong_alg_hs512": (lambda: _token(_good_claims(), alg="HS512"), "Invalid token"),
    "expired": (lambda: _token(_good_claims(exp=int(time.time()) - 5)), "Token expired"),
    "missing_exp": (lambda: _token({"sub": "alice", "role": "admin"}), "Invalid token"),
    "missing_sub": (lambda: _token({"role": "admin", "exp": int(time.time()) + 600}), "Invalid token"),
    "empty_sub": (lambda: _token(_good_claims(sub="")), "Invalid token"),
    "non_string_sub": (lambda: _token(_good_claims(sub=123)), "Invalid token"),
    "malformed": (lambda: "not.a.jwt", "Invalid token"),
}


def _unsigned_none_token():
    import base64
    import json

    def b64(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

    return f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64(_good_claims())}."


@pytest.mark.parametrize("entry", ENTRY_POINTS)
@pytest.mark.parametrize("case", sorted(CASES))
def test_invalid_token_rejected_identically(auth, monkeypatch, entry, case):
    make, detail = CASES[case]
    _db(monkeypatch, {"is_active": True})
    with pytest.raises(HTTPException) as e:
        entry(auth, make())
    assert e.value.status_code == 401
    assert e.value.detail == detail


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_tampered_payload_rejected(auth, monkeypatch, entry):
    _db(monkeypatch, {"is_active": True})
    good = _token(_good_claims(role="user"))
    head, _, sig = good.split(".")
    import base64
    import json
    evil = base64.urlsafe_b64encode(
        json.dumps(_good_claims(role="admin")).encode()
    ).rstrip(b"=").decode()
    with pytest.raises(HTTPException) as e:
        entry(auth, f"{head}.{evil}.{sig}")
    assert e.value.detail == "Invalid token"


# ---------- rejected: user state ----------

@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_deactivated_user_rejected(auth, monkeypatch, entry):
    _db(monkeypatch, {"is_active": False})
    with pytest.raises(HTTPException) as e:
        entry(auth, _token(_good_claims()))
    assert e.value.status_code == 401
    assert e.value.detail == "Account disabled"


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_deleted_user_rejected(auth, monkeypatch, entry):
    _db(monkeypatch, None)
    with pytest.raises(HTTPException) as e:
        entry(auth, _token(_good_claims()))
    assert e.value.detail == "User not found"


@pytest.mark.parametrize("entry", ENTRY_POINTS)
def test_active_check_toggle_off_skips_db(auth, monkeypatch, entry):
    monkeypatch.setattr(auth, "ENFORCE_ACTIVE_CHECK", False)
    import database
    called = []
    monkeypatch.setattr(database, "get_db_connection", lambda: called.append(1))
    entry(auth, _token(_good_claims()))
    assert called == []


# ---------- header parsing (verify_token only) ----------

@pytest.mark.parametrize("header, detail", [
    (None, "Missing authorization token"),
    ("Bearer", "Invalid authorization header format"),
    ("Token abc", "Invalid authorization scheme"),
])
def test_header_parsing_errors_unchanged(auth, header, detail):
    with pytest.raises(HTTPException) as e:
        auth.verify_token(header)
    assert e.value.status_code == 401
    assert e.value.detail == detail


# ---------- parity guard ----------

def test_both_entry_points_share_one_validator(auth):
    import inspect
    src_bearer = inspect.getsource(auth.get_current_user_from_bearer)
    src_header = inspect.getsource(auth.verify_token)
    assert "_validate_access_token(" in src_bearer
    assert "_validate_access_token(" in src_header
    assert "jwt.decode" not in src_bearer
    assert "jwt.decode" not in src_header


def test_claims_required_at_decode(auth):
    # A token with neither sub nor exp must never reach the user lookup.
    with pytest.raises(HTTPException):
        auth._validate_access_token(_token({"role": "admin"}))


# ---------- route coverage ----------

PROTECTED_DEPS = {"verify_token", "get_current_user_from_bearer", "wrapper"}

# The only routes allowed without a token. Anything else must require one.
EXPECTED_PUBLIC = {
    ("GET", "/"),
    ("GET", "/health"),
    ("POST", "/auth/login"),
    ("OPTIONS", "/auth/login"),
    ("GET", "/quotes/public/{token}"),
    ("GET", "/quotes/public/{token}/pdf"),
    ("GET", "/invoices/public/{token}"),
    ("GET", "/invoices/public/{token}/pdf"),
}


def _dep_names(dependant, out):
    for d in dependant.dependencies:
        out.append(getattr(d.call, "__name__", ""))
        _dep_names(d, out)
    return out


def _api_routes():
    for r in app.routes:
        if isinstance(r, APIRoute):
            yield r


def _has_auth(route):
    return bool(PROTECTED_DEPS & set(_dep_names(route.dependant, [])))


def test_only_expected_routes_are_public():
    public = set()
    for r in _api_routes():
        if not _has_auth(r):
            for m in r.methods:
                public.add((m, r.path))
    assert public == EXPECTED_PUBLIC


def _sample_path(path):
    return re.sub(r"\{[^}]+\}", "1", path)


@pytest.mark.parametrize("method, path", sorted(
    (m, r.path) for r in _api_routes() if _has_auth(r) for m in r.methods
))
def test_protected_route_rejects_missing_token(monkeypatch, method, path):
    client = TestClient(app)
    resp = client.request(method, _sample_path(path), json={})
    assert resp.status_code == 401, (method, path, resp.text)


@pytest.mark.parametrize("method, path", sorted(
    (m, r.path) for r in _api_routes() if _has_auth(r) for m in r.methods
))
def test_protected_route_rejects_bad_token(monkeypatch, method, path):
    client = TestClient(app)
    resp = client.request(
        method,
        _sample_path(path),
        json={},
        headers={"Authorization": "Bearer " + _token(_good_claims(), key="wrong")},
    )
    assert resp.status_code == 401, (method, path, resp.text)
