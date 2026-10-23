"""Estimator data layer against a real Postgres (I1). Runs only when ESTIMATOR_DB_URL is set.

Needs a database loaded from tests/fixtures/ci_schema.sql plus the three estimator migrations:
2026-10-22_estimator_schema.sql, 2026-10-22_estimator_seed_v1.sql. Tests that change data use a
throwaway version and clean up. Proof: values loaded from the database reproduce the golden cases.
"""
import json
import os
import sys

import pytest

pytestmark = pytest.mark.skipif(not os.getenv("ESTIMATOR_DB_URL"), reason="set ESTIMATOR_DB_URL to a database with the estimator migrations loaded")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import psycopg2  # noqa: E402
from psycopg2.extras import RealDictCursor  # noqa: E402

from estimator import calculate  # noqa: E402
from estimator.inputs import EstimateInputs  # noqa: E402
from estimator.loader import EstimatorVersionError, load_version  # noqa: E402

with open(os.path.join(ROOT, "tests", "fixtures", "estimator_golden.json")) as fh:
    GOLDEN = json.load(fh)


@pytest.fixture
def cur():
    conn = psycopg2.connect(os.environ["ESTIMATOR_DB_URL"])
    c = conn.cursor(cursor_factory=RealDictCursor)
    try:
        yield c
    finally:
        conn.rollback()
        conn.close()


def _seed_version_id(cur):
    cur.execute(
        "SELECT v.id FROM estimator_versions v JOIN estimator_models m ON m.id = v.model_id "
        "WHERE m.name = 'Nave Industrial' AND v.version = '1.0'"
    )
    return cur.fetchone()["id"]


def test_seed_counts(cur):
    vid = _seed_version_id(cur)
    for table, n in (("estimator_profiles", 132), ("estimator_constants", 11), ("estimator_materials", 30)):
        cur.execute(f"SELECT count(*) AS n FROM {table} WHERE version_id = %s", (vid,))
        assert cur.fetchone()["n"] == n, table


def test_seed_version_is_draft_and_refused_by_default(cur):
    vid = _seed_version_id(cur)
    with pytest.raises(EstimatorVersionError):
        load_version(cur, vid)


@pytest.mark.parametrize("case", sorted(GOLDEN))
def test_database_values_reproduce_golden_cases(cur, case):
    lv = load_version(cur, _seed_version_id(cur), allow_draft=True)
    i = GOLDEN[case]["inputs"]
    pick = {w: next(p for p in lv.profiles.values() if p.lb_per_ft == w and p.designation.endswith(f"x{int(w)}"))
            for w in (i["F41"], i["F45"], i["F50"], i["F54"])}
    inputs = EstimateInputs(
        ancho=i["E9"], largo=i["E11"], altura_laterales=i["E13"], altura_techado_lateral=i["E15"],
        distancia_ejes=i["E17"], columnas_frontales=i["E38"],
        perfil_columnas=pick[i["F41"]], perfil_frontales=pick[i["F45"]],
        perfil_tijerillas=pick[i["F50"]], perfil_frenado=pick[i["F54"]],
    )
    r = calculate(inputs, lv.constants, lv.prices)
    assert r.subtotal == pytest.approx(GOLDEN[case]["cells"]["F122"], rel=1e-9)


def test_default_case_profiles_exist_in_table(cur):
    lv = load_version(cur, _seed_version_id(cur), allow_draft=True)
    for name, w in (("W12x40", 40), ("W8x31", 31), ("W14x22", 22), ("W10x12", 12)):
        assert lv.profiles[name].lb_per_ft == w


def test_rule_revision_mismatch_refused(cur):
    vid = _seed_version_id(cur)
    cur.execute("UPDATE estimator_versions SET rule_revision = 99 WHERE id = %s", (vid,))
    with pytest.raises(EstimatorVersionError):
        load_version(cur, vid, allow_draft=True)


def test_changed_material_refused(cur):
    vid = _seed_version_id(cur)
    cur.execute("UPDATE estimator_materials SET driver_key = 'E22' WHERE version_id = %s AND row_ref = 89", (vid,))
    with pytest.raises(EstimatorVersionError):
        load_version(cur, vid, allow_draft=True)


def test_active_version_freezes_children(cur):
    vid = _seed_version_id(cur)
    cur.execute("UPDATE estimator_versions SET status='active', activated_at=now() WHERE id=%s", (vid,))
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute("UPDATE estimator_constants SET value = 3.3 WHERE version_id = %s AND key = 'ft_factor'", (vid,))


def _quote_and_user(cur):
    cur.execute("INSERT INTO users (username, password_hash) VALUES ('i1-test-user', 'x') RETURNING id")
    user = cur.fetchone()["id"]
    cur.execute("INSERT INTO clients (id, company_name) VALUES (9000001, 'I1 test client')")
    cur.execute(
        "INSERT INTO quotes (id, quote_id, client_id, tax_type_code, tax_rate, tax_label) "
        "VALUES (9000001, 'I1-TEST', 9000001, 'itbis_18', 0.18, 'ITBIS')"
    )
    return user


def test_audit_needs_reason_and_is_append_only(cur):
    user = _quote_and_user(cur)
    cur.execute("SAVEPOINT s1")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute(
            "INSERT INTO quote_edit_audit (quote_id, field, old_value, new_value, reason, user_id) "
            "VALUES (9000001, 'unit_price', '1', '2', '   ', %s)", (user,))
    cur.execute("ROLLBACK TO SAVEPOINT s1")
    cur.execute(
        "INSERT INTO quote_edit_audit (quote_id, field, old_value, new_value, reason, user_id) "
        "VALUES (9000001, 'unit_price', '1', '2', 'client agreed', %s) RETURNING id", (user,))
    aid = cur.fetchone()["id"]
    cur.execute("SAVEPOINT s2")
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute("UPDATE quote_edit_audit SET reason = 'changed' WHERE id = %s", (aid,))
    cur.execute("ROLLBACK TO SAVEPOINT s2")
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute("DELETE FROM quote_edit_audit WHERE id = %s", (aid,))


def test_quote_type_check_constraint(cur):
    _quote_and_user(cur)
    cur.execute("UPDATE quotes SET quote_type = 'engineering_estimate' WHERE id = 9000001")
    cur.execute("SAVEPOINT s1")
    with pytest.raises(psycopg2.errors.CheckViolation):
        cur.execute("UPDATE quotes SET quote_type = 'takeoff' WHERE id = 9000001")


def test_runs_are_append_only(cur):
    user = _quote_and_user(cur)
    vid = _seed_version_id(cur)
    cur.execute(
        "INSERT INTO estimator_runs (version_id, rule_revision, generated_by, inputs, snapshot, results) "
        "VALUES (%s, 1, %s, '{}', '{}', '{}') RETURNING id", (vid, user))
    rid = cur.fetchone()["id"]
    with pytest.raises(psycopg2.errors.RaiseException):
        cur.execute("UPDATE estimator_runs SET warnings = '[1]' WHERE id = %s", (rid,))
