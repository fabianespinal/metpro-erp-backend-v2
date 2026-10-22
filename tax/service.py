"""Tax types (A1). Rates and labels live in public.tax_types, never in code.

A document stores a snapshot of its type (code, rate, label). Changing a type later does not
change a document that already has the snapshot. The snapshot is refreshed only while a quote
is a Draft and its indirect charges change.
"""
from typing import List, Optional

from psycopg2.extras import RealDictCursor

from core.errors import api_error
from database import get_db_connection

TAX_COLUMNS = ("tax_type_code", "tax_rate", "tax_label")

# Approved rule (2026-10-22). The ONLY place that decides a document's tax type; nothing else may duplicate it.
# Any of these indirect charges selected -> Construction (Ley 17-2017). None selected -> ITBIS.
# Rates and labels come from tax_types, never from code.
STANDARD_CODE = "itbis_18"
CONSTRUCTION_CODE = "construction_17_2017"
CONSTRUCTION_TRIGGER_CHARGES = ("supervision", "admin", "insurance", "transport", "contingency")


def tax_code_for_charges(charges: Optional[dict]) -> str:
    charges = charges or {}
    return CONSTRUCTION_CODE if any(charges.get(k) for k in CONSTRUCTION_TRIGGER_CHARGES) else STANDARD_CODE


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


def resolve_tax_type(cursor, charges: Optional[dict]) -> dict:
    """Snapshot for a new or changed quote, decided by its indirect charges (tax_code_for_charges).

    The user never picks the type. A missing or inactive type is an error: nothing falls back silently to another rate.
    """
    cursor.execute("SELECT code, label, rate FROM tax_types WHERE code = %s AND active", (tax_code_for_charges(charges),))
    row = cursor.fetchone()
    if not row:
        raise api_error(400, "Tipo de impuesto no válido o inactivo", "TAX_TYPE_INVALID")
    return _snapshot(dict(row))


def get_tax_snapshot(charges: Optional[dict]) -> dict:
    """resolve_tax_type on its own connection, for read-only callers (the totals preview)."""
    conn = get_db_connection()
    try:
        return resolve_tax_type(conn.cursor(cursor_factory=RealDictCursor), charges)
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
