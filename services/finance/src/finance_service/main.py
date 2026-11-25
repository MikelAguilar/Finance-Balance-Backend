from fastapi import FastAPI

from finance_service.config import Settings
from service_common.app import create_service_app


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    return create_service_app(
        title="Finance Balance API: finanzas", production=settings.app_env == "production"
    )
