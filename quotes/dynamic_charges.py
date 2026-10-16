"""Dynamic (user-defined) quote charges.

Stored inside quotes.included_charges (JSONB) as:
    "dynamic_charges": [{"id": "x", "name": "Handling", "enabled": true, "percentage": 5}]

Rules (must match the frontend calculateQuoteTotals):
  - at most MAX_DYNAMIC_CHARGES entries count; extras are ignored
  - an entry counts only when enabled is truthy
  - amount = base * percentage / 100, where base is items_after_discount
    (the same base the five static charges use; charges never compound)
  - missing key, null, or malformed entries contribute 0 (legacy quotes)

No imports from other quotes modules, so any layer can use it without a cycle.
"""
from typing import List

MAX_DYNAMIC_CHARGES = 3


def dynamic_charge_lines(charges: dict, base: float) -> List[dict]:
    """Enabled dynamic charges as [{name, percentage, amount}] for a given base."""
    raw = (charges or {}).get("dynamic_charges")
    if not isinstance(raw, list):
        return []
    lines = []
    for dc in raw[:MAX_DYNAMIC_CHARGES]:
        if not isinstance(dc, dict) or not dc.get("enabled"):
            continue
        try:
            pct = float(dc.get("percentage") or 0)
        except (TypeError, ValueError):
            continue
        lines.append({
            "name": str(dc.get("name") or "").strip() or "Cargo adicional",
            "percentage": pct,
            "amount": base * (pct / 100),
        })
    return lines


def dynamic_charges_total(charges: dict, base: float) -> float:
    return sum(line["amount"] for line in dynamic_charge_lines(charges, base))
