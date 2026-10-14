"""Shared helper for returning client-safe errors from route handlers.

Usage, inside an ``except`` block:

    except Exception as e:
        raise internal_error("Quote create failed", e)

Behavior:
- The full exception and traceback are always written to the server log.
- By default the client receives only the context string. No driver text,
  SQL, DSN, or ``str(e)`` is returned.
- Internal detail is returned only when BOTH hold:
    EXPOSE_ERROR_DETAIL is truthy AND APP_ENV is not "production".
  APP_ENV defaults to "production" when unset, so the default is fail-safe.
"""
import logging
import os

from fastapi import HTTPException

logger = logging.getLogger("metpro.errors")

_TRUTHY = {"1", "true", "yes", "on"}


def expose_error_detail() -> bool:
    """Return True only when detail may reach the client (never in production)."""
    toggle = os.environ.get("EXPOSE_ERROR_DETAIL", "false").strip().lower()
    if toggle not in _TRUTHY:
        return False
    app_env = os.environ.get("APP_ENV", "production").strip().lower()
    return app_env != "production"


def internal_error(context: str, exc: BaseException, status_code: int = 500) -> HTTPException:
    """Log ``exc`` with ``context`` and return an HTTPException safe for clients.

    Call inside an ``except`` block so ``logger.exception`` captures the traceback.
    """
    logger.exception("%s", context)

    if expose_error_detail():
        detail = f"{context}: {type(exc).__name__}: {exc}"
    else:
        detail = context

    return HTTPException(status_code=status_code, detail=detail)
