"""Turn unhandled exceptions into the unified 500 body INSIDE the CORS middleware (debug B-08).

Starlette runs the Exception handler in ServerErrorMiddleware, the outermost layer,
so its 500 responses carried no Access-Control-Allow-Origin header. The browser then
reported "Failed to fetch" instead of the Spanish message. This middleware is added
before CORSMiddleware, so it sits inside it and CORS headers are applied to the 500.

The full traceback is logged. The client gets {"detail", "code"} only, never internals.
"""
import logging

from fastapi.responses import JSONResponse

from core.errors import error_body

logger = logging.getLogger("metpro.errors")


class UnhandledErrorMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False

        async def send_wrapper(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:  # noqa: BLE001 - last line of defence
            logger.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if started:
                raise  # headers already sent; nothing safe to add
            response = JSONResponse(status_code=500, content=error_body("Error interno del servidor", "INTERNAL_ERROR"))
            await response(scope, receive, send)
