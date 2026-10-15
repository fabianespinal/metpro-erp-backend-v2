"""Quote duplicate fix (quoting v1, phase 4).

Service-level tests with a fake DB cursor. Verifies what the duplicate path
writes: exact notes (no prefix), Draft status, public_token NULL, terms copied,
product_id / item_type / description copied on items.
"""
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes.service as svc  # noqa: E402

NEW_ID = "11111111-2222-3333-4444-555555555555"


class FakeCursor:
    def __init__(self, quote_row, item_rows, new_quote_row, new_item_rows):
        self.quote_row = quote_row
        self.item_rows = item_rows
        self.new_quote_row = new_quote_row
        self.new_item_rows = new_item_rows
        self.executed = []
        self._fetchone_queue = [quote_row, new_quote_row]
        self._fetchall_queue = [item_rows, new_item_rows]

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self._fetchone_queue.pop(0)

    def fetchall(self):
        return self._fetchall_queue.pop(0)


class FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, cursor_factory=None):
        return self._cursor

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


ORIGINAL = {
    "quote_id": "orig-1",
    "client_id": 7,
    "contact_id": 3,
    "project_name": "Warehouse",
    "notes": "Site visit on Monday",
    "status": "Sent",
    "included_charges": {"supervision": True},
    "total_amount": 1500.0,
    "payment_terms": "30 days",
    "valid_until": None,
    "terms": "Prices valid 30 days",
}

ORIGINAL_ITEMS = [
    {
        "id": 1, "quote_id": "orig-1", "product_id": 42, "product_name": "IPE 200",
        "quantity": 4.0, "unit_price": 100.0, "discount_type": "percent",
        "discount_value": 5.0, "item_type": "product", "description": None,
    },
    {
        "id": 2, "quote_id": "orig-1", "product_id": None, "product_name": "Site survey",
        "quantity": 1.0, "unit_price": 250.0, "discount_type": "none",
        "discount_value": 0.0, "item_type": "service", "description": "On-site walk",
    },
]

NEW_QUOTE_ROW = {
    "quote_id": NEW_ID, "client_id": 7, "project_name": "Warehouse",
    "notes": "Site visit on Monday", "status": "Draft",
    "included_charges": {}, "total_amount": 1500.0, "payment_terms": "30 days",
    "valid_until": None, "created_at": None, "updated_at": None,
}


def _run(monkeypatch):
    cursor = FakeCursor(ORIGINAL, ORIGINAL_ITEMS, NEW_QUOTE_ROW, [])
    conn = FakeConn(cursor)
    captured = {}

    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)
    monkeypatch.setattr(svc, "generate_quote_id", lambda: NEW_ID)

    def fake_execute_values(cur, sql, rows):
        captured["sql"] = " ".join(sql.split())
        captured["rows"] = rows

    monkeypatch.setattr(svc, "execute_values", fake_execute_values)
    result = svc.duplicate_quote("orig-1")
    return cursor, conn, captured, result


def _insert_quote_call(cursor):
    for sql, params in cursor.executed:
        if sql.startswith("INSERT INTO quotes"):
            return sql, params
    raise AssertionError("no quote insert executed")


def test_duplicate_notes_are_exact_copy(monkeypatch):
    cursor, _, _, _ = _run(monkeypatch)
    _, params = _insert_quote_call(cursor)
    notes_value = params[4]
    assert notes_value == "Site visit on Monday"
    assert "[DUPLICATE]" not in notes_value


def test_duplicate_notes_none_stays_none(monkeypatch):
    original = dict(ORIGINAL, notes=None)
    cursor = FakeCursor(original, [], NEW_QUOTE_ROW, [])
    monkeypatch.setattr(svc, "get_db_connection", lambda: FakeConn(cursor))
    monkeypatch.setattr(svc, "generate_quote_id", lambda: NEW_ID)
    monkeypatch.setattr(svc, "execute_values", lambda *a, **k: None)
    svc.duplicate_quote("orig-1")
    _, params = _insert_quote_call(cursor)
    assert params[4] is None


def test_duplicate_status_draft_and_token_null(monkeypatch):
    cursor, _, _, _ = _run(monkeypatch)
    sql, params = _insert_quote_call(cursor)
    assert params[5] == "Draft"
    assert "public_token" in sql
    assert sql.endswith("NULL)")  # public_token written as literal NULL


def test_duplicate_copies_terms_and_payment_terms(monkeypatch):
    cursor, _, _, _ = _run(monkeypatch)
    _, params = _insert_quote_call(cursor)
    assert params[8] == "30 days"
    assert params[9] == "Prices valid 30 days"


def test_duplicate_items_keep_product_id_type_description(monkeypatch):
    _, _, captured, _ = _run(monkeypatch)
    assert captured["sql"].startswith("INSERT INTO quote_items")
    assert "product_id" in captured["sql"]
    assert "item_type" in captured["sql"]
    assert "description" in captured["sql"]
    rows = captured["rows"]
    assert len(rows) == 2
    # (quote_id, product_id, product_name, quantity, unit_price,
    #  discount_type, discount_value, item_type, description)
    assert rows[0] == (NEW_ID, 42, "IPE 200", 4.0, 100.0, "percent", 5.0, "product", None)
    assert rows[1] == (NEW_ID, None, "Site survey", 1.0, 250.0, "none", 0.0, "service", "On-site walk")


def test_duplicate_items_default_item_type_when_missing(monkeypatch):
    legacy_item = {
        "id": 9, "product_id": 5, "product_name": "Old row", "quantity": 1.0,
        "unit_price": 10.0, "discount_type": "none", "discount_value": 0.0,
    }
    cursor = FakeCursor(ORIGINAL, [legacy_item], NEW_QUOTE_ROW, [])
    captured = {}
    monkeypatch.setattr(svc, "get_db_connection", lambda: FakeConn(cursor))
    monkeypatch.setattr(svc, "generate_quote_id", lambda: NEW_ID)
    monkeypatch.setattr(
        svc, "execute_values", lambda cur, sql, rows: captured.update(rows=rows)
    )
    svc.duplicate_quote("orig-1")
    assert captured["rows"][0][7] == "product"
    assert captured["rows"][0][8] is None


def test_duplicate_commits_and_returns_new_quote(monkeypatch):
    cursor, conn, _, result = _run(monkeypatch)
    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True
    assert result["quote_id"] == NEW_ID
    assert result["status"] == "Draft"


def test_original_quote_not_found_raises_404(monkeypatch):
    from fastapi import HTTPException

    cursor = FakeCursor(None, [], None, [])
    conn = FakeConn(cursor)
    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)
    try:
        svc.duplicate_quote("missing")
    except HTTPException as exc:
        assert exc.status_code == 404
        assert conn.rolled_back is True
    else:
        raise AssertionError("expected HTTPException 404")
