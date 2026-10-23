"""Purchase order switch (P3b). Default off; read at request time from the environment."""
import os


def po_enabled() -> bool:
    return os.environ.get("PO_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
