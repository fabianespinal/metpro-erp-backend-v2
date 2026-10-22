"""Item 9, module 3: clients, contacts, expenses, products, projects carry stable codes.

Messages and status codes are unchanged. The audit pins every (status, message, code).
"""
import importlib
import os
import re
import sys
import time

from fastapi.testclient import TestClient
from jose import jwt

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from main import app  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")
FILES = [
    "clients/router.py", "clients/service.py", "contacts/router.py",
    "expenses/router.py", "expenses/services.py",
    "products/router.py", "products/service.py", "projects/service.py", "projects/ledger.py",
]

# (status, message literal without quotes or f-prefix, code)
EXPECTED = {
    (400, "El archivo debe ser formato CSV", "CSV_FORMAT_INVALID"),
    (404, "Cliente no encontrado", "CLIENT_NOT_FOUND"),
    (404, "Cliente con ID {client_id} no encontrado", "CLIENT_NOT_FOUND"),
    (400, "Formato de correo no válido", "EMAIL_INVALID"),
    (400, "El correo {email} ya está en uso por otro cliente", "CLIENT_EMAIL_TAKEN"),
    (400, "El RNC {tax_id} ya está en uso por otro cliente", "CLIENT_TAX_ID_TAKEN"),
    (400, "El archivo debe estar codificado en UTF-8", "FILE_ENCODING_INVALID"),
    (400, "El archivo CSV está vacío", "CSV_EMPTY"),
    (400, "Falta la columna obligatoria: company_name", "CSV_COLUMN_MISSING"),
    (404, "Contacto no encontrado", "CONTACT_NOT_FOUND"),
    (404, "Gasto no encontrado", "EXPENSE_NOT_FOUND"),
    (400, "No hay nada que actualizar", "NOTHING_TO_UPDATE"),
    (500, "No se pudo registrar el gasto", "EXPENSE_INSERT_FAILED"),
    (404, "Producto no encontrado", "PRODUCT_NOT_FOUND"),
    (400, "Faltan columnas obligatorias: {required_cols}", "CSV_COLUMNS_MISSING"),
    (400, "La fecha de fin debe ser posterior a la fecha de inicio", "DATE_RANGE_INVALID"),
    (404, "Proyecto no encontrado", "PROJECT_NOT_FOUND"),
    (400, "El nombre no puede estar vacío", "NAME_REQUIRED"),
    (400, "El cliente tiene cotizaciones, facturas o proyectos y no se puede eliminar", "CLIENT_IN_USE"),
    (400, "Las dimensiones de producto no están habilitadas", "PRODUCT_DIMENSIONS_DISABLED"),  # B3
    (400, "El producto se usa en un paquete de plantilla y no se puede eliminar", "PRODUCT_IN_USE"),
    (400, "El proyecto tiene gastos asociados y no se puede eliminar", "PROJECT_HAS_EXPENSES"),
    (400, "El cliente de un proyecto creado desde una cotización no se puede cambiar", "PROJECT_CLIENT_LOCKED"),  # X-03
}

CALL = re.compile(r"api_error\((\d+), (f?)([\"'])(.*?)\3, \"([A-Z_]+)\"\)", re.S)


def _calls(path):
    src = open(os.path.join(ROOT, path), encoding="utf-8").read()
    return [(int(s), msg, code) for s, _p, _q, msg, code in CALL.findall(src)]


def test_no_bare_http_exception_raises_left():
    for path in FILES:
        src = open(os.path.join(ROOT, path), encoding="utf-8").read()
        assert "raise HTTPException(" not in src, path


def test_every_call_is_expected():
    for path in FILES:
        for status, msg, code in _calls(path):
            assert (status, msg, code) in EXPECTED, (path, status, msg, code)


def test_every_expected_pair_is_used():
    used = set()
    for path in FILES:
        used.update(_calls(path))
    assert used == EXPECTED


# ---------- behavior ----------

class _Seq:
    """Cursor whose fetchone returns rows in order, then None."""

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

    def fetchall(self):
        return []

    def close(self):
        pass


class _Conn:
    def __init__(self, rows):
        self._cursor = _Seq(rows)

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _auth_headers():
    tok = jwt.encode({"sub": "alice", "role": "admin", "exp": int(time.time()) + 600},
                     "test-secret-key", algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


def _patch_db(monkeypatch, *rows_per_call):
    """Each get_db_connection() call gets its own fake. First one is the active-user check."""
    import database
    queue = list(rows_per_call)

    def factory():
        return _Conn(queue.pop(0) if queue else [])

    monkeypatch.setattr(database, "get_db_connection", factory)


def _patch_service_db(monkeypatch, module_name, rows):
    """Service modules import get_db_connection by name, so patch them directly."""
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "get_db_connection", lambda: _Conn(rows))


def test_get_client_missing_has_code(monkeypatch):
    _patch_db(monkeypatch, [{"is_active": True}])
    _patch_service_db(monkeypatch, "clients.service", [])
    resp = TestClient(app).get("/clients/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Cliente no encontrado", "code": "CLIENT_NOT_FOUND"}


def test_get_product_missing_has_code(monkeypatch):
    _patch_db(monkeypatch, [{"is_active": True}])
    _patch_service_db(monkeypatch, "products.service", [])
    resp = TestClient(app).get("/products/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Producto no encontrado", "code": "PRODUCT_NOT_FOUND"}


def test_get_project_missing_has_code(monkeypatch):
    _patch_db(monkeypatch, [{"is_active": True}])
    _patch_service_db(monkeypatch, "projects.service", [])
    resp = TestClient(app).get("/projects/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Proyecto no encontrado", "code": "PROJECT_NOT_FOUND"}


def test_bulk_import_wrong_file_type_has_code(monkeypatch):
    _patch_db(monkeypatch, [{"is_active": True}])
    resp = TestClient(app).post(
        "/clients/bulk-import",
        headers=_auth_headers(),
        files={"file": ("clients.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "El archivo debe ser formato CSV", "code": "CSV_FORMAT_INVALID"}


def test_product_csv_wrong_type_has_code(monkeypatch):
    _patch_db(monkeypatch, [{"is_active": True}])
    resp = TestClient(app).post(
        "/products/import-csv",
        headers=_auth_headers(),
        files={"file": ("products.txt", b"x", "text/plain")},
    )
    assert resp.status_code == 400
    assert resp.json() == {"detail": "El archivo debe ser formato CSV", "code": "CSV_FORMAT_INVALID"}


def test_api_error_renders_dynamic_message_unchanged(monkeypatch):
    """Dynamic messages keep their f-string text and code."""
    cs = importlib.import_module("clients.service")
    from core.errors import api_error
    exc = api_error(400, f"Email {'a@b'} is already in use by another client", "CLIENT_EMAIL_TAKEN")
    assert exc.detail == "Email a@b is already in use by another client"
    assert exc.code == "CLIENT_EMAIL_TAKEN"
