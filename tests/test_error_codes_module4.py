"""Item 9, module 4: quotes, invoices, pdf carry stable codes. Messages and statuses unchanged."""
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
FILES = ["invoices/router.py", "invoices/service.py", "pdf/service.py", "quotes/service.py"]

# (file, status, message literal without quotes or f-prefix, code)
EXPECTED = {
    ("invoices/router.py", 404, "Factura no encontrada", "INVOICE_NOT_FOUND"),
    ("invoices/router.py", 400, "No se puede enviar una factura cancelada", "INVOICE_CANCELLED"),  # B-10
    ("invoices/router.py", 400, "El contacto de la factura no tiene correo electrónico", "INVOICE_NO_CONTACT_EMAIL"),  # B-10
    ("invoices/router.py", 404, "No disponible", "NOT_FOUND"),  # B-14 toggle off
    ("invoices/router.py", 403, "Permisos insuficientes", "INSUFFICIENT_PERMISSIONS"),  # B-14 admin only
    ("invoices/service.py", 404, "Factura no encontrada", "INVOICE_NOT_FOUND"),
    ("invoices/service.py", 400, "Estado no válido. Debe ser uno de: {list(INVOICE_STATUSES)}", "INVOICE_STATUS_INVALID"),
    ("invoices/service.py", 400, "Las facturas pasan a Pagada al registrar pagos", "INVOICE_PAID_VIA_PAYMENTS"),
    ("invoices/service.py", 400, "No se puede cambiar la factura de {current['status']} a {status}", "INVOICE_TRANSITION_INVALID"),
    ("invoices/service.py", 400, "La factura tiene pagos y no se puede cancelar", "INVOICE_HAS_PAYMENTS"),
    ("invoices/service.py", 400, "La factura tiene pagos y no se puede eliminar", "INVOICE_HAS_PAYMENTS"),
    ("pdf/service.py", 404, "Cotización no encontrada", "QUOTE_NOT_FOUND"),
    ("pdf/service.py", 404, "Cliente no encontrado", "CLIENT_NOT_FOUND"),
    ("pdf/service.py", 404, "Factura no encontrada", "INVOICE_NOT_FOUND"),
    ("pdf/service.py", 404, "La copia completa no está habilitada", "FULL_COPY_DISABLED"),  # internal full copy
    ("pdf/service.py", 403, "Permisos insuficientes", "INSUFFICIENT_PERMISSIONS"),  # internal full copy: admin only
    ("quotes/service.py", 409, "Esta cotización tiene líneas ocultas; actualice la pantalla antes de guardar", "PRINT_FLAG_REQUIRED"),  # A3
    ("quotes/service.py", 400, "El control de impresión no está habilitado", "PRINT_CONTROLS_DISABLED"),  # A3
    ("quotes/service.py", 400, "Ocultar productos en el PDF no está habilitado", "PDF_PRINT_ITEMS_DISABLED"),  # PDF update
    ("quotes/service.py", 403, "Los precios, cantidades, descuentos, cargos e impuestos de un estimado de ingeniería solo los puede cambiar un administrador", "ESTIMATE_LOCKED"),  # I3
    ("quotes/service.py", 400, "Indique el motivo del cambio", "ESTIMATE_EDIT_REASON_REQUIRED"),  # I3
    ("quotes/service.py", 404, "No disponible", "NOT_FOUND"),  # B1 switch off
    ("quotes/service.py", 400, "El contacto {target_contact} no pertenece al cliente {target_client}", "CONTACT_CLIENT_MISMATCH"),  # B1
    ("quotes/service.py", 404, "Cliente no encontrado", "CLIENT_NOT_FOUND"),
    ("quotes/service.py", 400, "El contacto {contact_id} no pertenece al cliente {client_id}", "CONTACT_CLIENT_MISMATCH"),
    ("quotes/service.py", 400, "Seleccione un contacto del cliente", "CONTACT_REQUIRED"),
    ("quotes/service.py", 404, "Cotización no encontrada", "QUOTE_NOT_FOUND"),
    ("quotes/service.py", 400, "Solo las cotizaciones en Borrador se pueden editar", "QUOTE_NOT_DRAFT"),
    ("quotes/service.py", 400, "Solo las cotizaciones aprobadas se pueden convertir en facturas", "QUOTE_NOT_APPROVED"),
    ("quotes/service.py", 400, "Las cotizaciones finalizadas no se pueden editar", "QUOTE_FINALIZED"),
    ("quotes/service.py", 400, "Solo las cotizaciones en Borrador se pueden finalizar", "QUOTE_NOT_DRAFT"),
    ("quotes/service.py", 400, "Use la acción de finalizar para establecer Final", "QUOTE_USE_FINALIZE"),
    ("quotes/service.py", 400, "La cotización debe tener al menos un ítem para finalizarla", "QUOTE_EMPTY"),
    ("quotes/service.py", 400, "Producto no encontrado", "PRODUCT_NOT_FOUND"),
    ("quotes/service.py", 400, "Ya existe una factura para esta cotización", "INVOICE_EXISTS"),
    ("quotes/service.py", 400, "Estado no válido. Debe ser uno de: {list(QUOTE_STATUSES)}", "QUOTE_STATUS_INVALID"),
    ("quotes/service.py", 400, "No se puede cambiar la cotización de {current['status']} a {status}", "QUOTE_TRANSITION_INVALID"),
    ("quotes/service.py", 400, "Use la acción de enviar para marcar una cotización como Enviada", "QUOTE_USE_SEND"),
    ("quotes/service.py", 400, "Use convertir a factura para facturar una cotización", "QUOTE_USE_CONVERT"),
    ("quotes/service.py", 400, "Las cotizaciones no pueden volver a Borrador. Duplique la cotización para reelaborarla", "QUOTE_REOPEN_BLOCKED"),
    ("quotes/service.py", 400, "Solo se pueden enviar cotizaciones finalizadas", "QUOTE_NOT_FINALIZED"),
    ("quotes/service.py", 400, "El contacto de la cotización no tiene correo electrónico", "QUOTE_NO_CONTACT_EMAIL"),
    ("quotes/service.py", 400, "Solo se pueden eliminar cotizaciones en Borrador o Rechazadas", "QUOTE_DELETE_BLOCKED"),
    ("quotes/service.py", 400, "La cotización tiene una factura y no se puede eliminar", "QUOTE_DELETE_BLOCKED"),
    ("quotes/service.py", 400, "Este estimado de ingeniería conserva su historial de cálculo y cambios auditados, por eso no se puede eliminar.", "ESTIMATE_QUOTE_HAS_HISTORY"),  # audit H1
    ("quotes/service.py", 400, "Cada cargo adicional activo necesita un nombre", "CHARGE_NAME_REQUIRED"),  # audit M1
    ("quotes/service.py", 400, "El descuento porcentual no puede exceder 100", "QUOTE_DISCOUNT_INVALID"),
    ("quotes/service.py", 400, "El descuento fijo no puede exceder el monto de la línea", "QUOTE_DISCOUNT_INVALID"),
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
            assert any(f == path and s == status and m == msg and c == code for f, s, m, c in EXPECTED), (path, status, msg, code)


def test_every_expected_entry_is_used():
    used = set()
    for path in FILES:
        for status, msg, code in _calls(path):
            used.add((path, status, msg, code))
    assert used == EXPECTED


# ---------- behavior ----------

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


def _patch_auth_db(monkeypatch):
    import database
    monkeypatch.setattr(database, "get_db_connection", lambda: _Conn([{"is_active": True}]))


def _patch_service_db(monkeypatch, module_name, rows=()):
    mod = importlib.import_module(module_name)
    monkeypatch.setattr(mod, "get_db_connection", lambda: _Conn(list(rows)))


def test_get_quote_missing_has_code(monkeypatch):
    _patch_auth_db(monkeypatch)
    _patch_service_db(monkeypatch, "quotes.service")
    resp = TestClient(app).get("/quotes/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Cotización no encontrada", "code": "QUOTE_NOT_FOUND"}


def test_get_invoice_missing_has_code(monkeypatch):
    _patch_auth_db(monkeypatch)
    _patch_service_db(monkeypatch, "invoices.service")
    resp = TestClient(app).get("/invoices/999", headers=_auth_headers())
    assert resp.status_code == 404
    assert resp.json() == {"detail": "Factura no encontrada", "code": "INVOICE_NOT_FOUND"}


def test_api_error_keeps_dynamic_message():
    from core.errors import api_error
    exc = api_error(400, f"Invalid status. Must be one of: {['Draft']}", "QUOTE_STATUS_INVALID")
    assert exc.detail == "Invalid status. Must be one of: ['Draft']"
    assert exc.code == "QUOTE_STATUS_INVALID"
