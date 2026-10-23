"""Suplidores switch (P2). Default off; read at request time from the environment."""
import os


def suppliers_enabled() -> bool:
    return os.environ.get("SUPPLIERS_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")
