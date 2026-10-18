"""Item 9, module 2: auth and users errors carry a stable code. Messages unchanged."""
import ast
import importlib
import os
import sys
import time

import pytest
from fastapi.testclient import TestClient
from jose import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
FILES = ["auth/router.py", "auth/service.py", "users/router.py", "users/service.py"]

# Every (message, code) pair this module may emit. Messages are the client contract.
EXPECTED = {
    ("Usuario o contraseña incorrectos", "INVALID_CREDENTIALS"),
    ("La cuenta está deshabilitada", "ACCOUNT_DISABLED"),
    ("Cuenta deshabilitada", "ACCOUNT_DISABLED"),
    ("El inicio de sesión no está disponible temporalmente", "LOGIN_UNAVAILABLE"),
    ("El registro no está disponible temporalmente", "REGISTRATION_UNAVAILABLE"),
    ("El nombre de usuario ya existe", "USERNAME_TAKEN"),
    ("El correo ya existe", "EMAIL_TAKEN"),
    ("Usuario no encontrado", "USER_NOT_FOUND"),
    ("La contraseña anterior es incorrecta", "PASSWORD_INCORRECT"),
    ("La contraseña actual es incorrecta", "PASSWORD_INCORRECT"),
    ("El token está vacío", "TOKEN_EMPTY"),
    ("El token expiró", "TOKEN_EXPIRED"),
    ("Token no válido", "TOKEN_INVALID"),
    ("Falta el token de autorización", "TOKEN_MISSING"),
    ("Formato de encabezado de autorización no válido", "AUTH_HEADER_INVALID"),
    ("Esquema de autorización no válido", "AUTH_SCHEME_INVALID"),
    ("Permisos insuficientes", "INSUFFICIENT_PERMISSIONS"),
    ("No hay campos para actualizar", "NO_FIELDS_TO_UPDATE"),
    ("No puede eliminar su propia cuenta", "CANNOT_DELETE_SELF"),
    ("No se puede quitar al último superadministrador activo", "LAST_SUPERADMIN"),
    ("El usuario o el correo ya existe", "USER_EXISTS"),
    ("Solo un superadministrador puede gestionar cuentas de superadministrador", "SUPERADMIN_REQUIRED"),
}


def _api_error_calls(path):
    tree = ast.parse(open(os.path.join(ROOT, path), encoding="utf-8").read())
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "api_error":
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            out.append(tuple(args[1:3]))
    return out


def test_no_bare_http_exception_raises_left():
    for path in FILES:
        src = open(os.path.join(ROOT, path), encoding="utf-8").read()
        assert "raise HTTPException(" not in src, path


@pytest.mark.parametrize("path", FILES)
def test_every_api_error_uses_expected_message_and_code(path):
    calls = _api_error_calls(path)
    assert calls, path
    for msg, code in calls:
        assert (msg, code) in EXPECTED, (path, msg, code)


def test_expected_pairs_are_all_used():
    used = set()
    for path in FILES:
        used.update(_api_error_calls(path))
    assert used == EXPECTED


# ---------- behavior ----------

class _Cursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._row

    def close(self):
        pass


class _Conn:
    def __init__(self, row):
        self._row = row

    def cursor(self, *a, **k):
        return _Cursor(self._row)

    def close(self):
        pass


def _token(claims):
    return jwt.encode({**claims, "exp": int(time.time()) + 600}, "test-secret-key", algorithm="HS256")


def test_login_wrong_user_has_code(monkeypatch):
    ar = importlib.import_module("auth.router")
    monkeypatch.setattr(ar, "get_db_connection", lambda: _Conn(None))
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    resp = TestClient(app).post("/auth/login", json={"username": "x", "password": "y"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Usuario o contraseña incorrectos", "code": "INVALID_CREDENTIALS"}


def test_login_disabled_user_has_code(monkeypatch):
    ar = importlib.import_module("auth.router")
    monkeypatch.setattr(ar, "get_db_connection", lambda: _Conn({"is_active": False, "password_hash": "x", "username": "x", "id": 1}))
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    resp = TestClient(app).post("/auth/login", json={"username": "x", "password": "y"})
    assert resp.json() == {"detail": "La cuenta está deshabilitada", "code": "ACCOUNT_DISABLED"}


def test_missing_header_has_code():
    resp = TestClient(app).get("/auth/me")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "Falta el token de autorización", "code": "TOKEN_MISSING"}


def test_bad_scheme_has_code():
    resp = TestClient(app).get("/auth/me", headers={"Authorization": "Token abc"})
    assert resp.json() == {"detail": "Esquema de autorización no válido", "code": "AUTH_SCHEME_INVALID"}


def test_bad_format_has_code():
    resp = TestClient(app).get("/auth/me", headers={"Authorization": "Bearer"})
    assert resp.json() == {"detail": "Formato de encabezado de autorización no válido", "code": "AUTH_HEADER_INVALID"}


def test_expired_token_has_code(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    tok = jwt.encode({"sub": "a", "exp": int(time.time()) - 5}, "test-secret-key", algorithm="HS256")
    resp = TestClient(app).get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert resp.json() == {"detail": "El token expiró", "code": "TOKEN_EXPIRED"}


def test_invalid_token_has_code():
    resp = TestClient(app).get("/auth/me", headers={"Authorization": "Bearer not.a.token"})
    assert resp.json() == {"detail": "Token no válido", "code": "TOKEN_INVALID"}


def test_deleted_user_has_code(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn(None))
    tok = _token({"sub": "ghost", "role": "admin"})
    resp = TestClient(app).get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert resp.json() == {"detail": "Usuario no encontrado", "code": "USER_NOT_FOUND"}


def test_deactivated_user_has_code(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn({"is_active": False}))
    tok = _token({"sub": "alice", "role": "admin"})
    resp = TestClient(app).get("/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert resp.json() == {"detail": "Cuenta deshabilitada", "code": "ACCOUNT_DISABLED"}


def test_insufficient_role_has_code(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn({"is_active": True}))
    tok = _token({"sub": "alice", "role": "user"})
    resp = TestClient(app).get("/auth/admin-only", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 403
    assert resp.json() == {"detail": "Permisos insuficientes", "code": "INSUFFICIENT_PERMISSIONS"}


def test_api_error_helper_sets_code_and_message():
    from core.errors import api_error
    exc = api_error(409, "Already here", "THING_EXISTS")
    assert exc.status_code == 409
    assert exc.detail == "Already here"
    assert exc.code == "THING_EXISTS"
