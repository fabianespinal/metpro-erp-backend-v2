"""PDF update (2026-10-23): switches and helpers for "Medidas", the project heading and the
per-quote "show products on the PDF" checkbox.

All three switches default OFF. With a switch off the code path is the one that existed before,
so nothing changes until Fabian turns it on after the migration is applied.
"""
import os
from typing import List, Optional, Tuple

UNIT_MAX = 20


def _on(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in ("1", "true", "yes", "on")


def medidas_enabled() -> bool:
    return _on("PDF_MEDIDAS_ENABLED")


def print_items_enabled() -> bool:
    return _on("PDF_PRINT_ITEMS_ENABLED")


def project_desc_enabled() -> bool:
    return _on("PDF_PROJECT_DESC_ENABLED")


def clean_unit(value) -> Optional[str]:
    """Free text. Blank = no unit. Trimmed and capped; no fixed list."""
    if value is None:
        return None
    text = str(value).strip()
    return text[:UNIT_MAX] if text else None


def with_units(sql: str, rows: List[tuple], items: List[dict]) -> Tuple[str, List[tuple]]:
    """Append unit_of_measure to a line INSERT only when the switch is on and at least one line has a
    unit. Otherwise the original SQL and rows come back untouched (works before the migration)."""
    if not medidas_enabled():
        return sql, rows
    units = [clean_unit(i.get("unit_of_measure")) for i in items]
    if not any(units):
        return sql, rows
    return sql.replace(") VALUES %s", ", unit_of_measure) VALUES %s"), [r + (u,) for r, u in zip(rows, units)]


def fill_units_from_products(cursor, items: List[dict]) -> None:
    """A line with a product and no unit key sent (None) takes the product's unit. A blank string
    means the user cleared it and is kept blank. Read through to_jsonb so it works before the migration."""
    if not medidas_enabled():
        return
    ids = {i["product_id"] for i in items if i.get("product_id") is not None and i.get("unit_of_measure") is None}
    if not ids:
        return
    cursor.execute("SELECT id, to_jsonb(products)->>'unit_of_measure' AS u FROM products WHERE id = ANY(%s)", (list(ids),))
    by_id = {r["id"]: r["u"] for r in cursor.fetchall()}
    for i in items:
        if i.get("unit_of_measure") is None and i.get("product_id") in by_id:
            i["unit_of_measure"] = by_id[i["product_id"]]
