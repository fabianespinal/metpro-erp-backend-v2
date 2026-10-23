"""Engineering Estimate I3: lock helpers, switch, API, Generate, quote lock.

Unit tests run everywhere. Database tests run only with ESTIMATOR_API_TESTS=1 and DATABASE_URL pointing at a
database loaded from tests/fixtures/ci_schema.sql plus the estimator migrations (schema, seed, run_idempotency).
They create their own rows (unique names) and restore the seeded version to draft. Runs are append-only, so the
rows they create stay in the throwaway database.
"""
import json
import os
import sys
import uuid

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-ci-0123456789abcdef")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402
from fastapi.testclient import TestClient  # noqa: E402

from auth.service import create_access_token  # noqa: E402
from core.public_payload import public_payload  # noqa: E402
from estimator import EstimatorInputError, calculate  # noqa: E402
from estimator.inputs import default_inputs  # noqa: E402
from estimator.quote_lock import money_changes  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
DB = os.getenv("ESTIMATOR_API_TESTS") == "1"
needs_db = pytest.mark.skipif(not DB, reason="set ESTIMATOR_API_TESTS=1 with a loaded database")

BODY = {
    "ancho": 18, "largo": 45, "altura_laterales": 9, "altura_techado_lateral": 5,
    "distancia_ejes": 7.5, "columnas_frontales": 6,
    "perfiles": {"columnas": "W12x40", "frontales": "W8x31", "tijerillas": "W14x22", "frenado": "W10x12"},
}


# ---------------- unit: lock helper ----------------
OLD = [{"id": 1, "product_name": "A", "quantity": 2, "unit_price": 100, "discount_type": "none", "discount_value": 0},
       {"id": 2, "product_name": "B", "quantity": 1, "unit_price": 50, "discount_type": "none", "discount_value": 0}]


def test_lock_no_change_when_identical_or_not_sent():
    same = [dict(i, product_name=i["product_name"] + "x") for i in OLD]  # a name edit is not a money change
    assert money_changes(OLD, same, None, None, "t", None) == []
    assert money_changes(OLD, None, None, None, "t", None) == []


def test_lock_detects_each_money_field():
    changed = [dict(OLD[0], unit_price=101), dict(OLD[1], quantity=3)]
    fields = {c["field"] for c in money_changes(OLD, changed, None, None, "t", None)}
    assert fields == {"line 1 unit_price", "line 2 quantity"}
    assert any("discount" in c["field"] for c in money_changes(OLD, [dict(OLD[0], discount_type="percentage", discount_value=5), OLD[1]], None, None, "t", None))


def test_lock_detects_added_removed_lines_charges_and_tax():
    assert [c["field"] for c in money_changes(OLD, OLD[:1], None, None, "t", None)] == ["line 2 removed"]
    assert [c["field"] for c in money_changes(OLD, OLD + [{"product_name": "C"}], None, None, "t", None)] == ["line 3 added"]
    assert [c["field"] for c in money_changes(OLD, None, None, {"supervision": False}, "t", None)] == ["charge supervision"]
    assert [c["field"] for c in money_changes(OLD, None, None, {"admin_percentage": 5}, "t", None)] == ["charge admin_percentage"]
    assert [c["field"] for c in money_changes(OLD, None, None, None, "construction_17_2017", "itbis_18")] == ["tax_type_code"]
    assert money_changes(OLD, None, {"supervision": True}, {"supervision": True, "supervision_percentage": 10.0}, "t", "t") == []


def test_public_payload_hides_quote_type():
    out = public_payload({"quote_number": 1, "quote_type": "engineering_estimate", "items": []})
    assert "quote_type" not in out and out["quote_number"] == 1


def test_core_quantity_override_only_for_fixed_lines():
    base = calculate(default_inputs())
    r = calculate(default_inputs(), quantity_overrides={116: 40})  # crane: typed 35 in the workbook
    assert r.subtotal - base.subtotal == pytest.approx(5 * 18000)
    for row in (78, 88):
        with pytest.raises(EstimatorInputError):
            calculate(default_inputs(), quantity_overrides={row: 1})


# ---------------- switch (no database needed) ----------------
def test_enabled_status_follows_switch_and_needs_login(monkeypatch):
    import auth.service as auth_service
    monkeypatch.setattr(auth_service, "ENFORCE_ACTIVE_CHECK", False)
    assert client.get("/estimator/enabled").status_code == 401
    monkeypatch.delenv("ENGINEERING_ESTIMATE_ENABLED", raising=False)
    assert client.get("/estimator/enabled", headers=_hdr("user")).json()["data"] == {"enabled": False}
    monkeypatch.setenv("ENGINEERING_ESTIMATE_ENABLED", "true")
    assert client.get("/estimator/enabled", headers=_hdr("user")).json()["data"] == {"enabled": True}


def test_missing_token_is_401_even_when_switch_off(monkeypatch):
    monkeypatch.delenv("ENGINEERING_ESTIMATE_ENABLED", raising=False)
    assert client.post("/estimator/calculate", json={}).status_code == 401


def _hdr(role="admin"):
    return {"Authorization": "Bearer " + create_access_token({"sub": f"t_{role}", "role": role, "user_id": "00000000-0000-0000-0000-000000000001"})}


def test_switch_off_every_route_is_404(monkeypatch):
    import auth.service as auth_service
    monkeypatch.setattr(auth_service, "ENFORCE_ACTIVE_CHECK", False)
    monkeypatch.delenv("ENGINEERING_ESTIMATE_ENABLED", raising=False)
    for method, path in (("post", "/estimator/calculate"), ("post", "/estimator/generate"), ("get", "/estimator/profiles"),
                         ("get", "/estimator/runs/1"), ("post", "/estimator/runs/1/parity")):
        r = getattr(client, method)(path, headers=_hdr("admin"), **({"json": {}} if method == "post" else {}))
        assert r.status_code == 404, path
        assert "ESTIMATOR_DISABLED" in r.text, r.text


# ---------------- database ----------------
if DB:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def _conn():
        c = psycopg2.connect(os.environ["DATABASE_URL"])
        c.autocommit = True
        return c

    def _one(sql, args=()):
        c = _conn()
        try:
            cur = c.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, args)
            return cur.fetchone() if cur.description else None
        finally:
            c.close()

    def _all(sql, args=()):
        c = _conn()
        try:
            cur = c.cursor(cursor_factory=RealDictCursor)
            cur.execute(sql, args)
            return cur.fetchall()
        finally:
            c.close()

    def _make_user(role):
        name = f"i3_{role}_{uuid.uuid4().hex[:8]}"
        row = _one("INSERT INTO users (username, password_hash, role, is_active) VALUES (%s, 'x', %s, true) RETURNING id", (name, role))
        token = create_access_token({"sub": name, "role": role, "user_id": str(row["id"])})
        return {"Authorization": f"Bearer {token}"}, str(row["id"])

    @pytest.fixture(scope="module")
    def world():
        from tests.estimator_seed_helper import ensure_seed
        ensure_seed(os.environ["DATABASE_URL"])
        was_active = _one("SELECT active FROM tax_types WHERE code='construction_17_2017'")["active"]
        _one("UPDATE tax_types SET active = true WHERE code='construction_17_2017'")  # inactive in the CI schema, active in production
        _one("UPDATE estimator_versions SET status='active', activated_at=now() WHERE id=(SELECT v.id FROM estimator_versions v JOIN estimator_models m ON m.id=v.model_id WHERE m.name='Nave Industrial' AND v.version='1.0')")
        cid = _one("SELECT coalesce(max(id),0)+1 AS n FROM clients")["n"]
        _one("INSERT INTO clients (id, company_name) VALUES (%s, %s)", (cid, f"I3 client {uuid.uuid4().hex[:6]}"))
        ct = _one("INSERT INTO contacts (company_id, name) VALUES (%s, 'I3 Contact') RETURNING id", (cid,))["id"]
        w = {"client_id": cid, "contact_id": ct, "admin": _make_user("admin"), "user": _make_user("user"), "superadmin": _make_user("superadmin")}
        os.environ["ENGINEERING_ESTIMATE_ENABLED"] = "true"
        yield w
        os.environ.pop("ENGINEERING_ESTIMATE_ENABLED", None)
        _one("UPDATE tax_types SET active = %s WHERE code='construction_17_2017'", (was_active,))
        _one("UPDATE estimator_versions SET status='draft' WHERE status='active' AND id=(SELECT v.id FROM estimator_versions v JOIN estimator_models m ON m.id=v.model_id WHERE m.name='Nave Industrial' AND v.version='1.0')")

    def _gen(world, who="admin", **extra):
        body = dict(BODY, idempotency_key=str(uuid.uuid4()), client_id=world["client_id"], contact_id=world["contact_id"], project_name="I3 test")
        body.update(extra)
        return client.post("/estimator/generate", json=body, headers=world[who][0])

    @needs_db
    def test_role_matrix(world):
        assert client.post("/estimator/calculate", json=BODY).status_code == 401
        assert client.post("/estimator/calculate", json=BODY, headers=world["user"][0]).status_code == 403
        assert client.post("/estimator/generate", json={}, headers=world["user"][0]).status_code == 403
        assert client.get("/estimator/profiles", headers=world["user"][0]).status_code == 403
        for role in ("admin", "superadmin"):
            assert client.post("/estimator/calculate", json=BODY, headers=world[role][0]).status_code == 200

    @needs_db
    def test_calculate_default_case(world):
        r = client.post("/estimator/calculate", json=BODY, headers=world["admin"][0]).json()["data"]
        assert r["subtotal_unrounded"] == pytest.approx(7386322.472)
        assert len(r["lines"]) == 30
        assert sum(l["quote_total"] for l in r["lines"]) == pytest.approx(7386323.64, abs=0.01)  # +1.168 from 2-decimal rounding
        assert r["pounds_by_role"]["columnas"] == pytest.approx(16531.2)
        assert any(w["defect"] == "D4" for w in r["warnings"])
        assert r["totals_preview"]["tax_type_code"] == "construction_17_2017"
        assert "run_id" not in r  # stateless

    @needs_db
    def test_calculate_nothing_saved(world):
        before = _one("SELECT count(*) AS n FROM estimator_runs")["n"]
        client.post("/estimator/calculate", json=BODY, headers=world["admin"][0])
        assert _one("SELECT count(*) AS n FROM estimator_runs")["n"] == before

    @needs_db
    def test_refusals(world):
        h = world["admin"][0]
        assert client.post("/estimator/calculate", json=dict(BODY, largo=50), headers=h).status_code == 400
        assert client.post("/estimator/calculate", json=dict(BODY, distancia_ejes=0), headers=h).status_code == 400
        assert client.post("/estimator/calculate", json=dict(BODY, perfiles=dict(BODY["perfiles"], columnas="W99x99")), headers=h).status_code == 400
        assert client.post("/estimator/calculate", json=dict(BODY, overrides=[{"row": 78, "quantity": 5, "reason": "x"}]), headers=h).status_code == 400
        assert client.post("/estimator/calculate", json=dict(BODY, overrides=[{"row": 116, "quantity": 40, "reason": ""}]), headers=h).status_code == 422
        ok = client.post("/estimator/calculate", json=dict(BODY, overrides=[{"row": 116, "quantity": 40, "reason": "crane 40"}]), headers=h)
        assert ok.status_code == 200 and ok.json()["data"]["overrides"][0]["reason"] == "crane 40"

    @needs_db
    def test_generate_creates_run_and_estimate_quote(world):
        r = _gen(world, overrides=[{"row": 84, "unit_price": 5200, "reason": "bolt supplier increase"}])
        assert r.status_code == 200, r.text
        out = r.json()["data"]
        q = _one("SELECT * FROM quotes WHERE quote_id = %s", (out["quote_id"],))
        assert q["quote_type"] == "engineering_estimate" and q["status"] == "Draft"
        assert q["tax_type_code"] == "construction_17_2017"
        charges = json.loads(q["included_charges"]) if isinstance(q["included_charges"], str) else q["included_charges"]
        assert not any(charges[k] for k in ("supervision", "admin", "insurance", "transport", "contingency"))  # CR-I4-1: charges start off
        items = _all("SELECT * FROM quote_items WHERE quote_id = %s", (out["quote_id"],))
        assert len(items) == 30
        run = _one("SELECT * FROM estimator_runs WHERE id = %s", (out["run_id"],))
        assert str(run["generated_by"]) == world["admin"][1] and run["rule_revision"] == 1
        assert run["overrides"][0]["reason"] == "bolt supplier increase" and run["overrides"][0]["user_id"] == world["admin"][1]
        assert run["snapshot"]["profiles_used"]["columnas"]["lb_per_ft"] == 40
        # totals equal the existing totals engine for the same lines
        from quotes.service import preview_totals
        expected = preview_totals([dict(i, quantity=float(i["quantity"]), unit_price=float(i["unit_price"]), discount_value=float(i["discount_value"])) for i in items], charges, "construction_17_2017")
        assert float(q["grand_total"]) == pytest.approx(expected["grand_total"], abs=0.01)

    @needs_db
    def test_generate_lines_carry_medidas_only_when_switched_on(world, monkeypatch):
        monkeypatch.delenv("PDF_MEDIDAS_ENABLED", raising=False)
        off = _gen(world).json()["data"]["quote_id"]
        assert {r["unit_of_measure"] for r in _all("SELECT unit_of_measure FROM quote_items WHERE quote_id = %s", (off,))} == {None}
        monkeypatch.setenv("PDF_MEDIDAS_ENABLED", "true")
        on = _gen(world).json()["data"]["quote_id"]
        rows = _all("SELECT product_name, unit_of_measure FROM quote_items WHERE quote_id = %s", (on,))
        assert all(r["unit_of_measure"] for r in rows)
        assert {r["unit_of_measure"] for r in rows} <= {"Lb", "Pie", "Unidad", "Cola", "Colas"}
        assert [r["product_name"] for r in rows] == [r["product_name"] for r in _all("SELECT product_name FROM quote_items WHERE quote_id = %s", (off,))]  # descriptions unchanged

    @needs_db
    def test_generate_is_idempotent(world):
        key = str(uuid.uuid4())
        a = _gen(world, idempotency_key=key).json()["data"]
        b = _gen(world, idempotency_key=key).json()["data"]
        assert a["run_id"] == b["run_id"] and a["quote_id"] == b["quote_id"] and b["already_generated"] is True
        assert _one("SELECT count(*) AS n FROM estimator_runs WHERE idempotency_key = %s", (key,))["n"] == 1
        other = _gen(world, who="superadmin", idempotency_key=key)
        assert other.status_code == 409

    @needs_db
    def test_generate_failure_leaves_nothing(world):
        runs, quotes_n = _one("SELECT count(*) AS n FROM estimator_runs")["n"], _one("SELECT count(*) AS n FROM quotes")["n"]
        r = _gen(world, contact_id=world["contact_id"] + 100000)
        assert r.status_code == 400
        assert _one("SELECT count(*) AS n FROM estimator_runs")["n"] == runs
        assert _one("SELECT count(*) AS n FROM quotes")["n"] == quotes_n

    @needs_db
    def test_generate_blocked_for_regular_user_and_switch_off(world, monkeypatch):
        assert _gen(world, who="user").status_code == 403
        monkeypatch.setenv("ENGINEERING_ESTIMATE_ENABLED", "false")
        assert _gen(world, who="admin").status_code == 404

    @needs_db
    def test_parity_panel_compares_typed_values(world):
        run = _gen(world).json()["data"]
        h = world["admin"][0]
        ok = client.post(f"/estimator/runs/{run['run_id']}/parity", json={"values": {"E42": 16531.2, "F122": 7386322.472, "F78": 1405152}}, headers=h).json()["data"]
        assert ok["all_match"] is True
        bad = client.post(f"/estimator/runs/{run['run_id']}/parity", json={"values": {"E42": 16000}}, headers=h).json()["data"]
        assert bad["all_match"] is False and bad["rows"][0]["difference"] == pytest.approx(531.2)
        assert client.post(f"/estimator/runs/{run['run_id']}/parity", json={"values": {"ZZ1": 1}}, headers=h).status_code == 400
        assert client.get(f"/estimator/runs/{run['run_id']}", headers=h).status_code == 200
        assert client.get(f"/estimator/runs/{run['run_id']}", headers=world["user"][0]).status_code == 403

    def _quote_body(world, quote_id):
        q = client.get(f"/quotes/{quote_id}", headers=world["admin"][0]).json()["data"]
        items = [{k: i[k] for k in ("product_name", "quantity", "unit_price", "discount_type", "discount_value", "item_type", "category")} for i in q["items"]]
        for i in items:
            for k in ("quantity", "unit_price", "discount_value"):
                i[k] = float(i[k])
        return q, items

    @needs_db
    def test_lock_regular_user_cannot_change_money_but_can_edit_header(world):
        qid = _gen(world).json()["data"]["quote_id"]
        q, items = _quote_body(world, qid)
        u = world["user"][0]
        # header only, with the full unchanged item list (what the normal edit screen sends)
        assert client.put(f"/quotes/{qid}", json={"notes": "n1", "items": items}, headers=u).status_code == 200
        items[0]["unit_price"] += 1
        r = client.put(f"/quotes/{qid}", json={"items": items}, headers=u)
        assert r.status_code == 403 and "ESTIMATE_LOCKED" in r.text
        r = client.put(f"/quotes/{qid}", json={"included_charges": {"supervision": False}}, headers=u)
        assert r.status_code == 403
        assert client.put(f"/quotes/{qid}", json={"tax_type_code": "itbis_18"}, headers=u).status_code == 403
        assert client.post(f"/quotes/{qid}/send", headers=u).status_code != 403  # not a money action (may fail for other reasons)

    @needs_db
    def test_lock_admin_needs_reason_and_is_audited(world):
        qid = _gen(world).json()["data"]["quote_id"]
        q, items = _quote_body(world, qid)
        old_price = items[0]["unit_price"]
        items[0]["unit_price"] = old_price + 5
        a = world["admin"][0]
        r = client.put(f"/quotes/{qid}", json={"items": items}, headers=a)
        assert r.status_code == 400 and "ESTIMATE_EDIT_REASON_REQUIRED" in r.text
        assert _one("SELECT count(*) AS n FROM quote_edit_audit a JOIN quotes q ON q.id=a.quote_id WHERE q.quote_id=%s", (qid,))["n"] == 0
        r = client.put(f"/quotes/{qid}", json={"items": items, "edit_reason": "client negotiated"}, headers=a)
        assert r.status_code == 200, r.text
        rows = _all("SELECT a.* FROM quote_edit_audit a JOIN quotes q ON q.id=a.quote_id WHERE q.quote_id=%s", (qid,))
        assert len(rows) == 1 and rows[0]["field"] == "line 1 unit_price" and rows[0]["reason"] == "client negotiated"
        assert str(rows[0]["user_id"]) == world["admin"][1] and float(rows[0]["new_value"]) == pytest.approx(old_price + 5)

    @needs_db
    def test_duplicate_keeps_type_and_lock(world):
        qid = _gen(world).json()["data"]["quote_id"]
        dup = client.post(f"/quotes/{qid}/duplicate", headers=world["user"][0])
        assert dup.status_code == 200, dup.text
        new_id = dup.json()["data"]["quote_id"]
        assert _one("SELECT quote_type FROM quotes WHERE quote_id = %s", (new_id,))["quote_type"] == "engineering_estimate"
        _, items = _quote_body(world, new_id)
        items[0]["quantity"] += 1
        assert client.put(f"/quotes/{new_id}", json={"items": items}, headers=world["user"][0]).status_code == 403

    @needs_db
    def test_standard_quote_is_untouched(world):
        body = {"client_id": world["client_id"], "contact_id": world["contact_id"], "project_name": "std",
                "items": [{"product_name": "Viga", "quantity": 2, "unit_price": 500.0}],
                "included_charges": {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}}
        r = client.post("/quotes/", json=body, headers=world["user"][0])
        assert r.status_code == 200, r.text
        qid = r.json()["data"]["quote_id"]
        assert _one("SELECT quote_type FROM quotes WHERE quote_id = %s", (qid,))["quote_type"] is None
        body["items"][0]["unit_price"] = 900.0
        assert client.put(f"/quotes/{qid}", json={"items": body["items"]}, headers=world["user"][0]).status_code == 200
        dup = client.post(f"/quotes/{qid}/duplicate", headers=world["user"][0]).json()["data"]["quote_id"]
        assert _one("SELECT quote_type FROM quotes WHERE quote_id = %s", (dup,))["quote_type"] is None
        assert _one("SELECT count(*) AS n FROM quote_edit_audit a JOIN quotes q ON q.id=a.quote_id WHERE q.quote_id IN (%s,%s)", (qid, dup))["n"] == 0

    @needs_db
    def test_get_quote_returns_quote_type(world):
        est = _gen(world).json()["data"]["quote_id"]
        assert client.get(f"/quotes/{est}", headers=world["user"][0]).json()["data"]["quote_type"] == "engineering_estimate"
        std = client.post("/quotes/", json={"client_id": world["client_id"], "contact_id": world["contact_id"], "project_name": "s",
                          "items": [{"product_name": "V", "quantity": 1, "unit_price": 1.0}],
                          "included_charges": {"supervision": False, "admin": False, "insurance": False, "transport": False, "contingency": False}},
                          headers=world["user"][0]).json()["data"]["quote_id"]
        assert client.get(f"/quotes/{std}", headers=world["user"][0]).json()["data"]["quote_type"] is None

    @needs_db
    def test_public_page_does_not_leak_quote_type(world):
        qid = _gen(world).json()["data"]["quote_id"]
        fin = client.post(f"/quotes/{qid}/finalize", headers=world["admin"][0])
        assert fin.status_code == 200, fin.text
        token = _one("SELECT public_token FROM quotes WHERE quote_id = %s", (qid,))["public_token"]
        pub = client.get(f"/quotes/public/{token}")
        assert pub.status_code == 200 and "quote_type" not in pub.text and "engineering_estimate" not in pub.text
