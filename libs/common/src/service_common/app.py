from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI

from service_common.health import router as health_router
from service_common.security_headers import add_security_headers

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_service_app(
    *, title: str, production: bool, lifespan: Lifespan | None = None
) -> FastAPI:
    """App base de cada servicio: /health, cabeceras de seguridad y Swagger solo en desarrollo."""
    app = FastAPI(
        lifespan=lifespan,
        title=title,
        version="0.1.0",
        docs_url=None if production else "/docs",
        redoc_url=None,
        openapi_url=None if production else "/openapi.json",
    )
    add_security_headers(app, production=production)
    app.include_router(health_router)
    return app
