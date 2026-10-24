"""Role policy switch. Default off; read at request time from the environment.

On: approving or rejecting a quote, converting a quote to an invoice, creating an invoice directly and
editing an expense need role admin or superadmin. Off: behavior is unchanged (any signed in user).
"""
import os

from core.errors import api_error


def role_policy_enabled() -> bool:
    return os.environ.get("ROLE_POLICY_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def enforce_admin(current_user: dict) -> None:
    """Raise 403 INSUFFICIENT_PERMISSIONS when the policy is on and the user is not admin or superadmin."""
    if role_policy_enabled() and current_user.get("role") not in ("admin", "superadmin"):
        raise api_error(403, "Permisos insuficientes", "INSUFFICIENT_PERMISSIONS")
