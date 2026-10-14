"""ASGI middleware that writes request_logs rows (item 12, module 3).

Logs a request when either:
  - auth succeeded (require_auth marked the holder), or
  - the matched route is a public invoice/quote view.

Never logged: /health, /auth/login, unmatched paths, and requests that
never passed auth (401 at the auth layer stays out of this table).

Path is the route template (e.g. /quotes/public/{token}), never the raw URL.
No request or response body is read or stored.

The DB write runs in a worker thread after the response has been sent,
so it does not block the event loop or add to time-to-first-byte.
"""
import time
from typing import Optional

import anyio
from starlette.requests import Request
from starlette.routing import Match

from core import request_log as rl
from core.rate_limit import client_ip

EXCLUDED_PATHS = frozenset({"/health", "/auth/login"})

PUBLIC_TEMPLATES = frozenset({
    "/quotes/public/{token}",
    "/quotes/public/{token}/pdf",
    "/invoices/public/{token}",
    "/invoices/public/{token}/pdf",
})


def _route_template(app, scope) -> Optional[str]:
    """Return the matched route's template, or None when nothing matches fully."""
    for route in app.routes:
        try:
            match, _ = route.matches(scope)
        except Exception:  # noqa: BLE001
            continue
        if match == Match.FULL and hasattr(route, "path"):
            return route.path
    return None


class RequestLogMiddleware:
    def __init__(self, app, asgi_app):
        # `app` is the downstream ASGI app. `asgi_app` is the FastAPI instance
        # used to resolve route templates.
        self.app = app
        self._fastapi = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        holder = {}
        token = rl._holder.set(holder)
        status = {"code": 500}
        started = time.perf_counter()

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = int((time.perf_counter() - started) * 1000)
            rl._holder.reset(token)
            try:
                await self._record(scope, holder, status["code"], latency_ms)
            except Exception:  # noqa: BLE001 - audit must never fail a request
                pass

    async def _record(self, scope, holder, status_code, latency_ms):
        path = scope.get("path", "")
        if path in EXCLUDED_PATHS:
            return

        template = _route_template(self._fastapi, scope)
        if template is None:
            return

        is_authenticated = bool(holder.get("is_authenticated"))
        is_public = template in PUBLIC_TEMPLATES
        if not (is_authenticated or is_public):
            return

        request = Request(scope)
        await anyio.to_thread.run_sync(
            lambda: rl.log_request(
                method=scope.get("method", "GET"),
                path=template,
                status_code=status_code,
                latency_ms=latency_ms,
                client_ip=client_ip(request),
                user_sub=holder.get("user_sub") if is_authenticated else None,
                is_public=is_public,
                is_authenticated=is_authenticated,
            )
        )
