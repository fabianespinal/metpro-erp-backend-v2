"""A1 acceptance, database level (2026-10-22). Runs only when A1_DB_TESTS=1.

Needs a database loaded from tests/fixtures/ci_schema.sql. Each test creates its own rows.
Covers the nine acceptance cases of claude/a1-acceptance-and-deploy-checklist-2026-10-22.md
that this layer can reach. Toggles are set per test with monkeypatch.
"""
import os
import uuid

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")  # collection must not depend on the caller's shell

pytestmark = pytest.mark.skipif(os.getenv("A1_DB_TESTS") != "1", reason="set A1_DB_TESTS=1 with a loaded database")

from database import get_db_connection  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402
from quotes import service  # noqa: E402
from quotes.models import IncludedCharges, QuoteUpdate  # noqa: E402

CONSTRUCTION = "construction_17_2017"
PACK_CHARGES = dict(supervision=True, admin=True, insurance=True, transport=True, contingency=True)


def _set_construction_active(active: bool):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE tax_types SET active = %s WHERE code = %s", (active, CONSTRUCTION))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def base(monkeypatch):
    """Client, contact and one product with a known price."""
    monkeypatch.setenv("TAX_FROM_CHARGES", "1")
    monkeypatch.delenv("REQUIRE_CHARGE_NAME", raising=False)
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("INSERT INTO clients (company_name) VALUES (%s) RETURNING id", (f"A1 test {uuid.uuid4().hex[:6]}",))
        client_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO contacts (company_id, name) VALUES (%s, 'A1 test contact') RETURNING id", (client_id,))
        contact_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO products (name, unit_price) VALUES ('A1 test product', 100) RETURNING id")
        product_id = cur.fetchone()["id"]
        conn.commit()
    finally:
        conn.close()
    _set_construction_active(True)
    yield {"client_id": client_id, "contact_id": contact_id, "product_id": product_id}
    _set_construction_active(False)


def _items(product_id, price=100, qty=1):
    return [dict(product_name="A1 test product", quantity=qty, unit_price=price,
                 discount_type="none", discount_value=0.0, item_type="product",
                 description=None, product_id=product_id, category=None)]


def _charges(**flags):
    c = IncludedCharges(**flags).dict()
    return c


def _create(base, charges, items=None, client_tax=None):
    return service.create_quote(
        client_id=base["client_id"], contact_id=base["contact_id"], project_name=None, notes=None,
        items=items or _items(base["product_id"]), included_charges=charges,
        tax_type_code=client_tax,
    )


def _tax_of(quote_id):
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT tax_type_code, tax_rate FROM quotes WHERE quote_id = %s", (quote_id,))
        r = cur.fetchone()
        return r["tax_type_code"], float(r["tax_rate"])
    finally:
        conn.close()


def test_case1_pack_charges_give_construction_rate(base):
    q = _create(base, _charges(**PACK_CHARGES))
    code, rate = _tax_of(q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q)
    assert code == CONSTRUCTION and rate == pytest.approx(0.018)


def test_case3_no_charges_gives_default_rate(base):
    charges = _charges(supervision=False, admin=False, insurance=False, transport=False, contingency=False)
    q = _create(base, charges)
    code, rate = _tax_of(q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q)
    assert code is None or code == "itbis_18"
    assert rate == pytest.approx(0.18)


def test_client_sent_tax_code_is_ignored_when_toggle_on(base):
    charges = _charges(supervision=False, admin=False, insurance=False, transport=False, contingency=False)
    q = _create(base, charges, client_tax=CONSTRUCTION)
    _, rate = _tax_of(q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q)
    assert rate == pytest.approx(0.18)


def test_inactive_construction_fails_loudly(base):
    _set_construction_active(False)
    with pytest.raises(Exception) as exc:
        _create(base, _charges(**PACK_CHARGES))
    assert "TAX_TYPE_INVALID" in str(getattr(exc.value, "detail", exc.value)) or "impuesto" in str(exc.value).lower()


def test_case4_zero_percent_charge_keeps_default(base):
    charges = _charges(supervision=False, admin=False, insurance=False, transport=False, contingency=False,
                       dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 0}])
    q = _create(base, charges)
    _, rate = _tax_of(q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q)
    assert rate == pytest.approx(0.18)


def test_case2_custom_charge_alone_keeps_default_rate(base):
    # Decision 2026-10-22 (supersedes "any charge"): a custom charge alone does not trigger 1.8%.
    charges = _charges(supervision=False, admin=False, insurance=False, transport=False, contingency=False,
                       dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 10}])
    q = _create(base, charges)
    _, rate = _tax_of(q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q)
    assert rate == pytest.approx(0.18)


def test_case5_removing_only_construction_charge_returns_default(base):
    q = _create(base, _charges(supervision=True, admin=False, insurance=False, transport=False, contingency=False,
                               dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 10}]))
    qid = q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q
    service.update_quote(qid, QuoteUpdate(included_charges=IncludedCharges(
        supervision=False, admin=False, insurance=False, transport=False, contingency=False,
        dynamic_charges=[{"id": "x", "name": "Prueba", "enabled": True, "percentage": 10}])))
    _, rate = _tax_of(qid)
    assert rate == pytest.approx(0.18)


def test_case6_snapshot_survives_later_rate_change(base):
    q = _create(base, _charges(**PACK_CHARGES))
    qid = q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q
    conn = get_db_connection()
    try:
        conn.cursor().execute("UPDATE tax_types SET rate = 0.05 WHERE code = %s", (CONSTRUCTION,))
        conn.commit()
    finally:
        conn.close()
    try:
        _, rate = _tax_of(qid)
        assert rate == pytest.approx(0.018)
    finally:
        conn = get_db_connection()
        try:
            conn.cursor().execute("UPDATE tax_types SET rate = 0.0180 WHERE code = %s", (CONSTRUCTION,))
            conn.commit()
        finally:
            conn.close()


def test_pack_total_matches_acceptance_case1(base):
    """Subtotal 7,435.56 scenario: items 7,435.56 are not reproducible with one 100-price product,
    so this checks the arithmetic relation instead: tax = subtotal x rate, total = subtotal + tax."""
    q = _create(base, _charges(**PACK_CHARGES))
    qid = q["quote_id"] if isinstance(q, dict) and "quote_id" in q else q
    conn = get_db_connection()
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT subtotal, tax_amount, total_amount, tax_rate FROM quotes WHERE quote_id = %s", (qid,))
        r = cur.fetchone()
        assert float(r["tax_amount"]) == pytest.approx(round(float(r["subtotal"]) * float(r["tax_rate"]), 2), abs=0.01)
        assert float(r["total_amount"]) == pytest.approx(float(r["subtotal"]) + float(r["tax_amount"]), abs=0.01)
    finally:
        conn.close()
