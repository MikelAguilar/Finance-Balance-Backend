from functools import partial

from fastapi import FastAPI

from auth_service.application.use_cases import LogIn, RegisterUser
from auth_service.config import Settings
from auth_service.infrastructure.db import SystemClock, build_session_factory
from auth_service.infrastructure.repositories import SqlUnitOfWork
from auth_service.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from auth_service.interfaces.http.auth import router as auth_router
from auth_service.interfaces.http.health import router as health_router
from auth_service.interfaces.http.seguridad import agregar_cabeceras_de_seguridad


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

    # Composición: aquí se eligen las implementaciones concretas de cada puerto. El motor de
    # base de datos no se conecta hasta la primera consulta.
    uow_factory = partial(SqlUnitOfWork, build_session_factory(settings.database_url))
    hasher = Argon2PasswordHasher()
    tokens = JwtTokenService(settings.jwt_secret.get_secret_value(), settings.access_token_minutes)
    clock = SystemClock()
    app.state.register_user = RegisterUser(uow_factory, hasher, clock)
    app.state.log_in = LogIn(uow_factory, hasher, tokens, clock, settings.refresh_token_days)

    app.include_router(health_router)
    app.include_router(auth_router)
    return app
