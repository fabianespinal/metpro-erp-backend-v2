"""Status gate: Approved and Invoiced require a finalized quote.

Service-level tests with a fake DB cursor, same pattern as test_quote_duplicate.py.
A Draft quote must not reach Approved or Invoiced directly, because it has no
public_token and no finalized totals.
"""
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes.service as svc  # noqa: E402


class FakeCursor:
    def __init__(self, current_row):
        self.current_row = current_row
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.current_row


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


def _run(monkeypatch, current_status, new_status):
    cursor = FakeCursor({"quote_id": "q-1", "status": current_status})
    conn = FakeConn(cursor)
    monkeypatch.setattr(svc, "get_db_connection", lambda: conn)
    return cursor, conn, lambda: svc.update_quote_status("q-1", new_status)


def test_draft_cannot_jump_to_approved(monkeypatch):
    cursor, conn, call = _run(monkeypatch, "Draft", "Approved")
    with pytest.raises(Exception) as exc:
        call()
    assert exc.value.code == "QUOTE_NOT_FINALIZED"
    assert conn.rolled_back is True
    assert not any(sql.startswith("UPDATE quotes SET status") for sql, _ in cursor.executed)


def test_draft_cannot_jump_to_invoiced(monkeypatch):
    cursor, conn, call = _run(monkeypatch, "Draft", "Invoiced")
    with pytest.raises(Exception) as exc:
        call()
    assert exc.value.code == "QUOTE_NOT_FINALIZED"
    assert not any(sql.startswith("UPDATE quotes SET status") for sql, _ in cursor.executed)


def test_final_can_be_approved(monkeypatch):
    cursor, conn, call = _run(monkeypatch, "Final", "Approved")
    result = call()
    assert result["status"] == "Approved"
    assert conn.committed is True


def test_approved_can_be_invoiced(monkeypatch):
    cursor, conn, call = _run(monkeypatch, "Approved", "Invoiced")
    result = call()
    assert result["status"] == "Invoiced"
    assert conn.committed is True


def test_final_cannot_go_back_to_draft(monkeypatch):
    cursor, conn, call = _run(monkeypatch, "Final", "Draft")
    with pytest.raises(Exception) as exc:
        call()
    assert exc.value.code == "QUOTE_FINALIZED"
