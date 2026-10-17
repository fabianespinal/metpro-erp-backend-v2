"""Terms and Conditions settings. PDF generation never fails because of this module."""
import json
import logging
from typing import Optional

from core.errors import api_error
from database import get_db_connection
from terms_page.defaults import DEFAULT_SECTIONS, MAX_SECTION_CHARS, SECTION_KEYS, SECTIONS

logger = logging.getLogger(__name__)

DOC_KINDS = ("quote", "invoice")


def clean_sections(sections) -> dict:
    """Validate and normalise the posted sections. Raises a Spanish 422."""
    if not isinstance(sections, dict):
        raise api_error(422, "Formato de secciones no válido.", "TERMS_SECTIONS_INVALID")
    unknown = sorted(set(sections) - set(SECTION_KEYS))
    if unknown:
        raise api_error(422, f"Secciones no reconocidas: {', '.join(unknown)}.", "TERMS_SECTION_UNKNOWN")
    out = {}
    titles = dict(SECTIONS)
    for key in SECTION_KEYS:
        if key not in sections:
            continue
        text = str(sections[key] or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if len(text) > MAX_SECTION_CHARS:
            raise api_error(
                422,
                f"La sección «{titles[key]}» supera el máximo de {MAX_SECTION_CHARS} caracteres.",
                "TERMS_SECTION_TOO_LONG",
            )
        out[key] = text
    return out


def _merge(stored: Optional[dict]) -> dict:
    """Stored text wins (even when empty, which hides the section); missing keys use the starter text."""
    stored = stored or {}
    return {k: (stored[k] if k in stored else DEFAULT_SECTIONS[k]) for k in SECTION_KEYS}


def _load_row():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT enabled_quote, enabled_invoice, sections, updated_at, updated_by FROM terms_settings WHERE id = 1"
        )
        return cur.fetchone()
    finally:
        conn.close()


def _sections_of(row) -> dict:
    raw = row["sections"] if row else {}
    if isinstance(raw, str):
        raw = json.loads(raw)
    return raw or {}


def get_settings() -> dict:
    row = _load_row()
    return {
        "enabled_quote": bool(row["enabled_quote"]) if row else False,
        "enabled_invoice": bool(row["enabled_invoice"]) if row else False,
        "sections": _merge(_sections_of(row)),
        "is_default": row is None,
        "updated_at": row["updated_at"].isoformat() if row and row.get("updated_at") else None,
        "updated_by": row.get("updated_by") if row else None,
    }


def save_settings(sections, enabled_quote: bool, enabled_invoice: bool, username: Optional[str]) -> dict:
    cleaned = clean_sections(sections)
    # Save the full set so what the admin saw is exactly what prints.
    full = _merge(cleaned)
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO terms_settings (id, enabled_quote, enabled_invoice, sections, updated_at, updated_by)
            VALUES (1, %s, %s, %s::jsonb, now(), %s)
            ON CONFLICT (id) DO UPDATE
               SET enabled_quote = EXCLUDED.enabled_quote, enabled_invoice = EXCLUDED.enabled_invoice,
                   sections = EXCLUDED.sections, updated_at = now(), updated_by = EXCLUDED.updated_by
            """,
            (bool(enabled_quote), bool(enabled_invoice), json.dumps(full), username),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return get_settings()


def get_active_sections(kind: str) -> Optional[list]:
    """[(title, text), ...] for the PDF, or None when the page is off for this document type.

    Never raises. On any error nothing is printed: unreviewed text must not appear by accident.
    """
    try:
        row = _load_row()
        if not row:
            return None
        if not row["enabled_quote" if kind == "quote" else "enabled_invoice"]:
            return None
        merged = _merge(_sections_of(row))
        titles = dict(SECTIONS)
        items = [(titles[k], merged[k]) for k in SECTION_KEYS if merged[k].strip()]
        return items or None
    except Exception:
        logger.exception("Terms lookup failed; the PDF is generated without the terms page")
        return None
