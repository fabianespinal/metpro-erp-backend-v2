"""Set 6: in-use guards on client, product, contact delete; migrations present and parseable."""
import os
import pathlib
import sys

import pytest
from fastapi import HTTPException

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import clients.service as csvc  # noqa: E402
import contacts.service as ctsvc  # noqa: E402
import products.service as psvc  # noqa: E402


class Cur:
    def __init__(self, ones, rowcount=1):
        self.ones = list(ones)
        self.sql = []
        self.rowcount = rowcount

    def execute(self, sql, params=None):
        self.sql.append(" ".join(sql.split()))

    def fetchone(self):
        return self.ones.pop(0) if self.ones else None


class Conn:
    def __init__(self, cur):
        self.cur, self.committed, self.rolled_back = cur, False, False

    def cursor(self, cursor_factory=None):
        return self.cur

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        pass


def test_client_in_use_is_kept(monkeypatch):
    cur = Cur([{"n": 2}])
    conn = Conn(cur)
    monkeypatch.setattr(csvc, "get_db_connection", lambda: conn)
    with pytest.raises(HTTPException) as exc:
        csvc.delete_client(7)
    assert exc.value.code == "CLIENT_IN_USE"
    assert not any(s.startswith("DELETE") for s in cur.sql)
    assert conn.rolled_back


def test_unused_client_is_deleted(monkeypatch):
    cur = Cur([{"n": 0}])
    conn = Conn(cur)
    monkeypatch.setattr(csvc, "get_db_connection", lambda: conn)
    assert csvc.delete_client(7)["message"] == "Cliente eliminado correctamente"
    assert cur.sql[-1].startswith("DELETE FROM clients") and conn.committed


def test_product_in_template_pack_is_kept(monkeypatch):
    cur = Cur([{"n": 1}])
    monkeypatch.setattr(psvc, "get_db_connection", lambda: Conn(cur))
    with pytest.raises(HTTPException) as exc:
        psvc.delete_product(3)
    assert exc.value.code == "PRODUCT_IN_USE"
    assert not any(s.startswith(("DELETE", "UPDATE")) for s in cur.sql)


def test_product_delete_detaches_lines_first(monkeypatch):
    cur = Cur([{"n": 0}])
    conn = Conn(cur)
    monkeypatch.setattr(psvc, "get_db_connection", lambda: conn)
    psvc.delete_product(3)
    writes = [s for s in cur.sql if s.startswith(("UPDATE", "DELETE"))]
    assert writes == [
        "UPDATE quote_items SET product_id = NULL WHERE product_id = %s",
        "UPDATE invoice_items SET product_id = NULL WHERE product_id = %s",
        "DELETE FROM products WHERE id = %s",
    ]
    assert conn.committed


class FakeQuery:
    def __init__(self, obj):
        self.obj = obj

    def filter(self, *a):
        return self

    def first(self):
        return self.obj


class FakeResult:
    def __init__(self, n):
        self.n = n

    def scalar(self):
        return self.n


class FakeSession:
    def __init__(self, in_use):
        self.in_use, self.deleted = in_use, False

    def query(self, model):
        return FakeQuery(object())

    def execute(self, stmt, params=None):
        return FakeResult(self.in_use)

    def delete(self, obj):
        self.deleted = True

    def commit(self):
        pass


def test_contact_in_use_is_kept():
    db = FakeSession(in_use=1)
    with pytest.raises(HTTPException) as exc:
        ctsvc.delete_contact(db, 4)
    assert exc.value.code == "CONTACT_IN_USE" and not db.deleted


def test_unused_contact_is_deleted():
    db = FakeSession(in_use=0)
    assert ctsvc.delete_contact(db, 4) is True and db.deleted


@pytest.mark.parametrize("name", ["status_checks", "foreign_keys", "not_null", "invoice_items_line_no"])
def test_migration_and_rollback_present_and_marked_not_applied(name):
    mig = ROOT / "migrations" / f"2026-10-16_{name}.sql"
    rb = ROOT / "migrations" / f"2026-10-16_{name}.rollback.sql"
    assert mig.exists() and rb.exists()
    assert "NOT APPLIED" in mig.read_text()
