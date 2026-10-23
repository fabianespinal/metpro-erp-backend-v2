"""A1 tax from charges (2026-10-22). Pure tests; no database.

Toggles are read at call time, so each test sets its own environment.
"""
import pytest

from tax.service import (
    CONSTRUCTION_TAX_CODE,
    charges_trigger_construction_tax,
    tax_code_for_charges,
    tax_from_charges_enabled,
)
from quotes.models import DynamicCharge


def _charges(**flags):
    base = {
        "supervision": False, "supervision_percentage": 10.0,
        "admin": False, "admin_percentage": 4.0,
        "insurance": False, "insurance_percentage": 1.0,
        "transport": False, "transport_percentage": 3.0,
        "contingency": False, "contingency_percentage": 3.0,
        "dynamic_charges": [],
    }
    base.update(flags)
    return base


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TAX_FROM_CHARGES", raising=False)
    monkeypatch.delenv("REQUIRE_CHARGE_NAME", raising=False)


def test_toggle_off_by_default():
    assert tax_from_charges_enabled() is False


def test_no_charges_means_default_type():
    assert tax_code_for_charges(_charges()) is None


@pytest.mark.parametrize("key", ["supervision", "admin", "insurance", "transport", "contingency"])
def test_each_static_charge_triggers_construction(key):
    assert tax_code_for_charges(_charges(**{key: True})) == CONSTRUCTION_TAX_CODE


def test_static_charge_at_zero_percent_does_not_trigger():
    assert tax_code_for_charges(_charges(admin=True, admin_percentage=0)) is None


def test_custom_charge_alone_does_not_trigger_construction():
    # Decision 2026-10-22 (supersedes "any charge"): custom charges never trigger 1.8%.
    c = _charges(dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 10}])
    assert tax_code_for_charges(c) is None


def test_custom_charge_does_not_change_construction_trigger_when_static_present():
    c = _charges(admin=True, admin_percentage=4,
                 dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 10}])
    assert tax_code_for_charges(c) == CONSTRUCTION_TAX_CODE


def test_named_delivery_or_rush_style_charge_does_not_trigger():
    for name in ("Delivery surcharge", "Rush fee", "Ajuste misceláneo", "Temporary custom charge"):
        c = _charges(dynamic_charges=[{"id": "x", "name": name, "enabled": True, "percentage": 5}])
        assert tax_code_for_charges(c) is None, name


def test_disabled_custom_charge_does_not_trigger():
    c = _charges(dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": False, "percentage": 10}])
    assert tax_code_for_charges(c) is None


def test_custom_charge_at_zero_does_not_trigger():
    c = _charges(dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 0}])
    assert charges_trigger_construction_tax(c) is False


def test_legacy_charges_without_dynamic_key():
    assert tax_code_for_charges({"supervision": True, "supervision_percentage": 10}) == CONSTRUCTION_TAX_CODE


def test_malformed_dynamic_entries_are_ignored():
    c = _charges(dynamic_charges=["bad", None, {"enabled": True, "percentage": "x"}])
    assert tax_code_for_charges(c) is None


def test_blank_name_defaults_when_toggle_off():
    dc = DynamicCharge(name="", enabled=True, percentage=5)
    assert dc.name == "Cargo adicional"


def test_blank_name_rejected_when_toggle_on(monkeypatch):
    monkeypatch.setenv("REQUIRE_CHARGE_NAME", "1")
    with pytest.raises(ValueError):
        DynamicCharge(name="", enabled=True, percentage=5)


def test_blank_name_allowed_when_charge_is_zero_and_toggle_on(monkeypatch):
    monkeypatch.setenv("REQUIRE_CHARGE_NAME", "1")
    DynamicCharge(name="", enabled=True, percentage=0)  # no value, no name needed


def test_named_charge_passes_when_toggle_on(monkeypatch):
    monkeypatch.setenv("REQUIRE_CHARGE_NAME", "1")
    dc = DynamicCharge(name=" Prueba ", enabled=True, percentage=5)
    assert dc.name == "Prueba"
