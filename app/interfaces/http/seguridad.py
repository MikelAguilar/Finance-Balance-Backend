from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response

CABECERAS_SIEMPRE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

# HSTS y CSP solo en producción: en desarrollo no hay HTTPS y Swagger necesita cargar scripts.
CABECERAS_PRODUCCION = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def agregar_cabeceras_de_seguridad(app: FastAPI, *, produccion: bool) -> None:
    cabeceras = CABECERAS_SIEMPRE | (CABECERAS_PRODUCCION if produccion else {})

    @app.middleware("http")
    async def _cabeceras(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers.update(cabeceras)
        return response
