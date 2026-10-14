"""Item 12, module 2: log_request() core.

Covers: row contents, parameterized insert, commit and close, never raises,
rollback on failure, stderr message without payload, field clipping, and a
signature with no body or header parameters.
"""
import inspect
import os
import sys
from datetime import datetime, timezone

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import database  # noqa: E402
from core import request_log as rl  # noqa: E402


class _Cursor:
    def __init__(self, sink, fail=False):
        self._sink = sink
        self._fail = fail

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        if self._fail:
            raise RuntimeError("boom: secret-row-content")
        self._sink["sql"] = sql
        self._sink["params"] = params


class _Conn:
    def __init__(self, fail=False):
        self.sink = {}
        self.fail = fail
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def cursor(self, *a, **k):
        return _Cursor(self.sink, fail=self.fail)

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


def _call(**over):
    kwargs = dict(
        method="GET",
        path="/auth/me",
        status_code=200,
        latency_ms=12,
        client_ip="203.0.113.7",
        user_sub="alice",
        is_public=False,
        is_authenticated=True,
        timestamp=datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
    )
    kwargs.update(over)
    return rl.log_request(**kwargs)


def test_writes_one_row_and_returns_true(conn):
    assert _call() is True
    params = conn.sink["params"]
    assert params == (
        datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc),
        "alice",
        "GET",
        "/auth/me",
        200,
        12,
        "203.0.113.7",
        False,
        True,
    )


def test_insert_is_parameterized_and_targets_request_logs(conn):
    _call()
    sql = conn.sink["sql"]
    assert "public.request_logs" in sql
    assert "%s" in sql
    # Values must not be interpolated into the SQL text.
    assert "alice" not in sql and "/auth/me" not in sql


def test_commit_and_close_on_success(conn):
    _call()
    assert conn.committed is True
    assert conn.rolled_back is False
    assert conn.closed is True


def test_default_timestamp_is_utc_now(conn):
    rl.log_request(method="GET", path="/x", status_code=200, latency_ms=1)
    ts = conn.sink["params"][0]
    assert ts.tzinfo is not None
    assert ts.utcoffset().total_seconds() == 0


def test_public_row_has_null_user_and_flags(conn):
    _call(user_sub=None, is_public=True, is_authenticated=False,
          path="/quotes/public/{token}")
    params = conn.sink["params"]
    assert params[1] is None
    assert params[7] is True
    assert params[8] is False


def test_never_raises_when_db_unavailable(monkeypatch, capsys):
    def boom():
        raise ConnectionError("db down")

    monkeypatch.setattr(database, "get_db_connection", boom)
    assert _call() is False  # no exception
    err = capsys.readouterr().err
    assert "request_log: write failed: ConnectionError" in err


def test_never_raises_when_insert_fails_and_rolls_back(monkeypatch, capsys):
    c = _Conn(fail=True)
    monkeypatch.setattr(database, "get_db_connection", lambda: c)
    assert _call() is False
    assert c.rolled_back is True
    assert c.closed is True


def test_failure_message_does_not_echo_payload(monkeypatch, capsys):
    c = _Conn(fail=True)
    monkeypatch.setattr(database, "get_db_connection", lambda: c)
    _call(user_sub="secret-user-sub")
    err = capsys.readouterr().err
    assert "secret-row-content" not in err
    assert "secret-user-sub" not in err


def test_path_is_clipped(conn):
    _call(path="/x/" + "a" * 2000)
    assert len(conn.sink["params"][3]) == rl.PATH_MAX


def test_user_sub_and_ip_are_clipped(conn):
    _call(user_sub="u" * 1000, client_ip="1" * 500)
    params = conn.sink["params"]
    assert len(params[1]) == rl.USER_SUB_MAX
    assert len(params[6]) == rl.CLIENT_IP_MAX


def test_negative_latency_is_floored_to_zero(conn):
    _call(latency_ms=-5)
    assert conn.sink["params"][5] == 0


def test_signature_has_no_body_or_header_parameters():
    params = inspect.signature(rl.log_request).parameters
    forbidden = {"body", "request_body", "response_body", "headers", "payload", "request", "response"}
    assert forbidden.isdisjoint(params.keys())
    assert set(params.keys()) == {
        "method", "path", "status_code", "latency_ms", "client_ip",
        "user_sub", "is_public", "is_authenticated", "timestamp",
    }
