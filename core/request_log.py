"""Request audit log writer (item 12, module 2).

log_request() writes one metadata row to public.request_logs.

Rules:
  - Metadata only. The signature has no body or header parameters, so
    request and response bodies cannot reach the table.
  - Never raises. A failed write is reported to stderr and the request
    continues unchanged.
  - Runs on the request thread. The insert is one short statement. If the
    DB is slow, the request is slow by that amount. A background queue
    would remove that cost but adds loss on crash. Not chosen here.
  - path must be the route template (e.g. /quotes/public/{token}), not the
    raw URL. Raw public paths contain bearer-like tokens.
"""
import sys
from datetime import datetime, timezone
from typing import Optional

PATH_MAX = 512
USER_SUB_MAX = 255
CLIENT_IP_MAX = 64

_INSERT_SQL = """
    INSERT INTO public.request_logs
        ("timestamp", user_sub, method, path, status_code, latency_ms,
         client_ip, is_public, is_authenticated)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _clip(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    return str(value)[:limit]


def log_request(
    *,
    method: str,
    path: str,
    status_code: int,
    latency_ms: int,
    client_ip: Optional[str] = None,
    user_sub: Optional[str] = None,
    is_public: bool = False,
    is_authenticated: bool = False,
    timestamp: Optional[datetime] = None,
) -> bool:
    """Write one audit row. Return True on success, False otherwise. Never raises."""
    conn = None
    try:
        # Resolved at call time so tests can patch database.get_db_connection.
        import database

        row = (
            timestamp or datetime.now(timezone.utc),
            _clip(user_sub, USER_SUB_MAX),
            str(method)[:16],
            _clip(path, PATH_MAX),
            int(status_code),
            max(0, int(latency_ms)),
            _clip(client_ip, CLIENT_IP_MAX),
            bool(is_public),
            bool(is_authenticated),
        )
        conn = database.get_db_connection()
        with conn.cursor() as cur:
            cur.execute(_INSERT_SQL, row)
        conn.commit()
        return True
    except Exception as exc:  # noqa: BLE001 - audit must never fail a request
        try:
            if conn is not None:
                conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        print(f"request_log: write failed: {type(exc).__name__}", file=sys.stderr)
        return False
    finally:
        try:
            if conn is not None:
                conn.close()
        except Exception:  # noqa: BLE001
            pass
