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


# ---------------------------------------------------------------------------
# Tax from charges (2026-10-22 decision). Toggle TAX_FROM_CHARGES, default OFF.
# Any charge with a value above 0 (static five or enabled dynamic charge) = construction_17_2017.
# No charge = the default type. The client-sent tax_type_code is ignored while the toggle is on.
# construction_17_2017 is seeded INACTIVE, so resolve_tax_type fails loudly until it is activated.
# ---------------------------------------------------------------------------
import os

CONSTRUCTION_TAX_CODE = "construction_17_2017"
STATIC_CHARGE_KEYS = ("supervision", "admin", "insurance", "transport", "contingency")


def tax_from_charges_enabled() -> bool:
    return os.getenv("TAX_FROM_CHARGES", "0").strip().lower() in ("1", "true", "yes")


def charges_trigger_construction_tax(charges: dict) -> bool:
    """True when at least one charge is switched on AND has a percentage above 0."""
    charges = charges or {}
    for key in STATIC_CHARGE_KEYS:
        if charges.get(key):
            try:
                if float(charges.get(f"{key}_percentage", 0) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    raw = charges.get("dynamic_charges")
    if isinstance(raw, list):
        for dc in raw[:3]:
            if not isinstance(dc, dict) or not dc.get("enabled"):
                continue
            try:
                if float(dc.get("percentage") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def tax_code_for_charges(charges: dict) -> Optional[str]:
    """Code to resolve for a document's charges. None = default type."""
    return CONSTRUCTION_TAX_CODE if charges_trigger_construction_tax(charges) else None
