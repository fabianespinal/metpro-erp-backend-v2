"""Tax types (A1). Rates and labels live in public.tax_types, never in code.

A document stores a snapshot of its type (code, rate, label). Changing a type later does not
change a document that already has the snapshot. The snapshot is refreshed only while a quote
is a Draft and the user picks a type.
"""
from typing import List, Optional

from psycopg2.extras import RealDictCursor

from core.errors import api_error
from database import get_db_connection

TAX_COLUMNS = ("tax_type_code", "tax_rate", "tax_label")


def _snapshot(row: dict) -> dict:
    return {
        "tax_type_code": row["code"],
        "tax_rate": float(row["rate"]),
        "tax_label": row["label"],
    }


def list_tax_types(active_only: bool = True) -> List[dict]:
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT code, label, rate, active, is_default, sort_order FROM tax_types "
            + ("WHERE active " if active_only else "")
            + "ORDER BY sort_order, id"
        )
        return [
            {**dict(r), "rate": float(r["rate"])}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def resolve_tax_type(cursor, code: Optional[str]) -> dict:
    """Snapshot for a new or changed document. code=None means the default type.

    Unknown or inactive codes are rejected. Nothing falls back silently to another rate.
    """
    if code is None:
        cursor.execute("SELECT code, label, rate FROM tax_types WHERE is_default AND active")
    else:
        cursor.execute("SELECT code, label, rate FROM tax_types WHERE code = %s AND active", (code,))
    row = cursor.fetchone()
    if not row:
        raise api_error(400, "Tipo de impuesto no válido o inactivo", "TAX_TYPE_INVALID")
    return _snapshot(dict(row))


def get_tax_snapshot(code: Optional[str]) -> dict:
    """resolve_tax_type on its own connection, for read-only callers (the totals preview)."""
    conn = get_db_connection()
    try:
        return resolve_tax_type(conn.cursor(cursor_factory=RealDictCursor), code)
    finally:
        conn.close()


def snapshot_from_document(doc: dict) -> dict:
    """The stored snapshot of a quote or invoice row. Raises if the row has none (should not happen after the migration)."""
    if any(doc.get(k) is None for k in TAX_COLUMNS):
        raise api_error(500, "El documento no tiene tipo de impuesto", "TAX_SNAPSHOT_MISSING")
    return {
        "tax_type_code": doc["tax_type_code"],
        "tax_rate": float(doc["tax_rate"]),
        "tax_label": doc["tax_label"],
    }
