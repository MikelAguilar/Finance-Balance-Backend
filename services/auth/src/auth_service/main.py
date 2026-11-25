from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

from auth_service.application.use_cases import (
    Authenticate,
    ChangePassword,
    DeleteAccount,
    GetProfile,
    ListSessions,
    LogIn,
    LogOut,
    RefreshSession,
    RegisterUser,
    RevokeSession,
    UpdateProfile,
)
from auth_service.config import Settings
from auth_service.infrastructure.db import SystemClock, build_session_factory
from auth_service.infrastructure.repositories import SqlUnitOfWork
from auth_service.infrastructure.security import Argon2PasswordHasher, JwtTokenService
from auth_service.interfaces.http.auth import router as auth_router
from auth_service.interfaces.http.health import router as health_router
from auth_service.interfaces.http.security_headers import add_security_headers


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    is_development = settings.app_env == "development"
    session_factory = build_session_factory(settings.database_url)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # Al apagar la app se cierran las conexiones abiertas con PostgreSQL.
        session_factory.kw["bind"].dispose()

    app = FastAPI(
        lifespan=lifespan,
        title="Finance Balance API",
        version="0.1.0",
        docs_url="/docs" if is_development else None,
        redoc_url=None,
        openapi_url="/openapi.json" if is_development else None,
    )
    add_security_headers(app, production=not is_development)

    # Composición: aquí se eligen las implementaciones concretas de cada puerto. El motor de
    # base de datos no se conecta hasta la primera consulta.
    uow_factory = partial(SqlUnitOfWork, session_factory)
    hasher = Argon2PasswordHasher()
    tokens = JwtTokenService(settings.jwt_secret.get_secret_value(), settings.access_token_minutes)
    clock = SystemClock()
    app.state.register_user = RegisterUser(uow_factory, hasher, clock)
    app.state.log_in = LogIn(
        uow_factory,
        hasher,
        tokens,
        clock,
        settings.refresh_token_days,
        settings.login_max_attempts,
        settings.login_window_minutes,
    )
    app.state.refresh_session = RefreshSession(
        uow_factory, tokens, clock, settings.refresh_token_days
    )
    app.state.authenticate = Authenticate(uow_factory, tokens, clock)
    app.state.change_password = ChangePassword(uow_factory, hasher, clock)
    app.state.log_out = LogOut(uow_factory, clock)
    app.state.get_profile = GetProfile(uow_factory)
    app.state.update_profile = UpdateProfile(uow_factory)
    app.state.list_sessions = ListSessions(uow_factory, clock)
    app.state.revoke_session = RevokeSession(uow_factory, clock)
    app.state.delete_account = DeleteAccount(uow_factory, hasher, clock)

    app.include_router(health_router)
    app.include_router(auth_router)
    return app
