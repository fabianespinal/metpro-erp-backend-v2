"""ENGINEERING_ESTIMATE_ENABLED. Default off. Off = every estimator endpoint answers 404 and touches nothing."""
import os

from core.errors import api_error


def estimator_enabled() -> bool:
    return os.environ.get("ENGINEERING_ESTIMATE_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def require_enabled() -> None:
    if not estimator_enabled():
        raise api_error(404, "No encontrado", "ESTIMATOR_DISABLED")
