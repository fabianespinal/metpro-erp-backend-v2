"""Cover page templates: storage and lookup. PDF generation never fails because of this module."""
import logging
import re
from typing import Optional

from core.errors import api_error
from database import get_db_connection
from cover_page.defaults import DEFAULT_BODY, DOC_TYPES, MAX_BODY_CHARS, allowed_fields

logger = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _check_doc_type(doc_type: str) -> None:
    if doc_type not in DOC_TYPES:
        raise api_error(404, "Tipo de documento no válido. Use «quote» o «invoice».", "COVER_DOC_TYPE_INVALID")


def validate_body(doc_type: str, body: Optional[str]) -> str:
    """Return the cleaned body or raise a Spanish 422."""
    _check_doc_type(doc_type)
    text = (body or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise api_error(422, "El texto de la portada no puede estar vacío.", "COVER_BODY_EMPTY")
    if len(text) > MAX_BODY_CHARS:
        raise api_error(422, f"El texto de la portada supera el máximo de {MAX_BODY_CHARS} caracteres.", "COVER_BODY_TOO_LONG")
    allowed = allowed_fields(doc_type)
    unknown = sorted({m for m in _PLACEHOLDER.findall(text) if m not in allowed})
    if unknown:
        listed = ", ".join("{" + n + "}" for n in unknown)
        valid = ", ".join("{" + n + "}" for n in allowed)
        raise api_error(422, f"Campos no reconocidos: {listed}. Campos válidos: {valid}.", "COVER_FIELD_UNKNOWN")
    return text


def render_text(body: str, values: dict) -> str:
    """Replace known {Fields}. Anything else is left as written."""
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), body)


def _row_to_dict(doc_type: str, row) -> dict:
    if not row:
        return {"doc_type": doc_type, "body": DEFAULT_BODY[doc_type], "enabled": True, "is_default": True,
                "updated_at": None, "updated_by": None}
    return {"doc_type": doc_type, "body": row["body"], "enabled": bool(row["enabled"]), "is_default": False,
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            "updated_by": row.get("updated_by")}


def get_all_templates() -> list:
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT doc_type, body, enabled, updated_at, updated_by FROM cover_page_templates")
        rows = {r["doc_type"]: r for r in cur.fetchall()}
    finally:
        conn.close()
    return [_row_to_dict(t, rows.get(t)) for t in DOC_TYPES]


def save_template(doc_type: str, body: str, enabled: bool, username: Optional[str]) -> dict:
    text = validate_body(doc_type, body)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO cover_page_templates (doc_type, body, enabled, updated_at, updated_by)
            VALUES (%s, %s, %s, now(), %s)
            ON CONFLICT (doc_type) DO UPDATE
               SET body = EXCLUDED.body, enabled = EXCLUDED.enabled,
                   updated_at = now(), updated_by = EXCLUDED.updated_by
            RETURNING doc_type, body, enabled, updated_at, updated_by
            """,
            (doc_type, text, bool(enabled), username),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return _row_to_dict(doc_type, row)


def get_active_body(doc_type: str) -> Optional[str]:
    """Body for the PDF cover, or None when an admin switched the cover off.

    Never raises: if the table is missing or the DB is unreachable the built-in text is used,
    so quote and invoice PDFs keep working.
    """
    try:
        conn = get_db_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT body, enabled FROM cover_page_templates WHERE doc_type = %s", (doc_type,))
            row = cur.fetchone()
        finally:
            conn.close()
        if row:
            return row["body"] if row["enabled"] else None
    except Exception:
        logger.exception("Cover page template lookup failed; using built-in text")
    return DEFAULT_BODY[doc_type]
