"""
Tests for money fields moving from double precision to numeric(12,2).

Scope (Module 5):
- calculate_quote_totals gives the same results for float and Decimal inputs.
- Decimal inputs round to the same cents as float inputs.
- NULL quantity is treated as 0 (existing behavior).
- NULL discount_value raises TypeError (existing behavior, documented here).
- FastAPI JSON encoding turns Decimal into a JSON number with the same value.

Not covered: convert_quote_to_invoice. It needs a live cursor. Verify on staging.
"""
import os
from decimal import Decimal

import pytest

# database.py creates an engine at import. No connection is made. Placeholder is enough.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/placeholder")
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-used-in-prod")

from fastapi.encoders import jsonable_encoder  # noqa: E402
from quotes.service import calculate_quote_totals  # noqa: E402

CENT = Decimal("0.01")

CHARGES_ALL_ON = {
    "supervision": True, "admin": True, "insurance": True,
    "transport": True, "contingency": True,
}


def _as_float(items):
    return [
        {
            "quantity": float(i["quantity"]),
            "unit_price": float(i["unit_price"]),
            "discount_type": i["discount_type"],
            "discount_value": float(i["discount_value"]),
        }
        for i in items
    ]


def _as_decimal(items):
    return [
        {
            "quantity": Decimal(str(i["quantity"])),
            "unit_price": Decimal(str(i["unit_price"])),
            "discount_type": i["discount_type"],
            "discount_value": Decimal(str(i["discount_value"])),
        }
        for i in items
    ]


MIXED_ITEMS = [
    {"quantity": "2.00", "unit_price": "150.00", "discount_type": "percentage", "discount_value": "10.00"},
    {"quantity": "1.00", "unit_price": "999.99", "discount_type": "fixed", "discount_value": "25.00"},
    {"quantity": "3.00", "unit_price": "12.50", "discount_type": "none", "discount_value": "0.00"},
]


def test_float_and_decimal_inputs_match_all_totals():
    float_result = calculate_quote_totals(_as_float(MIXED_ITEMS), CHARGES_ALL_ON)
    dec_result = calculate_quote_totals(_as_decimal(MIXED_ITEMS), CHARGES_ALL_ON)

    assert set(float_result) == set(dec_result)
    for key in float_result:
        assert float(dec_result[key]) == pytest.approx(float_result[key], abs=1e-9), key


def test_decimal_inputs_round_to_same_cents_as_float_inputs():
    float_result = calculate_quote_totals(_as_float(MIXED_ITEMS), CHARGES_ALL_ON)
    dec_result = calculate_quote_totals(_as_decimal(MIXED_ITEMS), CHARGES_ALL_ON)

    for key in ("items_total", "total_discounts", "items_after_discount", "grand_total"):
        f_cents = Decimal(str(round(float_result[key], 2))).quantize(CENT)
        d_cents = Decimal(str(float(dec_result[key]))).quantize(CENT)
        assert f_cents == d_cents, key


def test_no_charges_and_no_discount():
    items = [{"quantity": "1.00", "unit_price": "100.00", "discount_type": "none", "discount_value": "0.00"}]
    result = calculate_quote_totals(_as_decimal(items), {})
    assert float(result["items_total"]) == pytest.approx(100.0)
    assert float(result["grand_total"]) == pytest.approx(118.0)  # 18% ITBIS on 100


def test_null_quantity_is_treated_as_zero():
    items = [{"quantity": None, "unit_price": Decimal("50.00"), "discount_type": "none", "discount_value": Decimal("0")}]
    result = calculate_quote_totals(items, {})
    assert float(result["items_total"]) == 0.0


def test_null_discount_value_raises_current_behavior():
    # Documents existing behavior, not a desired one. float(None) raises for discount rows.
    # The migration keeps discount_value nullable, so this stays a known gap until handled.
    items = [{"quantity": Decimal("1"), "unit_price": Decimal("10"), "discount_type": "fixed", "discount_value": None}]
    with pytest.raises(TypeError):
        calculate_quote_totals(items, {})


def test_decimal_json_encoding_matches_float_value():
    payload = {"total_amount": Decimal("1150.00"), "unit_price": Decimal("12.50")}
    encoded = jsonable_encoder(payload)
    assert encoded == {"total_amount": 1150.0, "unit_price": 12.5}
    assert isinstance(encoded["total_amount"], float)
