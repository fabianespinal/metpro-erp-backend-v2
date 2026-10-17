"""Phase 2, module 1: approval creates a project; labels; failure never blocks approval."""
import os
import pathlib
import sys

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import quotes  # noqa: E402,F401  (import order: quotes before pdf/projects)
import projects.service as psvc  # noqa: E402
import quotes.service as qsvc  # noqa: E402


class Cur:
    def __init__(self, ones=None, alls=None):
        self.ones, self.alls, self.log = list(ones or []), list(alls or []), []
    def execute(self, sql, params=None):
        self.log.append((" ".join(sql.split()), params))
    def fetchone(self):
        return self.ones.pop(0) if self.ones else None
    def fetchall(self):
        return self.alls.pop(0) if self.alls else []


def test_project_label():
    assert psvc.project_label(1) == "P-0001"
    assert psvc.project_label(12345) == "P-12345"


def test_create_project_from_quote_fields():
    cur = Cur(
        ones=[{"quote_id": "u1", "quote_number": 10002, "client_id": 5, "project_name": "Nave A", "client_address": "Calle 1"},
              {"id": 7}],
        alls=[[{"product_name": "Viga"}, {"product_name": "Pintura"}]],
    )
    assert psvc.create_project_from_quote(cur, "u1") == 7
    sql, params = cur.log[-1]
    assert sql.startswith("INSERT INTO projects") and "'pending'" in sql and "ON CONFLICT (quote_id)" in sql
    assert params == (5, "Nave A", "Viga, Pintura", "Calle 1", "u1", 10002)


def test_name_falls_back_to_quote_label_and_second_call_is_noop():
    cur = Cur(ones=[{"quote_id": "u1", "quote_number": 10002, "client_id": 5, "project_name": None, "client_address": None}, None],
              alls=[[]])
    assert psvc.create_project_from_quote(cur, "u1") is None   # conflict: no row returned
    assert cur.log[-1][1][1] == "Proyecto Q-10002"


def test_enrich_adds_labels():
    d = psvc._enrich({"id": 3, "quote_number": 10002})
    assert d["project_number"] == "P-0003" and d["quote_label"] == "Q-10002"
    assert psvc._enrich({"id": 4, "quote_number": None})["quote_label"] is None


class Conn:
    def __init__(self, cur): self._cur, self.committed, self.rolled = cur, False, False
    def cursor(self, **kw): return self._cur
    def commit(self): self.committed = True
    def rollback(self): self.rolled = True
    def close(self): pass


def test_approval_creates_project_in_same_transaction(monkeypatch):
    cur = Cur(ones=[{"quote_id": "q", "status": "Sent"}])
    conn = Conn(cur)
    monkeypatch.setattr(qsvc, "get_db_connection", lambda: conn)
    seen = {}
    import projects.service as ps
    monkeypatch.setattr(ps, "create_project_from_quote", lambda c, qid: seen.setdefault("qid", qid))
    out = qsvc.update_quote_status("q", "Approved")
    assert out["status"] == "Approved" and seen["qid"] == "q" and conn.committed
    sqls = [s for s, _ in cur.log]
    assert any("SAVEPOINT project_from_quote" in s for s in sqls)


def test_project_failure_does_not_block_approval(monkeypatch):
    cur = Cur(ones=[{"quote_id": "q", "status": "Sent"}])
    conn = Conn(cur)
    monkeypatch.setattr(qsvc, "get_db_connection", lambda: conn)
    import projects.service as ps
    def boom(c, qid): raise RuntimeError("db")
    monkeypatch.setattr(ps, "create_project_from_quote", boom)
    out = qsvc.update_quote_status("q", "Approved")
    assert out["status"] == "Approved" and conn.committed
    assert any("ROLLBACK TO SAVEPOINT project_from_quote" in s for s, _ in cur.log)


def test_rejection_creates_no_project(monkeypatch):
    cur = Cur(ones=[{"quote_id": "q", "status": "Sent"}])
    monkeypatch.setattr(qsvc, "get_db_connection", lambda: Conn(cur))
    qsvc.update_quote_status("q", "Rejected")
    assert not any("SAVEPOINT" in s for s, _ in cur.log)
