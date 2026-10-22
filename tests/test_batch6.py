"""Debug pass batch 6: B-15 CORS origins, B-19 invoice line order, E-11 PDF filename."""
import importlib
import os
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")
USER_ID = "00000000-0000-0000-0000-000000000001"


def _load_main(monkeypatch, **env):
    for k in ("CORS_EXTRA_ORIGINS", "CORS_LEGACY_ORIGINS", "TRUSTED_PROXY_HOSTS"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    sys.modules.pop("main", None)
    return importlib.import_module("main")


def _preflight(app, origin):
    r = TestClient(app).options("/auth/me", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    return r.headers.get("access-control-allow-origin")


def test_b15_default_origins_are_production_only(monkeypatch):
    m = _load_main(monkeypatch)
    assert m.allowed_origins == ["https://app.metprord.com", "https://metprord.site"]
    assert _preflight(m.app, "https://app.metprord.com") == "https://app.metprord.com"
    assert _preflight(m.app, "http://localhost:3000") is None
    assert _preflight(m.app, "https://metpro-erp-frontend-staging-production.up.railway.app") is None


def test_b15_extra_and_legacy_toggles(monkeypatch):
    m = _load_main(monkeypatch, CORS_EXTRA_ORIGINS="http://localhost:3000, https://x.example/")
    assert "http://localhost:3000" in m.allowed_origins and "https://x.example" in m.allowed_origins
    m = _load_main(monkeypatch, CORS_LEGACY_ORIGINS="true")
    assert "http://localhost:3000" in m.allowed_origins
    assert "https://metpro-erp-frontend-staging-production.up.railway.app" in m.allowed_origins
    _load_main(monkeypatch)  # leave the module in its default state


def test_b19_convert_writes_line_no():
    import inspect
    from quotes import service
    src = inspect.getsource(service.convert_quote_to_invoice)
    assert "line_no) VALUES %s" in src and "enumerate(items, start=1)" in src


@needs_db
def test_b19_lines_follow_line_no_then_ctid(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor
    import invoices.service as isvc

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    monkeypatch.setattr(isvc, "get_db_connection", connect)
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE invoice_items, invoices, quote_items, quotes, clients RESTART IDENTITY CASCADE")
    cur.execute("INSERT INTO clients (company_name) VALUES ('C') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO invoices (invoice_number, client_id, status, total_amount, invoice_date, tax_type_code, tax_rate, tax_label) "
                "VALUES ('F-1', %s, 'Pending', 3, '2026-10-17', 'itbis_18', 0.18, 'ITBIS (18%%)') RETURNING id", (cid,))
    inv = cur.fetchone()["id"]
    for desc, no in (("tres", 3), ("uno", 1), ("dos", 2), ("legacy", None)):
        cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, discount, total, line_no) "
                    "VALUES (%s, %s, 1, 1, 0, 1, %s)", (inv, desc, no))
    conn.commit()
    conn.close()
    lines, source = isvc._invoice_lines(connect().cursor(), {"id": inv})
    assert source == "invoice_items"
    assert [l["product_name"] for l in lines] == ["uno", "dos", "tres", "legacy"]
