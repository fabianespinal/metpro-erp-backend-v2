"""Quoting v1 phase 3: totals parity.

compute_totals(tax_rate=0.18) must match the legacy production function
exactly, for every case below, including item types.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402

from quotes.service import calculate_quote_totals as legacy  # noqa: E402
from quotes.totals import compute_totals, TAX_RATE  # noqa: E402

ALL_CHARGES_ON = {
    "supervision": True, "supervision_percentage": 10.0,
    "admin": True, "admin_percentage": 4.0,
    "insurance": True, "insurance_percentage": 1.0,
    "transport": True, "transport_percentage": 3.0,
    "contingency": True, "contingency_percentage": 3.0,
}
ALL_CHARGES_OFF = {k: False for k in ALL_CHARGES_ON if not k.endswith("_percentage")}
MIXED = dict(ALL_CHARGES_ON, admin=False, transport=False)

CASES = [
    ("empty", [], ALL_CHARGES_ON),
    ("single product", [{"quantity": 2, "unit_price": 10.5, "discount_type": "none", "discount_value": 0}], ALL_CHARGES_ON),
    ("percentage discount", [{"quantity": 3, "unit_price": 100, "discount_type": "percentage", "discount_value": 15}], ALL_CHARGES_ON),
    ("fixed discount", [{"quantity": 4, "unit_price": 25.25, "discount_type": "fixed", "discount_value": 7.5}], MIXED),
    ("mixed items", [
        {"quantity": 2, "unit_price": 10.5, "discount_type": "none", "discount_value": 0},
        {"quantity": 10, "unit_price": 0.25, "discount_type": "percentage", "discount_value": 5},
        {"quantity": 1, "unit_price": 1200, "discount_type": "fixed", "discount_value": 100},
    ], ALL_CHARGES_ON),
    ("charges off", [{"quantity": 5, "unit_price": 19.99, "discount_type": "none", "discount_value": 0}], ALL_CHARGES_OFF),
    ("odd decimals", [{"quantity": 1.333, "unit_price": 7.777, "discount_type": "percentage", "discount_value": 12.5}], MIXED),
    ("null quantity and price", [{"quantity": None, "unit_price": 5, "discount_type": "none", "discount_value": 0}], ALL_CHARGES_ON),
    ("service and custom lines", [
        {"item_type": "service", "quantity": 1, "unit_price": 350, "discount_type": "none", "discount_value": 0},
        {"item_type": "custom", "quantity": 3, "unit_price": 12.2, "discount_type": "fixed", "discount_value": 2},
    ], ALL_CHARGES_ON),
    ("large", [{"quantity": 500, "unit_price": 1234.56, "discount_type": "percentage", "discount_value": 3.25}], ALL_CHARGES_ON),
]

KEYS = [
    "items_total", "total_discounts", "items_after_discount", "supervision", "admin",
    "insurance", "transport", "contingency", "subtotal_general", "itbis", "grand_total",
]


@pytest.mark.parametrize("name, items, charges", CASES, ids=[c[0] for c in CASES])
def test_parity_with_legacy_at_current_tax_rate(name, items, charges):
    old = legacy(items, charges)
    new = compute_totals(items, charges, tax_rate=0.18)
    for key in KEYS:
        assert new[key] == old[key], (name, key, new[key], old[key])
    assert new["tax_amount"] == old["itbis"]


def test_default_rate_is_current_production_rate():
    assert TAX_RATE == 0.18


def test_zero_tax_gives_subtotal_as_grand_total():
    items = CASES[4][1]
    out = compute_totals(items, ALL_CHARGES_ON, tax_rate=0)
    assert out["tax_amount"] == 0
    assert out["grand_total"] == out["subtotal_general"]


def test_negative_tax_rejected():
    with pytest.raises(ValueError):
        compute_totals([], ALL_CHARGES_ON, tax_rate=-0.1)


def test_item_type_does_not_change_math():
    base = [{"quantity": 2, "unit_price": 10, "discount_type": "none", "discount_value": 0}]
    typed = [dict(base[0], item_type="service")]
    assert compute_totals(base, ALL_CHARGES_ON) == compute_totals(typed, ALL_CHARGES_ON)
