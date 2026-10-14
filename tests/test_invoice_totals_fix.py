"""
Tests for the invoice line-total fix in convert_quote_to_invoice.

Covers the pure helper _invoice_line_amounts:
- percentage discount applies to the line subtotal
- fixed discount is a flat amount
- no discount leaves the line subtotal unchanged
- NULL discount_value is treated as 0 in the invoice path

Header totals and the full conversion need a database. They are verified by
the rehearsal smoke test, not here.
"""
import os

import pytest

# database.py creates an engine at import. No connection is made.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/placeholder")
os.environ.setdefault("SECRET_KEY", "test-only-secret-not-used-in-prod")

from quotes.service import _invoice_line_amounts  # noqa: E402


def test_percentage_discount_applies_to_line_subtotal():
    item = {"quantity": 2.0, "unit_price": 150.0, "discount_type": "percentage", "discount_value": 10.0}
    discount, line_total = _invoice_line_amounts(item)
    assert discount == 30.0
    assert line_total == 270.0


def test_fixed_discount_is_flat_amount():
    item = {"quantity": 3.0, "unit_price": 12.5, "discount_type": "fixed", "discount_value": 5.0}
    discount, line_total = _invoice_line_amounts(item)
    assert discount == 5.0
    assert line_total == 32.5


def test_no_discount_leaves_subtotal():
    item = {"quantity": 100.0, "unit_price": 12.5, "discount_type": "none", "discount_value": 0.0}
    discount, line_total = _invoice_line_amounts(item)
    assert discount == 0.0
    assert line_total == 1250.0


def test_null_discount_value_treated_as_zero():
    item = {"quantity": 1.0, "unit_price": 50.0, "discount_type": "percentage", "discount_value": None}
    discount, line_total = _invoice_line_amounts(item)
    assert discount == 0.0
    assert line_total == 50.0


@pytest.mark.parametrize("qty,price,pct,expected_line", [
    (1.0, 33.33, 10.0, 30.00),   # 33.33 - 3.333 = 29.997 -> 30.00
    (7.0, 19.99, 5.0, 132.93),
])
def test_percentage_line_totals_round_to_cents(qty, price, pct, expected_line):
    item = {"quantity": qty, "unit_price": price, "discount_type": "percentage", "discount_value": pct}
    _, line_total = _invoice_line_amounts(item)
    assert line_total == pytest.approx(expected_line, abs=0.005)
