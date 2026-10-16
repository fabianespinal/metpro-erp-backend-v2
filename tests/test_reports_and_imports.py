"""Set 7: revenue from invoices/payments; client import reads skip_duplicates from the form."""
import importlib
import inspect
import os
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import reports.service as rsvc  # noqa: E402

crouter = importlib.import_module("clients.router")


class Cur:
    def __init__(self, ones):
        self.ones, self.sql = list(ones), []

    def execute(self, sql, params=None):
        self.sql.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.ones.pop(0)


class Conn:
    def __init__(self, cur):
        self.cur = cur

    def cursor(self, cursor_factory=None):
        return self.cur

    def close(self):
        pass


def _run(monkeypatch, start=None, end=None, client=None):
    cur = Cur([{"amount": 1000, "n": 2}, {"amount": 400, "n": 3}, {"amount": 600, "n": 1}, {"amount": 250, "n": 1}])
    monkeypatch.setattr(rsvc, "get_db_connection", lambda: Conn(cur))
    return rsvc.get_revenue_report(start, end, client), cur


def test_revenue_is_collected_payments_not_quotes(monkeypatch):
    out, cur = _run(monkeypatch)
    assert out["grand_total"] == 400 and out["summary"]["total_revenue"] == 400
    keys = {r["key"]: r for r in out["revenue_breakdown"]}
    assert keys["invoiced"]["total_revenue"] == 1000
    assert keys["collected"]["total_revenue"] == 400
    assert keys["outstanding"]["total_revenue"] == 600
    assert keys["pipeline"]["total_revenue"] == 250
    assert "FROM invoice_payments" in cur.sql[1][0]
    assert "FROM quotes" not in cur.sql[1][0]


def test_revenue_filters_apply_to_every_query(monkeypatch):
    _, cur = _run(monkeypatch, "2026-10-01", "2026-10-31", 7)
    for sql, params in cur.sql:
        assert "BETWEEN %s AND %s" in sql
        assert params == ["2026-10-01", "2026-10-31", 7]


def test_client_import_skip_duplicates_is_form_field():
    sig = inspect.signature(crouter.import_clients_csv)
    default = sig.parameters["skip_duplicates"].default
    assert type(default).__name__ == "Form"
