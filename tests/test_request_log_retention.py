"""Item 12, module 4: 90-day retention for request_logs.

Covers: cutoff math, dry run vs apply, parameterized SQL, commit and
rollback, errors propagating (not swallowed), CLI defaults, and input checks.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database  # noqa: E402
from core import request_log_retention as rr  # noqa: E402

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if self._conn.fail_on and self._conn.fail_on in sql:
            raise RuntimeError("boom")
        self._conn.executed.append((sql, params))
        if "DELETE" in sql:
            self.rowcount = self._conn.delete_rowcount
        self._last = sql

    def fetchone(self):
        return {"n": self._conn.count}


class _Conn:
    def __init__(self, count=7, delete_rowcount=5, fail_on=None):
        self.count = count
        self.delete_rowcount = delete_rowcount
        self.fail_on = fail_on
        self.executed = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, *a, **k):
        return _Cursor(self)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def conn(monkeypatch):
    c = _Conn()
    monkeypatch.setattr(database, "get_db_connection", lambda: c)
    return c


# ---------- cutoff ----------

def test_default_retention_is_90_days():
    assert rr.RETENTION_DAYS == 90


def test_cutoff_is_now_minus_days():
    assert rr.cutoff_for(90, NOW) == NOW - timedelta(days=90)


@pytest.mark.parametrize("bad", [0, -1, 1.5, "90", True, None])
def test_invalid_days_rejected(bad):
    with pytest.raises(ValueError):
        rr.cutoff_for(bad, NOW)


# ---------- dry run (default) ----------

def test_dry_run_counts_and_does_not_delete(conn):
    result = rr.purge_request_logs(now=NOW)
    assert result == {
        "cutoff": (NOW - timedelta(days=90)).isoformat(),
        "days": 90,
        "matched": 7,
        "deleted": 0,
        "applied": False,
    }
    sqls = [s for s, _ in conn.executed]
    assert all("DELETE" not in s for s in sqls)
    assert conn.rolled_back is True
    assert conn.committed is False
    assert conn.closed is True


# ---------- apply ----------

def test_apply_deletes_and_commits(conn):
    result = rr.purge_request_logs(apply=True, now=NOW)
    assert result["matched"] == 7
    assert result["deleted"] == 5
    assert result["applied"] is True
    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True


def test_sql_is_parameterized_and_uses_cutoff(conn):
    rr.purge_request_logs(apply=True, now=NOW)
    cutoff = NOW - timedelta(days=90)
    for sql, params in conn.executed:
        assert "public.request_logs" in sql
        assert "%s" in sql
        assert params == (cutoff,)
        assert str(cutoff.date()) not in sql


def test_custom_days_changes_cutoff(conn):
    result = rr.purge_request_logs(days=30, now=NOW)
    assert result["cutoff"] == (NOW - timedelta(days=30)).isoformat()
    assert result["days"] == 30


def test_error_rolls_back_and_propagates(monkeypatch):
    c = _Conn(fail_on="DELETE")
    monkeypatch.setattr(database, "get_db_connection", lambda: c)
    with pytest.raises(RuntimeError):
        rr.purge_request_logs(apply=True, now=NOW)
    assert c.rolled_back is True
    assert c.committed is False
    assert c.closed is True


def test_db_connect_error_propagates(monkeypatch):
    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(database, "get_db_connection", boom)
    with pytest.raises(ConnectionError):
        rr.purge_request_logs(now=NOW)


# ---------- CLI ----------

def test_cli_default_is_dry_run(conn, capsys):
    assert rr.main([]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is False
    assert out["deleted"] == 0
    assert all("DELETE" not in s for s, _ in conn.executed)


def test_cli_apply_flag_deletes(conn, capsys):
    assert rr.main(["--apply"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["applied"] is True
    assert out["deleted"] == 5
    assert conn.committed is True


def test_cli_days_flag(conn, capsys):
    assert rr.main(["--days", "30"]) == 0
    assert json.loads(capsys.readouterr().out)["days"] == 30


def test_cli_returns_nonzero_and_no_payload_on_failure(monkeypatch, capsys):
    def boom():
        raise ConnectionError("secret-host-detail")

    monkeypatch.setattr(database, "get_db_connection", boom)
    assert rr.main(["--apply"]) == 1
    captured = capsys.readouterr()
    assert "request_log_retention: failed: ConnectionError" in captured.err
    assert "secret-host-detail" not in captured.err
    assert captured.out == ""


def test_cli_rejects_nonpositive_days(conn, capsys):
    assert rr.main(["--days", "0"]) == 1
    assert "failed: ValueError" in capsys.readouterr().err
