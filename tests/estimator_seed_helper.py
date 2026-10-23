"""Test helper: make sure the estimator seed (version 1.0 of 'Nave Industrial') is complete.

Other tests TRUNCATE quotes, products ... CASCADE, which also empties estimator tables that reference them
(materials via products, runs and audit via quotes). Estimator database tests call ensure_seed() first, so they do not
depend on test order. Test databases only: this deletes and reloads the seed rows."""
import os

import psycopg2

ROOT = os.path.join(os.path.dirname(__file__), "..")
SEED_SQL = os.path.join(ROOT, "migrations", "2026-10-22_estimator_seed_v1.sql")


def ensure_seed(url: str) -> None:
    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT v.id, m.id, (SELECT count(*) FROM estimator_materials WHERE version_id = v.id), "
            "(SELECT count(*) FROM estimator_profiles WHERE version_id = v.id), "
            "(SELECT count(*) FROM estimator_constants WHERE version_id = v.id) "
            "FROM estimator_versions v JOIN estimator_models m ON m.id = v.model_id "
            "WHERE m.name = 'Nave Industrial' AND v.version = '1.0'"
        )
        row = cur.fetchone()
        if row and (row[2], row[3], row[4]) == (30, 132, 11):
            return
        if row:
            vid, mid = row[0], row[1]
            cur.execute("UPDATE estimator_versions SET status = 'draft' WHERE id = %s", (vid,))
            for table in ("estimator_materials", "estimator_profiles", "estimator_constants"):
                cur.execute(f"DELETE FROM {table} WHERE version_id = %s", (vid,))
            cur.execute("DELETE FROM estimator_versions WHERE id = %s", (vid,))
            cur.execute("DELETE FROM estimator_models WHERE id = %s", (mid,))
        with open(SEED_SQL, encoding="utf-8") as fh:
            cur.execute(fh.read())
    finally:
        conn.close()
