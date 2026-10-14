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
from typing import Optional

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


# ============================================================
# UNIFIED ERROR MODEL
# ============================================================
# Every error response has the same JSON shape:
#   {"detail": "<message>", "code": "<ERROR_CODE>"}
#
# "detail" keeps the existing message contract (clients read it today).
# "code" is stable and machine-readable. A route may set a specific code
# by raising an exception with a ``code`` attribute. Otherwise the code
# is derived from the HTTP status.

from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402
from fastapi import Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "BAD_GATEWAY",
    503: "SERVICE_UNAVAILABLE",
}


def error_code_for(status_code: int, explicit: Optional[str] = None) -> str:
    if explicit:
        return explicit
    return STATUS_CODES.get(status_code, "HTTP_ERROR")


def error_body(message: str, code: str) -> dict:
    return {"detail": message, "code": code}


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Invalid request"
    first = errors[0]
    loc = [str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path", "header")]
    field = ".".join(loc)
    msg = first.get("msg", "invalid value")
    return f"Invalid request: {field}: {msg}" if field else f"Invalid request: {msg}"


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = error_code_for(exc.status_code, getattr(exc, "code", None))
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(str(exc.detail), code),
        headers=getattr(exc, "headers", None),
    )


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(_validation_message(exc), "VALIDATION_ERROR"),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error("Unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content=error_body("Internal server error", "INTERNAL_ERROR"),
    )


def register_error_handlers(app) -> None:
    """Install the unified error model on a FastAPI app."""
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)
    app.add_exception_handler(Exception, _unhandled_exception_handler)


def api_error(status_code: int, message: str, code: str) -> HTTPException:
    """Return an HTTPException whose error code is set explicitly.

    The message is the client-facing text and is passed through unchanged.
    """
    exc = HTTPException(status_code=status_code, detail=message)
    exc.code = code  # type: ignore[attr-defined]
    return exc
