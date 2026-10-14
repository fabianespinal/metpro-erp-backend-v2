"""
Migration conventions. Runs in CI on every PR.

- Every forward migration has a rollback pair: <name>.rollback.sql
- Every forward migration states its status on a "-- Status:" line
  that begins with "APPLIED" or "NOT APPLIED"
- BEGIN; and COMMIT; counts match in each migration file (transactions are closed)
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"

FORWARD = sorted(p for p in MIGRATIONS.glob("*.sql") if not p.name.endswith(".rollback.sql"))
STATUS = re.compile(r"^-- Status:\s+(APPLIED|NOT APPLIED)\b", re.MULTILINE)


def test_migrations_exist():
    assert FORWARD, "expected forward migrations in migrations/"


def test_every_forward_migration_has_rollback_pair():
    missing = [
        p.name for p in FORWARD
        if not (MIGRATIONS / f"{p.stem}.rollback.sql").exists()
    ]
    assert not missing, f"missing rollback files for: {missing}"


def test_every_forward_migration_has_status_line():
    missing = [p.name for p in FORWARD if not STATUS.search(p.read_text(encoding="utf-8"))]
    assert not missing, f"missing or invalid '-- Status:' line in: {missing}"


def test_transactions_are_closed():
    bad = []
    for p in list(FORWARD) + sorted(MIGRATIONS.glob("*.rollback.sql")):
        text = p.read_text(encoding="utf-8")
        begins = len(re.findall(r"^BEGIN;", text, re.MULTILINE))
        commits = len(re.findall(r"^COMMIT;", text, re.MULTILINE))
        if begins != commits:
            bad.append(f"{p.name}: BEGIN={begins} COMMIT={commits}")
    assert not bad, "\n".join(bad)
