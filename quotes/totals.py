"""Quote totals with an explicit tax rate (quoting v1, phase 3).

Not wired into create or update yet. Same arithmetic as
quotes.service.calculate_quote_totals, but the tax rate is a parameter.

Default TAX_RATE matches current production (ITBIS 18%). Changing the
default changes every customer-facing total and needs explicit approval.

Items are type-agnostic: product, service, and custom lines all count the
same. item_type only affects presentation, not math.
"""
from typing import List, Optional

from quotes.service import calculate_quote_totals as _legacy_totals

TAX_RATE = 0.18  # matches current production ITBIS; see module docstring


def compute_totals(items: List[dict], charges: dict, tax_rate: Optional[float] = None) -> dict:
    """Return the same keys as the legacy function, plus tax_rate and tax_amount.

    tax_amount = subtotal_general * tax_rate.
    grand_total = subtotal_general + tax_amount.
    With tax_rate=0.18 the result is identical to the legacy function.
    """
    rate = TAX_RATE if tax_rate is None else float(tax_rate)
    if rate < 0:
        raise ValueError("La tasa de impuesto debe ser mayor o igual a 0")

    base = _legacy_totals(items, charges)
    subtotal_general = base["subtotal_general"]
    tax_amount = subtotal_general * rate
    grand_total = subtotal_general + tax_amount

    out = dict(base)
    out["itbis"] = tax_amount          # legacy key kept for callers
    out["tax_rate"] = rate
    out["tax_amount"] = tax_amount
    out["grand_total"] = grand_total
    return out
