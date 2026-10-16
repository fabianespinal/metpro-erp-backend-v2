"""Quoting v1, phase 5: draft, finalize, totals persistence, Final lock, send guard.

Service-level tests with a fake DB cursor. Router tests call the functions
directly with monkeypatched services. Requires quoting_v1 migration in a real DB.
"""
import os
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes.service as svc  # noqa: E402
import importlib  # noqa: E402
router_mod = importlib.import_module("quotes.router")  # noqa: E402
from quotes.totals import compute_totals  # noqa: E402
from quotes.service import calculate_quote_totals  # noqa: E402

FIXED_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

ITEMS = [
    {"product_name": "IPE 200", "quantity": 4, "unit_price": 100.0,
     "discount_type": "percentage", "discount_value": 5.0,
     "item_type": "product", "description": None},
    {"product_name": "Survey", "quantity": 1, "unit_price": 250.0,
     "discount_type": "none", "discount_value": 0.0,
     "item_type": "service", "description": "On-site walk"},
]
CHARGES = {"supervision": True, "admin": True, "insurance": False,
           "transport": True, "contingency": False}


class FakeCursor:
    def __init__(self, fetchone_rows=(), fetchall_rows=()):
        self.executed = []
        self._one = list(fetchone_rows)
        self._all = list(fetchall_rows)

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._one.pop(0) if self._one else None

    def fetchall(self):
        return self._all.pop(0) if self._all else []


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def _patch_db(monkeypatch, cursor):
    conn = FakeConn(cursor)
    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)
    return conn


# ---------- totals: parity and wiring ----------

@pytest.mark.parametrize("charges", [
    {},
    CHARGES,
    {"supervision": True, "admin": True, "insurance": True, "transport": True, "contingency": True},
])
def test_compute_totals_matches_legacy_grand_total(charges):
    legacy = calculate_quote_totals(ITEMS, charges)
    new = compute_totals(ITEMS, charges)
    assert new["grand_total"] == pytest.approx(legacy["grand_total"])
    assert new["subtotal_general"] == pytest.approx(legacy["subtotal_general"])


def test_compute_totals_tax_default_is_18_percent():
    t = compute_totals(ITEMS, CHARGES)
    assert t["tax_rate"] == 0.18
    assert t["tax_amount"] == pytest.approx(t["subtotal_general"] * 0.18)
    assert t["grand_total"] == pytest.approx(t["subtotal_general"] + t["tax_amount"])


def test_totals_columns_order_and_total_amount_equals_grand_total():
    t = compute_totals(ITEMS, CHARGES)
    subtotal, disc, tax, grand, total_amount = svc._totals_columns(t)
    assert subtotal == t["subtotal_general"]
    assert disc == t["total_discounts"]
    assert tax == t["tax_amount"]
    assert grand == t["grand_total"]
    assert total_amount == t["grand_total"]


def test_totals_update_sql_has_five_params_plus_id():
    assert svc.TOTALS_UPDATE_SQL.count("%s") == 6


# ---------- create: no token, item fields persisted ----------

def test_create_insert_leaves_public_token_out(monkeypatch):
    # create_quote needs client and contact checks, then insert, commit, reselect.
    cursor = FakeCursor(
        fetchone_rows=[{"id": 1}, {"id": 2}, {"quote_id": FIXED_ID, "status": "Draft"}],
        fetchall_rows=[[]],
    )
    _patch_db(monkeypatch, cursor)
    monkeypatch.setattr(svc, "generate_quote_id", lambda: FIXED_ID)
    captured = {}
    monkeypatch.setattr(svc, "execute_values", lambda cur, sql, rows: captured.update(sql=sql, rows=rows))

    svc.create_quote(1, 2, "Proj", None, ITEMS, CHARGES)

    insert_sql = next(sql for sql, _ in cursor.executed if sql.startswith("INSERT INTO quotes"))
    assert "public_token" not in insert_sql
    assert "subtotal" in insert_sql and "grand_total" in insert_sql
    assert "item_type" in captured["sql"] and "description" in captured["sql"]
    assert captured["rows"][0][6:] == ("product", None, None)
    assert captured["rows"][1][6:] == ("service", "On-site walk", None)


# ---------- finalize ----------

def _draft_row(**over):
    row = {"quote_id": FIXED_ID, "status": "Draft", "included_charges": CHARGES, "public_token": None}
    row.update(over)
    return row


def test_finalize_sets_final_token_totals_and_finalized_at(monkeypatch):
    cursor = FakeCursor(
        fetchone_rows=[_draft_row(), {"quote_id": FIXED_ID, "status": "Final"}],
        fetchall_rows=[[dict(i, quote_id=FIXED_ID) for i in ITEMS], []],
    )
    conn = _patch_db(monkeypatch, cursor)
    monkeypatch.setattr(svc.uuid, "uuid4", lambda: FIXED_ID)

    svc.finalize_quote(FIXED_ID)

    assert conn.committed is True
    status_sql, status_params = cursor.executed[2]
    assert "status = %s" in status_sql and "finalized_at = CURRENT_TIMESTAMP" in status_sql
    assert "COALESCE(public_token, %s)" in status_sql
    assert status_params == ("Final", FIXED_ID, FIXED_ID)

    totals_sql, totals_params = cursor.executed[3]
    expected = compute_totals([dict(i) for i in ITEMS], CHARGES)
    assert totals_sql == " ".join(svc.TOTALS_UPDATE_SQL.split())
    assert totals_params[0] == pytest.approx(expected["subtotal_general"])
    assert totals_params[3] == pytest.approx(expected["grand_total"])
    assert totals_params[4] == pytest.approx(expected["grand_total"])
    assert totals_params[-1] == FIXED_ID


def test_finalize_keeps_existing_token(monkeypatch):
    # COALESCE in SQL keeps an existing token. The Python value is only used when NULL.
    cursor = FakeCursor(
        fetchone_rows=[_draft_row(public_token="keep-me"), {"quote_id": FIXED_ID, "status": "Final"}],
        fetchall_rows=[[dict(ITEMS[0], quote_id=FIXED_ID)], []],
    )
    _patch_db(monkeypatch, cursor)
    svc.finalize_quote(FIXED_ID)
    sql = cursor.executed[2][0]
    assert "COALESCE(public_token, %s)" in sql


def test_finalize_rejects_non_draft(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[_draft_row(status="Sent")])
    conn = _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.finalize_quote(FIXED_ID)
    assert exc.value.status_code == 400
    assert getattr(exc.value, "code", None) == "QUOTE_NOT_DRAFT"
    assert conn.rolled_back is True


def test_finalize_missing_quote_is_404(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[None])
    _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.finalize_quote("missing")
    assert exc.value.status_code == 404


# ---------- Final lock ----------

def test_update_quote_blocks_final(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[{"quote_id": FIXED_ID, "status": "Final"}])
    _patch_db(monkeypatch, cursor)

    class _Upd:
        def dict(self, exclude_unset=True):
            return {"project_name": "New"}

    with pytest.raises(HTTPException) as exc:
        svc.update_quote(FIXED_ID, _Upd())
    assert exc.value.status_code == 400
    assert exc.value.code == "QUOTE_FINALIZED"


def test_patch_status_to_final_is_rejected(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[{"quote_id": FIXED_ID, "status": "Draft"}])
    _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.update_quote_status(FIXED_ID, "Final")
    assert exc.value.status_code == 400
    assert exc.value.code == "QUOTE_USE_FINALIZE"


def test_patch_status_away_from_final_is_rejected(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[{"quote_id": FIXED_ID, "status": "Final"}])
    _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.update_quote_status(FIXED_ID, "Sent")
    assert exc.value.status_code == 400
    assert exc.value.code == "QUOTE_USE_SEND"


def test_final_is_in_valid_status_list_for_error_message(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[{"quote_id": FIXED_ID, "status": "Draft"}])
    _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.update_quote_status(FIXED_ID, "Bogus")
    assert "Final" in str(exc.value.detail)


# ---------- send guard ----------

def test_send_blocked_when_no_public_token(monkeypatch):
    monkeypatch.setattr(router_mod.service, "get_quote_with_contact",
                        lambda qid: {"public_token": None, "status": "Draft"})
    with pytest.raises(HTTPException) as exc:
        router_mod.send_quote(FIXED_ID, current_user={})
    assert exc.value.status_code == 400
    assert exc.value.code == "QUOTE_NOT_FINALIZED"


# ---------- draft alias ----------

def test_draft_endpoint_delegates_to_create(monkeypatch):
    calls = {}

    def fake_create(**kwargs):
        calls.update(kwargs)
        return {"quote_id": FIXED_ID, "status": "Draft"}

    monkeypatch.setattr(router_mod.service, "create_quote", fake_create)

    class _Item:
        def dict(self):
            return {"product_name": "IPE", "quantity": 1, "unit_price": 1.0,
                    "discount_type": "none", "discount_value": 0.0,
                    "item_type": "product", "description": None}

    class _Charges:
        def dict(self):
            return dict(CHARGES)

    class _Body:
        client_id = 1
        contact_id = 2
        project_name = "P"
        notes = None
        items = [_Item()]
        included_charges = _Charges()
        payment_terms = None
        valid_until = None

    result = router_mod.create_draft_quote(_Body(), current_user={})
    assert result["status"] == "Draft"
    assert calls["client_id"] == 1
    assert calls["items"][0]["item_type"] == "product"


# ---------- decisions: Final transitions, finalize guards ----------

@pytest.mark.parametrize("target", ["Approved", "Rejected"])
def test_final_can_move_forward(monkeypatch, target):
    cursor = FakeCursor(fetchone_rows=[{"quote_id": FIXED_ID, "status": "Final"}])
    conn = _patch_db(monkeypatch, cursor)
    result = svc.update_quote_status(FIXED_ID, target)
    assert result["status"] == target
    assert conn.committed is True


@pytest.mark.parametrize("target,code", [
    ("Draft", "QUOTE_REOPEN_BLOCKED"),
    ("Sent", "QUOTE_USE_SEND"),
    ("Invoiced", "QUOTE_USE_CONVERT"),
])
def test_final_cannot_move_back(monkeypatch, target, code):
    cursor = FakeCursor(fetchone_rows=[{"quote_id": FIXED_ID, "status": "Final"}])
    _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.update_quote_status(FIXED_ID, target)
    assert exc.value.status_code == 400
    assert exc.value.code == code


def test_finalize_rejects_empty_quote(monkeypatch):
    cursor = FakeCursor(fetchone_rows=[_draft_row()], fetchall_rows=[[]])
    conn = _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.finalize_quote(FIXED_ID)
    assert exc.value.status_code == 400
    assert exc.value.code == "QUOTE_EMPTY"
    assert conn.committed is False
    assert conn.rolled_back is True
    assert not any(sql.startswith("UPDATE quotes") for sql, _ in cursor.executed)


# ---------- product_id persisted and validated (Phase 6 prerequisite) ----------

def test_create_persists_product_id_and_validates_existence(monkeypatch):
    items = [dict(ITEMS[0], product_id=42), dict(ITEMS[1])]
    cursor = FakeCursor(
        fetchone_rows=[{"id": 1}, {"id": 2}, {"quote_id": FIXED_ID, "status": "Draft"}],
        fetchall_rows=[[{"id": 42}], []],
    )
    _patch_db(monkeypatch, cursor)
    monkeypatch.setattr(svc, "generate_quote_id", lambda: FIXED_ID)
    captured = {}
    monkeypatch.setattr(svc, "execute_values", lambda cur, sql, rows: captured.update(rows=rows))
    svc.create_quote(1, 2, "P", None, items, CHARGES)
    assert captured["rows"][0][8] == 42
    assert captured["rows"][1][8] is None


def test_create_rejects_unknown_product_id(monkeypatch):
    items = [dict(ITEMS[0], product_id=999)]
    cursor = FakeCursor(
        fetchone_rows=[{"id": 1}, {"id": 2}],
        fetchall_rows=[[]],
    )
    conn = _patch_db(monkeypatch, cursor)
    with pytest.raises(HTTPException) as exc:
        svc.create_quote(1, 2, "P", None, items, CHARGES)
    assert exc.value.code == "PRODUCT_NOT_FOUND"
    assert conn.committed is False


def test_update_rejects_unknown_product_id_before_delete(monkeypatch):
    cursor = FakeCursor(
        fetchone_rows=[{"quote_id": FIXED_ID, "status": "Draft"}],
        fetchall_rows=[[]],
    )
    _patch_db(monkeypatch, cursor)

    class _Upd:
        def dict(self, exclude_unset=True):
            return {"items": [dict(ITEMS[0], product_id=999)]}

    with pytest.raises(HTTPException) as exc:
        svc.update_quote(FIXED_ID, _Upd())
    assert exc.value.code == "PRODUCT_NOT_FOUND"
    assert not any(sql.startswith("DELETE FROM quote_items") for sql, _ in cursor.executed)
