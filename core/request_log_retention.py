"""90-day retention for public.request_logs (item 12, module 4).

Manual trigger only. No scheduler.

  python -m core.request_log_retention              # dry run: counts only
  python -m core.request_log_retention --apply     # deletes rows older than cutoff

Rules:
  - Default is dry run. Deletion requires --apply.
  - Cutoff = now (UTC) minus retention days. Rows with timestamp < cutoff are expired.
  - Count and delete run in one transaction. Any error rolls back and propagates.
    Unlike logging, a failed purge must be visible to the operator.
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

RETENTION_DAYS = 90

_COUNT_SQL = 'SELECT COUNT(*) AS n FROM public.request_logs WHERE "timestamp" < %s'
_DELETE_SQL = 'DELETE FROM public.request_logs WHERE "timestamp" < %s'


def cutoff_for(days: int, now: Optional[datetime] = None) -> datetime:
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError("Los días deben ser un entero mayor o igual a 1")
    base = now or datetime.now(timezone.utc)
    return base - timedelta(days=days)


def purge_request_logs(*, days: int = RETENTION_DAYS, apply: bool = False,
                       now: Optional[datetime] = None) -> dict:
    """Count (and optionally delete) request_logs rows older than ``days``.

    Returns {"cutoff", "days", "matched", "deleted", "applied"}.
    """
    cutoff = cutoff_for(days, now)

    # Resolved at call time so tests can patch database.get_db_connection.
    import database

    conn = database.get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(_COUNT_SQL, (cutoff,))
            matched = int(cur.fetchone()["n"])
            deleted = 0
            if apply:
                cur.execute(_DELETE_SQL, (cutoff,))
                deleted = int(cur.rowcount)
        if apply:
            conn.commit()
        else:
            conn.rollback()
        return {
            "cutoff": cutoff.isoformat(),
            "days": days,
            "matched": matched,
            "deleted": deleted,
            "applied": bool(apply),
        }
    except Exception:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        raise
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Purge request_logs older than N days.")
    parser.add_argument("--days", type=int, default=RETENTION_DAYS,
                        help=f"retention in days (default {RETENTION_DAYS})")
    parser.add_argument("--apply", action="store_true",
                        help="delete rows. Without this flag the run is a dry run.")
    args = parser.parse_args(argv)
    try:
        result = purge_request_logs(days=args.days, apply=args.apply)
    except Exception as exc:  # noqa: BLE001
        print(f"request_log_retention: failed: {type(exc).__name__}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
