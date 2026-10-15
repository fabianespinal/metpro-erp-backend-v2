"""Quoting v1 phase 3: item type and description on quote items (model only).

Persistence is Phase 5 (needs the quoting_v1 migration). These tests cover
validation and defaults only.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from quotes.models import QuoteItemBase  # noqa: E402


def test_defaults_keep_existing_payloads_valid():
    item = QuoteItemBase(product_name="Panel", quantity=2, unit_price=10)
    assert item.item_type == "product"
    assert item.description is None


@pytest.mark.parametrize("kind", ["product", "service", "custom"])
def test_allowed_item_types(kind):
    item = QuoteItemBase(product_name="Install", quantity=1, unit_price=350,
                         item_type=kind, description="Labor, 2 days")
    assert item.item_type == kind
    assert item.description == "Labor, 2 days"


@pytest.mark.parametrize("bad", ["Service", "labor", "", "bundle"])
def test_invalid_item_type_rejected(bad):
    with pytest.raises(ValidationError):
        QuoteItemBase(product_name="X", quantity=1, unit_price=1, item_type=bad)
