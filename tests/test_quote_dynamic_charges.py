"""Dynamic charges (up to 3 user-defined, % of items_after_discount).

Guards: legacy quotes unchanged, math matches the frontend, API model accepts
and keeps dynamic_charges, PDF renders them.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from quotes.dynamic_charges import dynamic_charge_lines, dynamic_charges_total  # noqa: E402
from quotes.models import IncludedCharges, QuoteCreate, QuoteUpdate  # noqa: E402
from quotes.service import calculate_quote_totals  # noqa: E402
from quotes.totals import compute_totals  # noqa: E402
from invoices.service import calculate_invoice_totals  # noqa: E402

ITEMS = [{"quantity": 1, "unit_price": 100, "discount_type": "none", "discount_value": 0}]
STATIC_ON = {
    "supervision": True, "supervision_percentage": 10.0,
    "admin": True, "admin_percentage": 4.0,
    "insurance": True, "insurance_percentage": 1.0,
    "transport": True, "transport_percentage": 3.0,
    "contingency": True, "contingency_percentage": 3.0,
}
STATIC_OFF = {k: False for k in ("supervision", "admin", "insurance", "transport", "contingency")}


def dc(name, pct, enabled=True):
    return {"id": name, "name": name, "enabled": enabled, "percentage": pct}


# ---- legacy behavior ------------------------------------------------------
def test_no_dynamic_key_equals_empty_list():
    a = calculate_quote_totals(ITEMS, dict(STATIC_ON))
    b = calculate_quote_totals(ITEMS, {**STATIC_ON, "dynamic_charges": []})
    assert a == b
    assert set(a) == set(calculate_invoice_totals(ITEMS, dict(STATIC_ON)))  # return keys unchanged
    assert a["subtotal_general"] == pytest.approx(121.0)       # 100 + 21
    assert a["grand_total"] == pytest.approx(121.0 * 1.18)


@pytest.mark.parametrize("bad", [None, "x", 5, {}, [None], ["x"], [{"enabled": True, "percentage": "abc"}]])
def test_malformed_dynamic_is_ignored(bad):
    t = calculate_quote_totals(ITEMS, {**STATIC_ON, "dynamic_charges": bad})
    assert t["subtotal_general"] == pytest.approx(121.0)


# ---- math -----------------------------------------------------------------
def test_one_dynamic_charge():
    t = calculate_quote_totals(ITEMS, {**STATIC_OFF, "dynamic_charges": [dc("Handling", 5)]})
    assert t["subtotal_general"] == pytest.approx(105.0)
    assert t["itbis"] == pytest.approx(105.0 * 0.18)
    assert t["grand_total"] == pytest.approx(105.0 * 1.18)


def test_three_dynamic_charges_with_static():
    charges = {**STATIC_ON, "dynamic_charges": [dc("A", 5), dc("B", 2), dc("C", 3)]}
    t = calculate_quote_totals(ITEMS, charges)
    assert t["subtotal_general"] == pytest.approx(131.0)


def test_disabled_dynamic_excluded():
    t = calculate_quote_totals(ITEMS, {**STATIC_OFF, "dynamic_charges": [dc("A", 5), dc("B", 2, enabled=False)]})
    assert t["subtotal_general"] == pytest.approx(105.0)


def test_fourth_dynamic_charge_ignored():
    charges = {**STATIC_OFF, "dynamic_charges": [dc("A", 1), dc("B", 1), dc("C", 1), dc("D", 50)]}
    assert dynamic_charges_total(charges, 100) == pytest.approx(3.0)


def test_base_is_after_discount_and_charges_do_not_compound():
    items = [{"quantity": 2, "unit_price": 100, "discount_type": "percentage", "discount_value": 10}]
    # 200 - 20 = 180 base. Dynamic 5% of 180 = 9 (not of 180 + static).
    t = calculate_quote_totals(items, {**STATIC_ON, "dynamic_charges": [dc("A", 5)]})
    assert t["items_after_discount"] == pytest.approx(180.0)
    assert dynamic_charges_total({"dynamic_charges": [dc("A", 5)]}, t["items_after_discount"]) == pytest.approx(9.0)
    assert t["subtotal_general"] == pytest.approx(180 + 180 * 0.21 + 9)


def test_blank_name_gets_fallback_label():
    lines = dynamic_charge_lines({"dynamic_charges": [dc("  ", 5)]}, 100)
    assert lines[0]["name"] == "Cargo adicional"


def test_compute_totals_and_invoice_totals_agree_with_quote_totals():
    charges = {**STATIC_ON, "dynamic_charges": [dc("A", 5), dc("B", 2)]}
    q = calculate_quote_totals(ITEMS, charges)
    assert compute_totals(ITEMS, charges)["grand_total"] == pytest.approx(q["grand_total"])
    assert calculate_invoice_totals(ITEMS, charges)["grand_total"] == pytest.approx(q["grand_total"])


# ---- API models -----------------------------------------------------------
def test_legacy_payload_defaults_to_empty_dynamic():
    ic = IncludedCharges(**STATIC_ON)
    assert ic.dynamic_charges == []
    assert QuoteCreate(client_id=1, items=[]).included_charges.dynamic_charges == []


def test_dynamic_charges_survive_roundtrip():
    payload = {**STATIC_ON, "dynamic_charges": [dc("Handling", 5)]}
    ic = IncludedCharges(**payload)
    dumped = ic.model_dump()
    assert dumped["dynamic_charges"] == [{"id": "Handling", "name": "Handling", "enabled": True, "percentage": 5.0}]
    # .dict() is what the service layer calls today
    assert ic.dict()["dynamic_charges"][0]["name"] == "Handling"


def test_update_model_keeps_dynamic_charges():
    u = QuoteUpdate(included_charges={**STATIC_ON, "dynamic_charges": [dc("X", 7)]})
    assert u.included_charges.dict()["dynamic_charges"][0]["percentage"] == 7.0


@pytest.mark.parametrize("bad", [
    [dc("A", 1), dc("B", 1), dc("C", 1), dc("D", 1)],   # more than 3
    [dc("A", -1)],                                      # negative
    [dc("A", 101)],                                     # over 100
    [{"name": "x" * 61, "enabled": True, "percentage": 1}],  # name too long
])
def test_invalid_dynamic_charges_rejected(bad):
    with pytest.raises(ValidationError):
        IncludedCharges(**STATIC_ON, dynamic_charges=bad)


# ---- PDF ------------------------------------------------------------------
def test_pdf_renders_with_dynamic_charges():
    from pdf.utils.layout_utils import build_quote_invoice_pdf

    charges = {**STATIC_ON, "dynamic_charges": [dc("Manejo", 5)]}
    t = calculate_quote_totals(ITEMS, charges)
    items = [{"product_name": "Item", "quantity": 1, "unit_price": 100, "discount_type": "none", "discount_value": 0}]
    stream = build_quote_invoice_pdf(
        doc_type="COTIZACION", doc_id="10001", doc_date="2026-10-16",
        client={"company_name": "ACME", "contact_name": "X", "email": "", "phone": "", "address": ""},
        project_name="P", notes="", items=items, charges=charges,
        items_total=t["items_total"], total_discounts=t["total_discounts"],
        items_after_discount=t["items_after_discount"],
        supervision=t["supervision"], supervision_pct=10.0, admin=t["admin"], admin_pct=4.0,
        insurance=t["insurance"], insurance_pct=1.0, transport=t["transport"], transport_pct=3.0,
        contingency=t["contingency"], contingency_pct=3.0,
        subtotal_general=t["subtotal_general"], itbis=t["itbis"], grand_total=t["grand_total"],
    )
    data = stream.getvalue() if hasattr(stream, "getvalue") else bytes(stream)
    assert data[:4] == b"%PDF"


def test_blank_name_is_defaulted_not_rejected():
    ic = IncludedCharges(**STATIC_ON, dynamic_charges=[{"name": "   ", "enabled": True, "percentage": 2}])
    assert ic.dynamic_charges[0].name == "Cargo adicional"
