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
# Tax from charges. Toggle TAX_FROM_CHARGES, default OFF.
# Rule (authoritative, 2026-10-22 option 2, confirmed 2026-10-24): one of the five construction charges
# (supervision, admin, insurance, transport, contingency) switched on and above 0 = construction_17_2017.
# Custom (dynamic) charges never trigger it. No construction charge = the default type.
# The client-sent tax_type_code is ignored while the toggle is on.
# Engineering estimate quotes are the exception: they always keep the 1.8% the estimator sets
# (decision 2026-10-24); callers skip derivation for them (see derives_tax_for).
# ---------------------------------------------------------------------------
import os

CONSTRUCTION_TAX_CODE = "construction_17_2017"
STATIC_CHARGE_KEYS = ("supervision", "admin", "insurance", "transport", "contingency")
# Same defaults as quotes.service.calculate_quote_totals and quotes.models.IncludedCharges.
DEFAULT_CHARGE_PERCENTAGES = {"supervision": 10.0, "admin": 4.0, "insurance": 1.0, "transport": 3.0, "contingency": 3.0}


def tax_from_charges_enabled() -> bool:
    return os.getenv("TAX_FROM_CHARGES", "0").strip().lower() in ("1", "true", "yes", "on")


def charges_trigger_construction_tax(charges: dict) -> bool:
    """True when at least one of the five construction overhead charges is switched on AND above 0.

    Decision 2026-10-22 (supersedes "any charge"): only supervision, admin, insurance,
    transport and contingency trigger construction_17_2017. Dynamic/custom charges never trigger it.
    """
    charges = charges or {}
    for key in STATIC_CHARGE_KEYS:
        if charges.get(key):
            try:
                # A missing percentage means the default, exactly as the totals calculation reads it
                # (partial API updates store only the keys sent). Audit smoke 2026-10-24.
                if float(charges.get(f"{key}_percentage", DEFAULT_CHARGE_PERCENTAGES[key]) or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def tax_code_for_charges(charges: dict) -> Optional[str]:
    """Code to resolve for a document's charges. None = default type."""
    return CONSTRUCTION_TAX_CODE if charges_trigger_construction_tax(charges) else None


ESTIMATE_QUOTE_TYPE = "engineering_estimate"


def derives_tax_for(quote_type: Optional[str]) -> bool:
    """True when the tax of a quote of this type follows its charges right now.

    Off when TAX_FROM_CHARGES is off. Never for engineering estimate quotes: their 1.8% is fixed by the
    estimator and survives every save, duplicate and finalize (audit C2, decision 2026-10-24).
    """
    return tax_from_charges_enabled() and quote_type != ESTIMATE_QUOTE_TYPE
