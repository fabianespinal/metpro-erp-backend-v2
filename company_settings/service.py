"""Company settings (V1: the seal). PDFs read the seal only when a request asks for it."""
import logging
import threading
import time
from typing import Optional

from core.errors import api_error
from core.storage import (
    StorageError,
    StorageNotConfigured,
    StorageObjectNotFound,
    download_object,
    storage_configured,
    upload_object,
)
from database import get_db_connection
from pdf.utils.seal_utils import PreparedSeal, SealImageError, normalize_seal_image, prepare_seal

logger = logging.getLogger(__name__)

BUCKET = "company-seals"
COMPANY_KEY = "metpro"                      # single company for now; the path leaves room for more
SEAL_OBJECT = f"{COMPANY_KEY}/seal.png"
CACHE_SECONDS = 300

_cache_lock = threading.Lock()
_cache: dict = {"at": 0.0, "path": None, "seal": None}


def _clear_cache() -> None:
    with _cache_lock:
        _cache.update(at=0.0, path=None, seal=None)


def _row() -> Optional[dict]:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT seal_image_url, seal_enabled_by_default, updated_at, updated_by FROM company_settings WHERE id = 1"
        )
        return cur.fetchone()
    finally:
        conn.close()


def get_seal_settings() -> dict:
    """What the UI needs. Never returns the storage path."""
    row = _row()
    return {
        "configured": bool(row and row["seal_image_url"]),
        "enabled_by_default": bool(row and row["seal_enabled_by_default"]),
        "storage_ready": storage_configured(),
        "updated_at": row["updated_at"].isoformat() if row and row["updated_at"] else None,
        "updated_by": row["updated_by"] if row else None,
    }


def set_enabled_by_default(enabled: bool, actor: Optional[str]) -> dict:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO company_settings (id, seal_enabled_by_default, updated_by) VALUES (1, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET seal_enabled_by_default = EXCLUDED.seal_enabled_by_default, "
            "updated_at = now(), updated_by = EXCLUDED.updated_by",
            (bool(enabled), actor),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_seal_settings()


def save_seal_image(raw: bytes, actor: Optional[str]) -> dict:
    """Validate, normalise and store the seal, then point the settings row at it. Replaces any earlier seal."""
    try:
        png = normalize_seal_image(raw)
    except SealImageError as exc:
        raise api_error(422, str(exc), "SEAL_IMAGE_INVALID")
    if not storage_configured():
        raise api_error(503, "El almacenamiento de archivos no está configurado en el servidor.", "STORAGE_NOT_CONFIGURED")
    try:
        upload_object(BUCKET, SEAL_OBJECT, png, "image/png")  # the row is only updated after the file is stored
    except StorageNotConfigured:
        raise api_error(503, "El almacenamiento de archivos no está configurado en el servidor.", "STORAGE_NOT_CONFIGURED")
    except StorageError:
        logger.exception("Seal upload failed")
        raise api_error(502, "No se pudo guardar el sello. Intente de nuevo.", "SEAL_UPLOAD_FAILED")

    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO company_settings (id, seal_image_url, updated_by) VALUES (1, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET seal_image_url = EXCLUDED.seal_image_url, "
            "updated_at = now(), updated_by = EXCLUDED.updated_by",
            (SEAL_OBJECT, actor),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    _clear_cache()
    return get_seal_settings()


def get_seal_image_bytes() -> bytes:
    """The stored PNG, for the settings preview."""
    row = _row()
    if not row or not row["seal_image_url"]:
        raise api_error(404, "No hay un sello cargado.", "SEAL_NOT_FOUND")
    try:
        return download_object(BUCKET, row["seal_image_url"])
    except StorageObjectNotFound:
        raise api_error(404, "No hay un sello cargado.", "SEAL_NOT_FOUND")
    except StorageNotConfigured:
        raise api_error(503, "El almacenamiento de archivos no está configurado en el servidor.", "STORAGE_NOT_CONFIGURED")
    except StorageError:
        logger.exception("Seal download failed")
        raise api_error(502, "No se pudo leer el sello.", "SEAL_READ_FAILED")


def load_seal_for_pdf() -> Optional[PreparedSeal]:
    """Prepared seal, or None when it cannot be loaded. Never raises."""
    try:
        now = time.monotonic()
        with _cache_lock:
            if _cache["seal"] is not None and now - _cache["at"] < CACHE_SECONDS:
                return _cache["seal"]
        row = _row()
        path = row["seal_image_url"] if row else None
        if not path:
            return None
        seal = prepare_seal(download_object(BUCKET, path))
        with _cache_lock:
            _cache.update(at=time.monotonic(), path=path, seal=seal)
        return seal
    except Exception:
        logger.exception("Company seal could not be loaded")
        return None


def seal_for_pdf(print_seal: bool) -> Optional[PreparedSeal]:
    """The seal to print, or None when the request does not ask for one.

    Asked for but not loadable is an error, never a silent unstamped PDF: an unsigned
    document could otherwise go to a client believing it carries the seal.
    """
    if print_seal is not True:
        # Strict on purpose: only an explicit True prints a seal. Truthy look-alikes (a "yes" string,
        # 1, or FastAPI's Form/Query default marker when a route function is called directly) do not.
        return None
    seal = load_seal_for_pdf()
    if seal is None:
        raise api_error(
            503,
            "No se pudo cargar el sello de la empresa. Desmarque «Imprimir sello» o intente de nuevo.",
            "SEAL_UNAVAILABLE",
        )
    return seal
