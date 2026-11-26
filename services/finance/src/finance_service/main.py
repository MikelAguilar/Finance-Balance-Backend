from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from finance_service.application.download import Download
from finance_service.config import Settings
from finance_service.infrastructure.repositories import sql_store
from finance_service.interfaces.http.sync import router as sync_router
from service_common.app import create_service_app


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    # El motor no se conecta hasta la primera consulta.
    engine = create_engine(settings.database_url, pool_pre_ping=True)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Al apagar la app se cierran las conexiones abiertas con PostgreSQL.
        engine.dispose()

    app = create_service_app(
        title="Finance Balance API: finanzas",
        production=settings.app_env == "production",
        lifespan=lifespan,
    )
    app.state.download = Download(sql_store(sessionmaker(engine)))
    app.include_router(sync_router)
    return app
