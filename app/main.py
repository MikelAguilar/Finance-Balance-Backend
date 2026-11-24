from fastapi import FastAPI

from app.config import Settings
from app.interfaces.http.health import router as health_router
from app.interfaces.http.seguridad import agregar_cabeceras_de_seguridad


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    is_development = settings.app_env == "development"

    app = FastAPI(
        title="Finance Balance API",
        version="0.1.0",
        docs_url="/docs" if is_development else None,
        redoc_url=None,
        openapi_url="/openapi.json" if is_development else None,
    )
    agregar_cabeceras_de_seguridad(app, produccion=not is_development)
    app.include_router(health_router)
    return app
