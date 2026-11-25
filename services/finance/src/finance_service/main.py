from fastapi import FastAPI

from finance_service.config import Settings
from service_common.health import router as health_router
from service_common.security_headers import add_security_headers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    is_development = settings.app_env == "development"
    app = FastAPI(
        title="Finance Balance API: finanzas",
        version="0.1.0",
        docs_url="/docs" if is_development else None,
        redoc_url=None,
        openapi_url="/openapi.json" if is_development else None,
    )
    add_security_headers(app, production=not is_development)
    app.include_router(health_router)
    return app
