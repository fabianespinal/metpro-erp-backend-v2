"""Fixes from the last-3-day surgical audit (2026-10-24).

C1 five-charge tax rule, C2 estimate quotes keep 1.8%, H3 duplicate and finalize follow the rule,
M1 charge names on finalize, M2 zero-total lines, H1 estimate quote delete, H2 user delete, H7 switch parsing.
Database tests need METPRO_LEDGER_TEST_DB (a database loaded with the schema and the estimator, status
history and tax migrations).
"""
import importlib
import json
import os
import sys
import uuid

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException  # noqa: E402

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
CONSTRUCTION = "construction_17_2017"
FIVE_ON = dict(supervision=True, admin=True, insurance=True, transport=True, contingency=True,
               supervision_percentage=10.0, admin_percentage=4.0, insurance_percentage=1.0,
               transport_percentage=3.0, contingency_percentage=3.0, dynamic_charges=[])
ALL_OFF = dict(FIVE_ON, supervision=False, admin=False, insurance=False, transport=False, contingency=False)


# ---------------- no database ----------------

@pytest.mark.parametrize("value,expected", [("on", True), ("ON ", True), ("true", True), ("1", True), ("yes", True),
                                            ("off", False), ("", False), ("enabled", False)])
def test_switch_parser_accepts_the_same_values_everywhere(monkeypatch, value, expected):
    from core.switches import switch_on
    from tax.service import tax_from_charges_enabled
    monkeypatch.setenv("BLOCK_ZERO_LINE_FINALIZE", value)
    monkeypatch.setenv("TAX_FROM_CHARGES", value)
    assert switch_on("BLOCK_ZERO_LINE_FINALIZE") is expected
    assert tax_from_charges_enabled() is expected


def test_require_charge_name_accepts_on(monkeypatch):
    from pydantic import ValidationError
    from quotes.models import DynamicCharge
    monkeypatch.setenv("REQUIRE_CHARGE_NAME", "on")
    with pytest.raises(ValidationError):
        DynamicCharge(name="  ", enabled=True, percentage=5)


def test_custom_charge_alone_keeps_the_default_type():
    from tax.service import tax_code_for_charges
    only_custom = dict(ALL_OFF, dynamic_charges=[{"id": "x", "name": "Limpieza", "enabled": True, "percentage": 10}])
    assert tax_code_for_charges(only_custom) is None
    assert tax_code_for_charges(dict(FIVE_ON)) == CONSTRUCTION


def test_estimates_never_derive(monkeypatch):
    from tax.service import derives_tax_for
    monkeypatch.setenv("TAX_FROM_CHARGES", "true")
    assert derives_tax_for(None) is True
    assert derives_tax_for("standard") is True
    assert derives_tax_for("engineering_estimate") is False
    monkeypatch.setenv("TAX_FROM_CHARGES", "false")
    assert derives_tax_for(None) is False


# ---------------- database ----------------

@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("quotes.service", "tax.service", "users.service", "core.status_history"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setenv("TAX_FROM_CHARGES", "true")
    monkeypatch.delenv("REQUIRE_CHARGE_NAME", raising=False)
    monkeypatch.delenv("BLOCK_ZERO_LINE_FINALIZE", raising=False)
    conn = connect()
    cur = conn.cursor()
    cur.execute("UPDATE tax_types SET active = true WHERE code = %s", (CONSTRUCTION,))
    cur.execute("INSERT INTO clients (company_name) VALUES (%s) RETURNING id", (f"AF {uuid.uuid4().hex[:6]}",))
    client_id = cur.fetchone()["id"]
    cur.execute("INSERT INTO contacts (company_id, name) VALUES (%s, 'AF contact') RETURNING id", (client_id,))
    contact_id = cur.fetchone()["id"]
    conn.commit()
    yield {"connect": connect, "client_id": client_id, "contact_id": contact_id}
    conn.close()


def _item(price=100.0, qty=1.0, dtype="none", dval=0.0, name="AF line"):
    return dict(product_name=name, quantity=qty, unit_price=price, discount_type=dtype, discount_value=dval,
                item_type="custom", description=None, product_id=None, category=None)


def _create(db, charges, items=None, quote_type=None, tax_code=None):
    from quotes import service
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        qid = service.create_quote_in_tx(cur, db["client_id"], db["contact_id"], "AF", None,
                                         items or [_item()], charges, tax_type_code=tax_code, quote_type=quote_type)
        conn.commit()
        return qid
    finally:
        conn.close()


def _row(db, qid):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, status, tax_type_code, tax_rate, tax_amount, subtotal, grand_total FROM quotes WHERE quote_id = %s", (qid,))
        return cur.fetchone()
    finally:
        conn.close()


def _force(db, qid, **cols):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        sets = ", ".join(f"{k} = %s" for k in cols)
        cur.execute(f"UPDATE quotes SET {sets} WHERE quote_id = %s", tuple(cols.values()) + (qid,))
        conn.commit()
    finally:
        conn.close()


@needs_db
def test_c1_custom_charge_only_quote_is_taxed_at_18(db):
    only_custom = dict(ALL_OFF, dynamic_charges=[{"id": "x", "name": "Limpieza", "enabled": True, "percentage": 10}])
    assert _row(db, _create(db, only_custom))["tax_type_code"] == "itbis_18"
    assert _row(db, _create(db, dict(FIVE_ON)))["tax_type_code"] == CONSTRUCTION


@needs_db
def test_c2_estimate_quote_keeps_18_percent_through_create_save_and_preview(db):
    from quotes import service
    from quotes.models import QuoteUpdate
    qid = _create(db, dict(ALL_OFF), quote_type="engineering_estimate", tax_code=CONSTRUCTION)
    assert _row(db, qid)["tax_type_code"] == CONSTRUCTION  # Generate path: charges off, still 1.8%
    service.update_quote(qid, QuoteUpdate(notes="solo notas"), actor={"role": "user", "user_id": None})
    r = _row(db, qid)
    assert r["tax_type_code"] == CONSTRUCTION and float(r["tax_rate"]) == 0.018
    kept = service.preview_totals([_item()], dict(ALL_OFF), CONSTRUCTION, "engineering_estimate")
    derived = service.preview_totals([_item()], dict(ALL_OFF), CONSTRUCTION)
    assert kept["tax_type_code"] == CONSTRUCTION and derived["tax_type_code"] == "itbis_18"


@needs_db
def test_c2_standard_draft_still_follows_the_rule_on_save(db):
    from quotes import service
    from quotes.models import QuoteUpdate
    qid = _create(db, dict(ALL_OFF))
    assert _row(db, qid)["tax_type_code"] == "itbis_18"
    service.update_quote(qid, QuoteUpdate(included_charges=dict(FIVE_ON)), actor={"role": "admin"})
    assert _row(db, qid)["tax_type_code"] == CONSTRUCTION


@needs_db
def test_h3_finalize_applies_the_rule_to_a_stale_draft(db):
    from quotes import service
    qid = _create(db, dict(FIVE_ON))
    _force(db, qid, tax_type_code="itbis_18", tax_rate=0.18, tax_label="ITBIS (18%)")  # draft from before the switch
    service.finalize_quote(qid)
    r = _row(db, qid)
    assert r["status"] == "Final" and r["tax_type_code"] == CONSTRUCTION
    assert abs(float(r["tax_amount"]) - round(float(r["subtotal"]) * 0.018, 2)) <= 0.01


@needs_db
def test_h3_duplicate_follows_the_rule_and_estimate_copy_keeps_its_tax(db):
    from quotes import service
    qid = _create(db, dict(FIVE_ON))
    _force(db, qid, tax_type_code="itbis_18", tax_rate=0.18, tax_label="ITBIS (18%)")
    copy = service.duplicate_quote(qid)
    r = _row(db, copy["quote_id"])
    assert r["tax_type_code"] == CONSTRUCTION
    assert abs(float(r["grand_total"]) - float(r["subtotal"]) - float(r["tax_amount"])) <= 0.01
    est = _create(db, dict(ALL_OFF), quote_type="engineering_estimate", tax_code=CONSTRUCTION)
    est_copy = service.duplicate_quote(est)
    assert _row(db, est_copy["quote_id"])["tax_type_code"] == CONSTRUCTION


@needs_db
def test_m1_finalize_refuses_a_stored_unnamed_charge(db, monkeypatch):
    from quotes import service
    qid = _create(db, dict(FIVE_ON))
    bad = dict(FIVE_ON, dynamic_charges=[{"id": "x", "name": "", "enabled": True, "percentage": 5}])
    _force(db, qid, included_charges=json.dumps(bad))
    monkeypatch.setenv("REQUIRE_CHARGE_NAME", "true")
    with pytest.raises(HTTPException) as e:
        service.finalize_quote(qid)
    assert e.value.status_code == 400 and e.value.code == "CHARGE_NAME_REQUIRED"
    monkeypatch.setenv("REQUIRE_CHARGE_NAME", "false")
    assert service.finalize_quote(qid)["status"] == "Final"


@needs_db
@pytest.mark.parametrize("line", [
    dict(price=0.0), dict(qty=0.0), dict(dtype="percentage", dval=100.0), dict(price=50.0, qty=2.0, dtype="fixed", dval=100.0)])
def test_m2_every_zero_total_line_blocks_finalize(db, monkeypatch, line):
    from quotes import service
    qid = _create(db, dict(FIVE_ON), items=[_item(), _item(name="Linea cero", **line)])
    monkeypatch.setenv("BLOCK_ZERO_LINE_FINALIZE", "on")
    with pytest.raises(HTTPException) as e:
        service.finalize_quote(qid)
    assert e.value.code == "ZERO_PRICE_LINE" and "Linea cero" in e.value.detail


@needs_db
def test_m2_lines_with_a_total_finalize(db, monkeypatch):
    from quotes import service
    qid = _create(db, dict(FIVE_ON), items=[_item(), _item(price=50.0, qty=2.0, dtype="fixed", dval=99.0)])
    monkeypatch.setenv("BLOCK_ZERO_LINE_FINALIZE", "true")
    assert service.finalize_quote(qid)["status"] == "Final"


def _user(db, username):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                    "(gen_random_uuid(), %s, 'x', %s, 'user', true) RETURNING id", (username, f"{username}@test.local"))
        uid = str(cur.fetchone()["id"])
        conn.commit()
        return uid
    finally:
        conn.close()


@needs_db
def test_h1_estimate_quote_with_history_is_refused_cleanly(db):
    from quotes import service
    qid = _create(db, dict(ALL_OFF), quote_type="engineering_estimate", tax_code=CONSTRUCTION)
    uid = _user(db, f"af_{uuid.uuid4().hex[:6]}")
    conn = db["connect"]()
    cur = conn.cursor()
    cur.execute("INSERT INTO quote_edit_audit (quote_id, field, old_value, new_value, reason, user_id) "
                "VALUES (%s, 'quantity', '1', '2', 'prueba', %s)", (_row(db, qid)["id"], uid))
    conn.commit()
    conn.close()
    with pytest.raises(HTTPException) as e:
        service.delete_quote(qid)
    assert e.value.status_code == 400 and e.value.code == "ESTIMATE_QUOTE_HAS_HISTORY"
    plain = _create(db, dict(ALL_OFF))
    assert service.delete_quote(plain)["message"]


@needs_db
def test_h2_user_with_status_history_is_refused_cleanly(db):
    from users import service as users
    uid = _user(db, f"af_{uuid.uuid4().hex[:6]}")
    conn = db["connect"]()
    cur = conn.cursor()
    cur.execute("INSERT INTO status_history (entity_type, entity_key, from_status, to_status, actor_user_id) "
                "VALUES ('quote', 'x', 'Draft', 'Final', %s)", (uid,))
    conn.commit()
    conn.close()
    with pytest.raises(HTTPException) as e:
        users.delete_user(uid, actor_role="superadmin")
    assert e.value.status_code == 400 and e.value.code == "USER_HAS_HISTORY"
    clean = _user(db, f"af_{uuid.uuid4().hex[:6]}")
    assert users.delete_user(clean, actor_role="superadmin")["message"]


def test_missing_percentage_reads_as_the_default_like_the_totals():
    """A partial update stores only the keys sent; the tax rule must read the same default as the totals."""
    from tax.service import tax_code_for_charges
    assert tax_code_for_charges({"supervision": True}) == CONSTRUCTION
    assert tax_code_for_charges({"supervision": True, "supervision_percentage": 0}) is None


@needs_db
def test_partial_api_update_turning_on_a_charge_switches_tax_and_totals_agree(db):
    from quotes import service
    from quotes.models import QuoteUpdate
    qid = _create(db, dict(ALL_OFF))
    upd = QuoteUpdate(**{"included_charges": {"supervision": True, "admin": False, "insurance": False,
                                              "transport": False, "contingency": False}})
    service.update_quote(qid, upd, actor={"role": "admin"})
    r = _row(db, qid)
    assert r["tax_type_code"] == CONSTRUCTION
    assert abs(float(r["subtotal"]) - 110.0) <= 0.01  # 100 + 10% supervision at its default
