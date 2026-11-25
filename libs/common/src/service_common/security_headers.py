from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

ALWAYS_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# HSTS y CSP solo en producción: en desarrollo no hay HTTPS y Swagger necesita cargar scripts.
PRODUCTION_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def add_security_headers(app: FastAPI, *, production: bool) -> None:
    headers = ALWAYS_HEADERS | (PRODUCTION_HEADERS if production else {})

    @app.middleware("http")
    async def _add_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(headers)
        return response
