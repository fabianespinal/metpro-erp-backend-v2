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


_VALIDATION_ES = {
    "missing": "campo obligatorio",
    "string_type": "debe ser texto",
    "int_type": "debe ser un número entero",
    "int_parsing": "debe ser un número entero",
    "float_type": "debe ser un número",
    "float_parsing": "debe ser un número",
    "bool_type": "debe ser verdadero o falso",
    "bool_parsing": "debe ser verdadero o falso",
    "string_too_short": "el texto es demasiado corto",
    "string_too_long": "el texto es demasiado largo",
    "greater_than": "el valor es demasiado bajo",
    "greater_than_equal": "el valor es demasiado bajo",
    "less_than": "el valor es demasiado alto",
    "less_than_equal": "el valor es demasiado alto",
    "too_short": "la lista tiene muy pocos elementos",
    "too_long": "la lista tiene demasiados elementos",
    "list_type": "debe ser una lista",
    "dict_type": "debe ser un objeto",
    "json_invalid": "JSON no válido",
    "literal_error": "valor no permitido",
    "enum": "valor no permitido",
    "string_pattern_mismatch": "formato no válido",
    "date_from_datetime_parsing": "fecha no válida",
    "date_parsing": "fecha no válida",
    "date_type": "fecha no válida",
}


def _validation_message(exc: RequestValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "Solicitud no válida"
    first = errors[0]
    loc = [str(p) for p in first.get("loc", ()) if p not in ("body", "query", "path", "header")]
    field = ".".join(loc)
    etype = first.get("type", "")
    raw = str(first.get("msg", ""))
    if etype == "value_error" or raw.startswith("Value error, "):
        # Custom validators already raise Spanish messages.
        msg = raw[len("Value error, "):] if raw.startswith("Value error, ") else raw
    else:
        msg = _VALIDATION_ES.get(etype, "valor no válido")
    return f"Solicitud no válida: {field}: {msg}" if field else f"Solicitud no válida: {msg}"


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
        content=error_body("Error interno del servidor", "INTERNAL_ERROR"),
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
