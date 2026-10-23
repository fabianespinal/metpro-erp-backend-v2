"""RFQ switch (P3a). Default off; read at request time from the environment."""
import os


def rfq_enabled() -> bool:
    return os.environ.get("RFQ_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
