"""Unified success response shape.

    {"data": <payload>, "success": true}

Applied to every JSON success response by apply_success_envelope(app).

Not wrapped:
- Error responses (non-2xx). They keep the error model: {"detail", "code"}.
- Non-JSON responses (PDF, streams, plain bytes, 204 with no body).
- Payloads are passed through unchanged inside "data".
"""
import json
from typing import Any

from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute, request_response


def success_body(payload: Any) -> dict:
    return {"data": payload, "success": True}


def _wrap_handler(original):
    async def handler(request):
        response = await original(request)
        if not isinstance(response, JSONResponse):
            return response
        if not (200 <= response.status_code < 300):
            return response
        if not response.body:
            return response
        try:
            payload = json.loads(response.body)
        except ValueError:
            return response
        headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in ("content-length", "content-type")
        }
        return JSONResponse(
            content=success_body(payload),
            status_code=response.status_code,
            headers=headers,
        )

    return handler


def apply_success_envelope(app) -> int:
    """Wrap every APIRoute on the app. Returns the number of routes wrapped."""
    count = 0
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if getattr(route, "_success_envelope", False):
            continue
        route.app = request_response(_wrap_handler(route.get_route_handler()))
        route._success_envelope = True
        count += 1
    return count
