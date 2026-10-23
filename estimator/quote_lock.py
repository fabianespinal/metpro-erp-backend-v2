"""Money lock for engineering_estimate quotes (Q-H-1, Q-H-3, R2 to R4).

Pure helpers, no database. A quote is an estimate quote when quote_type == 'engineering_estimate';
every other quote (NULL, standard, template) is untouched by this module.
Money fields: line quantity, unit price, discount type and value, adding or removing lines,
included charges (flags and percentages) and the tax type. Everything else stays editable.
"""
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, List, Optional

ESTIMATE_TYPE = "engineering_estimate"
ADMIN_ROLES = ("admin", "superadmin")

DEFAULT_CHARGES = {
    "supervision": True, "supervision_percentage": 10.0,
    "admin": True, "admin_percentage": 4.0,
    "insurance": True, "insurance_percentage": 1.0,
    "transport": True, "transport_percentage": 3.0,
    "contingency": True, "contingency_percentage": 3.0,
}


def is_estimate(quote: dict) -> bool:
    return (quote or {}).get("quote_type") == ESTIMATE_TYPE


def _num(value) -> Decimal:
    return Decimal(str(value if value is not None else 0)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _line(item: dict) -> dict:
    return {
        "quantity": _num(item.get("quantity", 1)),
        "unit_price": _num(item.get("unit_price", 0)),
        "discount_type": item.get("discount_type") or "none",
        "discount_value": _num(item.get("discount_value", 0)),
    }


def _charges(raw: Optional[dict]) -> dict:
    merged = dict(DEFAULT_CHARGES)
    merged.update(raw or {})
    return {k: (bool(v) if isinstance(DEFAULT_CHARGES.get(k), bool) else _num(v)) for k, v in merged.items()
            if k in DEFAULT_CHARGES}


def money_changes(
    old_items: Iterable[dict], new_items: Optional[List[dict]],
    old_charges: Optional[dict], new_charges: Optional[dict],
    old_tax_code: Optional[str], new_tax_code: Optional[str],
) -> List[dict]:
    """Return one entry per changed money field: {item_id, field, old, new}. Empty list = no money change.

    A field the update does not send (None) is not a change. Lines are compared by position."""
    changes: List[dict] = []
    old_list = [dict(i) for i in old_items]
    if new_items is not None:
        new_list = [i if isinstance(i, dict) else dict(i) for i in new_items]
        for idx in range(max(len(old_list), len(new_list))):
            o = old_list[idx] if idx < len(old_list) else None
            n = new_list[idx] if idx < len(new_list) else None
            label = f"line {idx + 1}"
            if o is None:
                changes.append({"item_id": None, "field": f"{label} added", "old": None, "new": n.get("product_name")})
            elif n is None:
                changes.append({"item_id": o.get("id"), "field": f"{label} removed", "old": o.get("product_name"), "new": None})
            else:
                lo, ln = _line(o), _line(n)
                for key in lo:
                    if lo[key] != ln[key]:
                        changes.append({"item_id": o.get("id"), "field": f"{label} {key}", "old": str(lo[key]), "new": str(ln[key])})
    if new_charges is not None:
        co, cn = _charges(old_charges), _charges(new_charges)
        for key in co:
            if co[key] != cn[key]:
                changes.append({"item_id": None, "field": f"charge {key}", "old": str(co[key]), "new": str(cn[key])})
    if new_tax_code is not None and new_tax_code != old_tax_code:
        changes.append({"item_id": None, "field": "tax_type_code", "old": old_tax_code, "new": new_tax_code})
    return changes
