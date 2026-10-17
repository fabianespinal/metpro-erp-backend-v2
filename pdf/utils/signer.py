"""Name printed above the Metpro signature line on every PDF."""
import logging
from typing import Optional

from database import get_db_connection

logger = logging.getLogger(__name__)


def resolve_signer_name(current_user: Optional[dict] = None,
                        fallback_name: Optional[str] = None) -> Optional[str]:
    """
    Full name of the person generating the document.

    Logged-in user: users.full_name (looked up by the JWT "sub"), then the JWT
    "name" claim, then the username. No logged-in user (public links): the
    document creator's name passed as fallback_name. Returns None when nothing
    is known, so the signature line stays blank. Never raises.
    """
    try:
        if current_user:
            username = current_user.get("sub")
            conn = get_db_connection()
            try:
                cur = conn.cursor()
                cur.execute("SELECT full_name FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
            finally:
                conn.close()
            if row:
                val = row["full_name"] if isinstance(row, dict) else row[0]
                if val and str(val).strip():
                    return str(val).strip()
            claim = (current_user.get("name") or "").strip()
            return claim or username or (fallback_name or None)
    except Exception:
        logger.exception("Signer name lookup failed")
        claim = ((current_user or {}).get("name") or "").strip()
        if claim:
            return claim
    return (fallback_name or "").strip() or None
