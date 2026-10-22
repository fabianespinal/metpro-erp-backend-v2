"""Phase B quote feature switches. All default off; each is read at request time from the environment."""
import os


def _on(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() in ("1", "true", "yes", "on")


def blank_quotes_enabled() -> bool:
    """B2: start a quote without a template pack (screen option)."""
    return _on("BLANK_QUOTES_ENABLED")


def duplicate_change_client_enabled() -> bool:
    """B1: duplicate a quote for a different client or contact."""
    return _on("DUPLICATE_CHANGE_CLIENT_ENABLED")
