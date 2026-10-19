"""Product Cost module (2026-10-18): estimated cost and margin for quotes and projects.

Display only. Nothing here writes to quotes, invoices or their totals.

Approved rules:
- Cost basis: the product's CURRENT cost (products.cost). Older quotes follow cost changes.
- Subtotal: the quote subtotal before ITBIS (lines after discount + indirect charges),
  i.e. quotes.subtotal; recomputed from lines + charges when a legacy quote has none.
- Missing cost: a line with no product link, or whose product has no cost, is left OUT of
  the estimated cost and reported through coverage (lines_costed / lines_total).
- estimated_margin = subtotal - estimated_cost; estimated_margin_pct = margin / subtotal * 100.
"""
import json
from typing import Iterable, List, Optional

from core.errors import api_error


def _f(v) -> float:
    return float(v or 0)


def _pct(num: float, den: float) -> Optional[float]:
    return round(num / den * 100, 2) if den else None


def cost_lines(items: Iterable[dict], costs: dict) -> List[dict]:
    """One row per quote line: product, quantity, current unit cost, line cost, costed flag.

    costs maps product_id -> cost (None when the product has no cost).
    """
    out = []
    for it in items:
        pid = it.get("product_id")
        unit_cost = costs.get(pid) if pid is not None else None
        costed = unit_cost is not None
        qty = _f(it.get("quantity"))
        out.append({
            "product_id": pid,
            "product_name": it.get("product_name") or "",
            "category": it.get("category"),
            "quantity": qty,
            "unit_price": round(_f(it.get("unit_price")), 2),
            "unit_cost": round(float(unit_cost), 2) if costed else None,
            "line_cost": round(qty * float(unit_cost), 2) if costed else None,
            "costed": costed,
            "reason": None if costed else ("sin_producto" if pid is None else "sin_costo"),
        })
    return out


def summarize(lines: List[dict], subtotal: float) -> dict:
    """Estimated cost, margin and coverage from cost_lines() output and the pre-ITBIS subtotal."""
    estimated_cost = round(sum(l["line_cost"] for l in lines if l["costed"]), 2)
    subtotal = round(_f(subtotal), 2)
    margin = round(subtotal - estimated_cost, 2)
    total = len(lines)
    costed = sum(1 for l in lines if l["costed"])
    return {
        "subtotal": subtotal,
        "estimated_cost": estimated_cost,
        "estimated_margin": margin,
        "estimated_margin_pct": _pct(margin, subtotal),
        "lines_total": total,
        "lines_costed": costed,
        "coverage_pct": _pct(costed, total) if total else None,
        "complete": total > 0 and costed == total,
    }


def product_costs(cursor, product_ids) -> dict:
    ids = sorted({p for p in product_ids if p is not None})
    if not ids:
        return {}
    cursor.execute("SELECT id, cost FROM products WHERE id = ANY(%s)", (ids,))
    return {r["id"]: (float(r["cost"]) if r["cost"] is not None else None) for r in cursor.fetchall()}


def _charges(raw) -> dict:
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw else {}
        except ValueError:
            return {}
    return raw or {}


def quote_estimate(cursor, quote_id: str) -> dict:
    """Estimate for one saved quote (any status). 404 when the quote does not exist."""
    cursor.execute(
        "SELECT quote_id, quote_number, subtotal, included_charges FROM quotes WHERE quote_id = %s",
        (quote_id,),
    )
    q = cursor.fetchone()
    if not q:
        raise api_error(404, "Cotización no encontrada", "QUOTE_NOT_FOUND")
    cursor.execute(
        "SELECT product_id, product_name, category, quantity, unit_price, discount_type, discount_value "
        "FROM quote_items WHERE quote_id = %s ORDER BY id",
        (quote_id,),
    )
    items = [dict(r) for r in cursor.fetchall()]
    subtotal = q["subtotal"]
    if subtotal is None:  # legacy quote without stored totals: same math as the quote itself
        from quotes.service import calculate_quote_totals
        subtotal = calculate_quote_totals(items, _charges(q["included_charges"]))["subtotal_general"]
    lines = cost_lines(items, product_costs(cursor, (i["product_id"] for i in items)))
    out = summarize(lines, subtotal)
    out.update({"quote_id": q["quote_id"], "quote_label": f"Q-{q['quote_number']}" if q["quote_number"] else None,
                "lines": lines})
    return out


def preview_estimate(cursor, items: List[dict], charges: dict) -> dict:
    """Estimate for unsaved lines (take-off / editor). Same math, nothing stored."""
    from quotes.service import calculate_quote_totals
    subtotal = calculate_quote_totals(items, charges or {})["subtotal_general"]
    lines = cost_lines(items, product_costs(cursor, (i.get("product_id") for i in items)))
    out = summarize(lines, subtotal)
    out["lines"] = lines
    return out


def variance(estimated_cost: float, expenses_total: float, estimated_margin: Optional[float],
             actual_margin: Optional[float]) -> dict:
    """variance = estimated_cost - expenses_total (positive: under budget).
    margin_accuracy_pct = actual_margin / estimated_margin * 100 (None when estimate is 0 or missing)."""
    v = round(_f(estimated_cost) - _f(expenses_total), 2)
    acc = None
    if estimated_margin not in (None, 0) and actual_margin is not None:
        acc = round(actual_margin / estimated_margin * 100, 2)
    return {
        "variance": v,
        "variance_pct": _pct(v, _f(estimated_cost)),
        "margin_accuracy_pct": acc,
    }
