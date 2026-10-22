"""A2 Payment correction and audit trail.

Unit tests run everywhere. Integration tests need Postgres with the production schema plus
2026-10-22_payment_corrections (METPRO_LEDGER_TEST_DB); skipped otherwise.
"""
import importlib
import os
import re
import sys

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost:5432/test")
ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)

import quotes  # noqa: F401,E402  (import order)
from fastapi.testclient import TestClient  # noqa: E402

import auth.service as auth_service  # noqa: E402
from auth.service import create_access_token  # noqa: E402
from main import app  # noqa: E402

client = TestClient(app)
USER_ID = "00000000-0000-0000-0000-000000000001"
ADMIN_ID = "00000000-0000-0000-0000-000000000002"


def _hdr(role="user"):
    uid = ADMIN_ID if role == "admin" else USER_ID
    return {"Authorization": "Bearer " + create_access_token({"sub": f"t_{role}", "role": role, "user_id": uid})}


def _sql(name):
    lines = open(os.path.join(ROOT, "migrations", name), encoding="utf-8").read().splitlines()
    return "\n".join(l.split("--")[0] for l in lines).upper()


# ---------------- migration shape ----------------

def test_migration_is_additive_and_invents_nothing():
    sql = _sql("2026-10-22_payment_corrections.sql")
    for forbidden in ("DROP ", "DELETE FROM", "UPDATE ", "TRUNCATE", "RENAME", "SET NOT NULL"):
        assert forbidden not in sql, forbidden
    # Only two SET DEFAULTs: new rows get backfilled=false and a real created_at. Existing rows are untouched.
    assert re.findall(r"ALTER COLUMN (\w+) SET DEFAULT (\w+)", sql) == [("BACKFILLED", "FALSE"), ("CREATED_AT", "NOW")]
    assert "BACKFILLED          BOOLEAN NOT NULL DEFAULT TRUE" in re.sub(r"\s+", " ", sql).replace("BACKFILLED BOOLEAN", "BACKFILLED          BOOLEAN") or \
        "BACKFILLED BOOLEAN NOT NULL DEFAULT TRUE" in re.sub(r"\s+", " ", sql)
    assert "CREATED_AT TIMESTAMPTZ," in re.sub(r"\s+", " ", sql)  # nullable, no default at ADD time: no timestamp invented


def test_rollback_refuses_when_corrections_exist():
    sql = _sql("2026-10-22_payment_corrections.rollback.sql")
    assert "RAISE EXCEPTION" in sql and "CORRECTS_PAYMENT_ID IS NOT NULL" in sql
    assert sql.index("RAISE EXCEPTION") < sql.index("DROP COLUMN")


def test_immutability_trigger_is_a_separate_optional_migration():
    sql = _sql("2026-10-22_payment_immutability.sql")
    assert "BEFORE UPDATE" in sql and "BEFORE DELETE" in sql and "TRUNCATE" not in sql.split("$$")[1]
    # The main migration does not install it.
    assert "TRIGGER" not in _sql("2026-10-22_payment_corrections.sql")


def test_correction_route_is_admin_only_and_toggled():
    import inspect
    router = importlib.import_module("invoices.router")
    src = inspect.getsource(router.correct_invoice_payment)
    assert "payment_correction_enabled()" in src and "_allowed_roles(\"admin\")" in src
    svc = importlib.import_module("invoices.payments.service")
    assert svc.payment_correction_enabled() is True  # approved: on at launch


def test_correction_is_on_when_the_variable_is_unset(monkeypatch):
    svc = importlib.import_module("invoices.payments.service")
    monkeypatch.delenv("PAYMENT_CORRECTION_ENABLED", raising=False)
    assert svc.payment_correction_enabled() is True


@pytest.mark.parametrize("value,expected", [("true", True), ("1", True), ("false", False), ("", False), ("no", False)])
def test_toggle_values(monkeypatch, value, expected):
    svc = importlib.import_module("invoices.payments.service")
    monkeypatch.setenv("PAYMENT_CORRECTION_ENABLED", value)
    assert svc.payment_correction_enabled() is expected


# ---------------- integration ----------------

DSN = os.environ.get("METPRO_LEDGER_TEST_DB")
needs_db = pytest.mark.skipif(not DSN, reason="METPRO_LEDGER_TEST_DB not set")


@pytest.fixture
def db(monkeypatch):
    import psycopg2
    from psycopg2.extras import RealDictCursor

    def connect():
        return psycopg2.connect(DSN, cursor_factory=RealDictCursor)

    for mod in ("database", "invoices.service", "invoices.router", "pdf.service", "reports.service"):
        monkeypatch.setattr(importlib.import_module(mod), "get_db_connection", connect, raising=False)
    monkeypatch.setattr(auth_service, "_assert_user_active", lambda u: None)
    monkeypatch.setenv("PAYMENT_CORRECTION_ENABLED", "true")
    conn = connect()
    cur = conn.cursor()
    cur.execute("TRUNCATE conduces, invoice_payments, invoice_items, invoices, quote_items, expenses, projects, quotes, "
                "template_pack_items, template_pack_categories, template_packs, products, contacts, clients "
                "RESTART IDENTITY CASCADE")
    for uid, name, role in ((USER_ID, "t_user", "user"), (ADMIN_ID, "t_admin", "admin")):
        cur.execute("INSERT INTO users (id, username, password_hash, email, role, is_active) VALUES "
                    "(%s, %s, 'x', %s, %s, true) ON CONFLICT DO NOTHING", (uid, name, f"{name}@test.local", role))
    cur.execute("INSERT INTO clients (company_name) VALUES ('Cliente A2') RETURNING id")
    cid = cur.fetchone()["id"]
    cur.execute("INSERT INTO invoices (invoice_number, client_id, status, total_amount, grand_total, invoice_date, "
                "tax_type_code, tax_rate, tax_label) VALUES ('F-A2', %s, 'Pending', 1000, 1000, '2026-10-17', "
                "'itbis_18', 0.18, 'ITBIS (18%%)') RETURNING id", (cid,))
    iid = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return {"iid": iid, "connect": connect}


def _rows(db, sql, params=()):
    conn = db["connect"]()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


def _pay(db, amount, user="user", date="2026-10-18"):
    r = client.post(f"/invoices/{db['iid']}/payments",
                    json={"amount": amount, "method": "Transferencia", "payment_date": date}, headers=_hdr(user))
    assert r.status_code == 200, r.text
    return r.json()["data"]["payment_id"]


def _correct(db, pid, amount, reason="Monto mal digitado", user="admin", **over):
    body = {"amount": amount, "method": "Cheque", "payment_date": "2026-10-19", "notes": "corregido", "reason": reason}
    body.update(over)
    return client.post(f"/invoices/{db['iid']}/payments/{pid}/correct", json=body, headers=_hdr(user))


def _invoice(db):
    return _rows(db, "SELECT status, amount_paid, amount_due FROM invoices WHERE id = %s", (db["iid"],))[0]


@needs_db
def test_new_payment_records_who_and_when_and_is_not_backfilled(db):
    pid = _pay(db, 100)
    row = _rows(db, "SELECT created_at, created_by_user_id, backfilled FROM invoice_payments WHERE id = %s", (pid,))[0]
    assert row["created_at"] is not None and str(row["created_by_user_id"]) == USER_ID and row["backfilled"] is False


@needs_db
def test_correct_voids_old_links_new_and_recomputes_balance(db):
    a = _pay(db, 300)
    r = _correct(db, a, 250)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["voided_payment_id"] == a and d["correction_chain_id"] == a
    assert (d["amount_paid"], d["amount_due"], d["status"]) == (250.0, 750.0, "Pending")
    rows = {p["id"]: p for p in _rows(db, "SELECT * FROM invoice_payments ORDER BY id")}
    old, new = rows[a], rows[d["payment_id"]]
    # The old payment is kept exactly as recorded, only voided.
    assert float(old["amount"]) == 300 and old["method"] == "Transferencia" and str(old["payment_date"]) == "2026-10-18"
    assert old["voided_at"] and old["void_reason"] == "Monto mal digitado" and str(old["voided_by_user_id"]) == ADMIN_ID
    assert old["corrects_payment_id"] is None and old["correction_chain_id"] is None
    # The new one points back, carries who/when, and is not flagged backfilled.
    assert new["corrects_payment_id"] == a and new["correction_chain_id"] == a
    assert str(new["created_by_user_id"]) == ADMIN_ID and new["created_at"] and new["backfilled"] is False
    assert new["voided_at"] is None and float(new["amount"]) == 250


@needs_db
def test_chain_keeps_the_first_payment_as_its_id(db):
    a = _pay(db, 100)
    b = _correct(db, a, 120).json()["data"]["payment_id"]
    c = _correct(db, b, 90, reason="otra vez").json()["data"]
    listed = {p["id"]: p for p in client.get(f"/invoices/{db['iid']}/payments", headers=_hdr()).json()["data"]}
    assert {listed[x]["correction_chain_id"] for x in (a, b, c["payment_id"])} == {a}
    assert listed[a]["corrected_by_payment_id"] == b and listed[b]["corrected_by_payment_id"] == c["payment_id"]
    assert listed[c["payment_id"]]["corrected_by_payment_id"] is None
    assert listed[b]["corrects_payment_id"] == a and listed[c["payment_id"]]["corrects_payment_id"] == b
    assert listed[a]["voided_at"] and listed[b]["voided_at"] and listed[c["payment_id"]]["voided_at"] is None
    assert _invoice(db)["amount_paid"] == 90


@needs_db
def test_unrelated_payment_has_no_chain(db):
    a = _pay(db, 100)
    other = _pay(db, 50)
    _correct(db, a, 80)
    listed = {p["id"]: p for p in client.get(f"/invoices/{db['iid']}/payments", headers=_hdr()).json()["data"]}
    assert listed[other]["correction_chain_id"] is None and listed[other]["corrected_by_payment_id"] is None


@needs_db
def test_paid_invoice_returns_to_pending_and_back(db):
    a = _pay(db, 1000)
    assert _invoice(db)["status"] == "Paid"
    d = _correct(db, a, 900).json()["data"]
    assert (d["status"], d["amount_due"]) == ("Pending", 100.0)
    d = _correct(db, d["payment_id"], 1000, reason="era completo").json()["data"]
    assert (d["status"], d["amount_due"]) == ("Paid", 0.0)


@needs_db
def test_reason_is_required_and_nothing_changes_on_failure(db):
    a = _pay(db, 100)
    assert _correct(db, a, 90, reason="").status_code == 400
    assert _correct(db, a, 90, reason="ab").json()["code"] == "PAYMENT_CORRECTION_REASON_REQUIRED"
    assert len(_rows(db, "SELECT id FROM invoice_payments")) == 1
    assert _rows(db, "SELECT voided_at FROM invoice_payments")[0]["voided_at"] is None


@needs_db
def test_cannot_exceed_due_after_the_old_payment_is_out(db):
    a = _pay(db, 400)
    _pay(db, 500)
    r = _correct(db, a, 500.01)  # due once A is out = 1000 - 500 = 500
    assert r.status_code == 400 and r.json()["code"] == "PAYMENT_EXCEEDS_DUE"
    assert _rows(db, "SELECT voided_at FROM invoice_payments WHERE id = %s", (a,))[0]["voided_at"] is None  # rolled back
    assert _correct(db, a, 500).status_code == 200


@needs_db
def test_cannot_correct_a_voided_payment_twice_or_a_missing_one(db):
    a = _pay(db, 100)
    assert _correct(db, a, 90).status_code == 200
    assert _correct(db, a, 80).json()["code"] == "PAYMENT_ALREADY_VOIDED"
    assert _correct(db, 9999, 80).status_code == 404


@needs_db
def test_admin_only_and_toggle_off(db, monkeypatch):
    a = _pay(db, 100)
    assert _correct(db, a, 90, user="user").status_code == 403
    monkeypatch.setenv("PAYMENT_CORRECTION_ENABLED", "false")
    assert _correct(db, a, 90).status_code == 404
    assert _rows(db, "SELECT voided_at FROM invoice_payments")[0]["voided_at"] is None


@needs_db
def test_cancelled_invoice_is_refused(db):
    a = _pay(db, 100)
    conn = db["connect"]()
    conn.cursor().execute("UPDATE invoices SET status = 'Cancelled' WHERE id = %s", (db["iid"],))
    conn.commit()
    conn.close()
    r = _correct(db, a, 90)
    assert r.status_code == 400 and r.json()["code"] == "INVOICE_NOT_PAYABLE"


@needs_db
def test_revenue_report_counts_only_the_live_payment(db):
    a = _pay(db, 300)
    _correct(db, a, 250)
    rev = client.get("/reports/revenue", headers=_hdr()).json()["data"]["summary"]
    assert rev["total_revenue"] == 250.0


@needs_db
def test_payment_options_endpoint(db, monkeypatch):
    assert client.get("/invoices/payment-options", headers=_hdr()).json()["data"] == {
        "void_enabled": True, "correction_enabled": True}
    monkeypatch.setenv("PAYMENT_CORRECTION_ENABLED", "false")
    assert client.get("/invoices/payment-options", headers=_hdr()).json()["data"]["correction_enabled"] is False
    assert client.get("/invoices/payment-options").status_code in (401, 403)


@needs_db
def test_listing_names_who_and_marks_pre_existing_payments(db):
    pid = _pay(db, 100)
    conn = db["connect"]()
    cur = conn.cursor()
    # A payment as it exists in production today: no creator, no timestamp, backfilled.
    cur.execute("INSERT INTO invoice_payments (invoice_id, amount, payment_date, method, created_at, backfilled) "
                "VALUES (%s, 5, '2026-10-01', 'Cheque', NULL, true) RETURNING id", (db["iid"],))
    old = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    listed = {p["id"]: p for p in client.get(f"/invoices/{db['iid']}/payments", headers=_hdr()).json()["data"]}
    assert listed[pid]["created_by_name"] == "t_user" and listed[pid]["backfilled"] is False
    assert listed[old]["created_by_name"] is None and listed[old]["created_at"] is None and listed[old]["backfilled"] is True


# ---------------- optional immutability trigger ----------------

@pytest.fixture
def guarded(db):
    conn = db["connect"]()
    conn.cursor().execute(open(os.path.join(ROOT, "migrations", "2026-10-22_payment_immutability.sql"), encoding="utf-8").read())
    conn.commit()
    conn.close()
    yield db
    conn = db["connect"]()
    conn.cursor().execute(open(os.path.join(ROOT, "migrations", "2026-10-22_payment_immutability.rollback.sql"), encoding="utf-8").read())
    conn.commit()
    conn.close()


@needs_db
def test_trigger_blocks_edits_and_deletes_but_not_the_correction_flow(guarded):
    import psycopg2
    db = guarded
    a = _pay(db, 100)
    for sql in ("UPDATE invoice_payments SET amount = 1 WHERE id = %s",
                "UPDATE invoice_payments SET notes = 'x' WHERE id = %s",
                "DELETE FROM invoice_payments WHERE id = %s"):
        conn = db["connect"]()
        try:
            with pytest.raises(psycopg2.errors.IntegrityConstraintViolation):
                conn.cursor().execute(sql, (a,))
        finally:
            conn.rollback()
            conn.close()
    d = _correct(db, a, 80)
    assert d.status_code == 200, d.text  # void + insert are allowed
    conn = db["connect"]()
    try:
        with pytest.raises(psycopg2.errors.IntegrityConstraintViolation):
            conn.cursor().execute("UPDATE invoice_payments SET voided_at = NULL WHERE id = %s", (a,))  # cannot un-void
    finally:
        conn.rollback()
        conn.close()
    assert client.post(f"/invoices/{db['iid']}/payments/{d.json()['data']['payment_id']}/void",
                       json={"reason": "anular"}, headers=_hdr("admin")).status_code == 200  # the plain void still works


@needs_db
def test_trigger_allows_no_update_except_a_complete_void(guarded):
    import psycopg2
    db = guarded
    a = _pay(db, 100)
    blocked = [
        "UPDATE invoice_payments SET created_by_user_id = NULL WHERE id = %s",
        "UPDATE invoice_payments SET backfilled = true WHERE id = %s",
        "UPDATE invoice_payments SET created_at = now() WHERE id = %s",
        "UPDATE invoice_payments SET correction_chain_id = id WHERE id = %s",
        "UPDATE invoice_payments SET voided_at = now() WHERE id = %s",  # void without reason and user
        "UPDATE invoice_payments SET voided_at = now(), void_reason = '  ', voided_by_user_id = '%s' WHERE id = %%s" % ADMIN_ID,
    ]
    for sql in blocked:
        conn = db["connect"]()
        try:
            with pytest.raises(psycopg2.errors.IntegrityConstraintViolation):
                conn.cursor().execute(sql, (a,))
        finally:
            conn.rollback()
            conn.close()
    conn = db["connect"]()
    conn.cursor().execute("UPDATE invoice_payments SET voided_at = now(), void_reason = 'error', voided_by_user_id = %s WHERE id = %s", (ADMIN_ID, a))
    conn.commit()
    conn.close()


@needs_db
def test_a_user_with_payments_cannot_be_deleted(db, monkeypatch):
    import users.service as users_service
    from users.service import delete_user
    monkeypatch.setattr(users_service, "get_db_connection", db["connect"])
    from fastapi import HTTPException
    _pay(db, 50)
    with pytest.raises(HTTPException) as exc:
        delete_user(USER_ID, "superadmin")
    assert exc.value.code == "USER_HAS_PAYMENTS"
