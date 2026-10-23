"""Status history (S1, 2026-10-23, switch STATUS_HISTORY_ENABLED, default OFF).

record() writes one append-only row inside the caller's transaction, so the history and the
status change commit or roll back together. Switch off = no SQL at all (works before the migration).
After the switch is on, a failed write is isolated by a savepoint: it never blocks a status change.
"""
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

QUOTE = "quote"
INVOICE = "invoice"


def enabled() -> bool:
    return os.environ.get("STATUS_HISTORY_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def record(cursor, entity_type: str, entity_key, from_status: Optional[str], to_status: str,
           actor_user_id=None, note: Optional[str] = None) -> bool:
    """Append one row. Returns True when written. No-op when off or when nothing changed."""
    if not enabled() or from_status == to_status:
        return False
    cursor.execute("SAVEPOINT status_history_write")
    try:
        cursor.execute(
            """
            INSERT INTO status_history
                (entity_type, entity_key, from_status, to_status, actor_user_id, actor_name, note)
            VALUES (%s, %s, %s, %s, %s::uuid,
                    (SELECT COALESCE(NULLIF(full_name, ''), username) FROM users WHERE id = %s::uuid), %s)
            """,
            (entity_type, str(entity_key), from_status, to_status,
             str(actor_user_id) if actor_user_id else None,
             str(actor_user_id) if actor_user_id else None, note),
        )
        cursor.execute("RELEASE SAVEPOINT status_history_write")
        return True
    except Exception:
        cursor.execute("ROLLBACK TO SAVEPOINT status_history_write")
        logger.exception("status_history write failed for %s %s", entity_type, entity_key)
        return False


def fetch(cursor, entity_type: str, entity_key) -> list:
    """Newest first. Empty when the switch is off."""
    if not enabled():
        return []
    cursor.execute(
        """
        SELECT from_status, to_status, actor_user_id, actor_name, changed_at, note
        FROM status_history
        WHERE entity_type = %s AND entity_key = %s
        ORDER BY changed_at DESC, id DESC
        """,
        (entity_type, str(entity_key)),
    )
    return [dict(r) for r in cursor.fetchall()]


def attach_last(cursor, entity_type: str, rows: list, key: str) -> list:
    """Add last_status_by / last_status_at to list rows with ONE query. Switch off = columns are None, no SQL."""
    for row in rows:
        row["last_status_by"] = None
        row["last_status_at"] = None
    if not enabled() or not rows:
        return rows
    keys = [str(r[key]) for r in rows]
    cursor.execute(
        """
        SELECT DISTINCT ON (entity_key) entity_key, actor_name, changed_at
        FROM status_history
        WHERE entity_type = %s AND entity_key = ANY(%s)
        ORDER BY entity_key, changed_at DESC, id DESC
        """,
        (entity_type, keys),
    )
    latest = {r["entity_key"]: r for r in cursor.fetchall()}
    for row in rows:
        hit = latest.get(str(row[key]))
        if hit:
            row["last_status_by"] = hit["actor_name"]
            row["last_status_at"] = hit["changed_at"]
    return rows
