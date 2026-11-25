"""Bloqueos de fila (FOR UPDATE), con PostgreSQL real y sin depender de la suerte en los tiempos.

Las pruebas de test_concurrency.py lanzan peticiones a la vez y miran el resultado, pero si falta un
bloqueo pueden pasar igual: depende de quién llegue primero. Aquí el orden lo fija la prueba:

- El repositorio: con for_update=True, otra conexión no puede tomar la fila (NOWAIT falla al
  instante); sin for_update, sí puede.
- Los casos de uso: otra transacción cambia la fila y todavía no confirma. Con FOR UPDATE, el caso
  de uso espera y trabaja con la fila ya cambiada; sin el bloqueo, leería la versión vieja y
  perdería el cambio (o lo pisaría). Cada prueba mira ese resultado, no los tiempos.
"""

import threading
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from auth_service.application.use_cases import (
    ChangePassword,
    LogIn,
    LogOut,
    RefreshSession,
    RegisterUser,
    RevokeSession,
    UpdateProfile,
)
from auth_service.domain.errors import InvalidToken
from auth_service.infrastructure.db import SystemClock, build_session_factory
from auth_service.infrastructure.repositories import SqlUnitOfWork
from auth_service.infrastructure.security import Argon2PasswordHasher, JwtTokenService

from ..conftest import JWT_SECRET

PASSWORD = "una contraseña larga"
# Cuánto se deja corriendo el caso de uso antes de confirmar el cambio concurrente: tiempo de sobra
# para que, sin bloqueo, ya haya leído la versión vieja de la fila.
HEAD_START = 1.0
EARLIER = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def uow_factory(settings) -> Iterator[Callable[[], SqlUnitOfWork]]:
    session_factory = build_session_factory(settings.database_url)
    yield partial(SqlUnitOfWork, session_factory)
    session_factory.kw["bind"].dispose()


@pytest.fixture
def account(uow_factory):
    """Una cuenta con una sesión en un dispositivo."""
    hasher, tokens, clock = Argon2PasswordHasher(), JwtTokenService(JWT_SECRET, 15), SystemClock()
    user = RegisterUser(uow_factory, hasher, clock).execute(
        "luis@example.com", PASSWORD, "Luis", "Aguilar"
    )
    log_in = LogIn(uow_factory, hasher, tokens, clock, 90, max_attempts=5, window_minutes=15)
    login = log_in.execute("luis@example.com", PASSWORD, "telefono", "Teléfono")
    return {"user_id": user.id, "session_id": login.session_id, "login": login}


def is_locked(engine, table: str, row_id: UUID) -> bool:
    """¿Otra conexión tiene bloqueada la fila? NOWAIT responde al instante en lugar de esperar."""
    with engine.connect() as connection, connection.begin():
        try:
            connection.execute(
                text(f"SELECT 1 FROM auth.{table} WHERE id = :id FOR UPDATE NOWAIT"),
                {"id": row_id},
            )
        except OperationalError as error:
            assert "could not obtain lock" in str(error)
            return True
    return False


def run_during_concurrent_change(engine, change: str, params: dict, action: Callable[[], object]):
    """Otra transacción ejecuta `change` (y con eso bloquea la fila); mientras sigue abierta, corre
    `action` en un hilo; después confirma el cambio. Devuelve lo que devolvió o lanzó `action`."""
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["result"] = action()
        except Exception as error:  # noqa: BLE001 - se devuelve para revisarla
            outcome["error"] = error

    worker = threading.Thread(target=run)
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(text(change), params)
        worker.start()
        worker.join(HEAD_START)
        transaction.commit()
    worker.join(10)
    assert not worker.is_alive()
    return outcome


def column(engine, table: str, name: str, row_id: UUID):
    with engine.connect() as connection:
        return connection.execute(
            text(f"SELECT {name} FROM auth.{table} WHERE id = :id"), {"id": row_id}
        ).scalar_one()


# --- Repositorio --------------------------------------------------------------------------------


def test_user_lookups_with_for_update_lock_the_row(uow_factory, engine, account) -> None:
    with uow_factory() as uow:
        assert uow.users.get(account["user_id"], for_update=True) is not None
        assert is_locked(engine, "users", account["user_id"])
    assert not is_locked(engine, "users", account["user_id"])
    with uow_factory() as uow:
        assert uow.users.get_by_email("luis@example.com", for_update=True) is not None
        assert is_locked(engine, "users", account["user_id"])


def test_user_lookups_without_for_update_do_not_lock(uow_factory, engine, account) -> None:
    with uow_factory() as uow:
        uow.users.get(account["user_id"])
        uow.users.get_by_email("luis@example.com")
        assert not is_locked(engine, "users", account["user_id"])


def test_session_lookups_with_for_update_lock_the_row(uow_factory, engine, account) -> None:
    token_hash = JwtTokenService(JWT_SECRET, 15).hash_refresh_token(account["login"].refresh_token)
    with uow_factory() as uow:
        assert uow.sessions.get(account["session_id"], for_update=True) is not None
        assert is_locked(engine, "sessions", account["session_id"])
    with uow_factory() as uow:
        assert uow.sessions.get_by_refresh_hash(token_hash, for_update=True) is not None
        assert is_locked(engine, "sessions", account["session_id"])


def test_session_lookups_without_for_update_do_not_lock(uow_factory, engine, account) -> None:
    token_hash = JwtTokenService(JWT_SECRET, 15).hash_refresh_token(account["login"].refresh_token)
    # Que la búsqueda por el hash anterior también encuentre la fila.
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE auth.sessions SET previous_refresh_token_hash = :hash WHERE id = :id"),
            {"hash": token_hash, "id": account["session_id"]},
        )
    with uow_factory() as uow:
        uow.sessions.get(account["session_id"])
        uow.sessions.get_by_refresh_hash(token_hash)
        assert uow.sessions.get_by_previous_refresh_hash(token_hash) is not None
        uow.sessions.list_unrevoked_for_user(account["user_id"])
        assert not is_locked(engine, "sessions", account["session_id"])


# --- Casos de uso -------------------------------------------------------------------------------


def test_change_password_sees_a_password_changed_at_the_same_time(
    uow_factory, engine, account
) -> None:
    # Otro dispositivo acaba de cambiar la contraseña. Con el bloqueo, este cambio espera y verifica
    # contra la contraseña nueva; sin él, verificaría contra la vieja.
    hasher = Argon2PasswordHasher()
    change = ChangePassword(uow_factory, hasher, SystemClock())

    outcome = run_during_concurrent_change(
        engine,
        "UPDATE auth.users SET password_hash = :hash WHERE id = :id",
        {"hash": hasher.hash("contraseña puesta por otro"), "id": account["user_id"]},
        lambda: change.execute(
            account["user_id"],
            account["session_id"],
            "contraseña puesta por otro",
            "contraseña final larga",
        ),
    )

    assert "error" not in outcome
    stored = column(engine, "users", "password_hash", account["user_id"])
    assert hasher.verify(stored, "contraseña final larga")


def test_update_profile_keeps_a_surname_changed_at_the_same_time(
    uow_factory, engine, account
) -> None:
    update = UpdateProfile(uow_factory)

    outcome = run_during_concurrent_change(
        engine,
        "UPDATE auth.users SET last_name = 'Otro Apellido' WHERE id = :id",
        {"id": account["user_id"]},
        lambda: update.execute(account["user_id"], first_name="Ana"),
    )

    user = outcome["result"]
    assert (user.first_name, user.last_name) == ("Ana", "Otro Apellido")


@pytest.mark.parametrize("use_case", ["log_out", "revoke_session"])
def test_closing_a_session_closed_at_the_same_time_keeps_the_first_close_time(
    uow_factory, engine, account, use_case
) -> None:
    clock = SystemClock()
    actions = {
        "log_out": lambda: LogOut(uow_factory, clock).execute(account["session_id"]),
        "revoke_session": lambda: RevokeSession(uow_factory, clock).execute(
            account["user_id"], account["session_id"]
        ),
    }

    outcome = run_during_concurrent_change(
        engine,
        "UPDATE auth.sessions SET revoked_at = :earlier WHERE id = :id",
        {"earlier": EARLIER, "id": account["session_id"]},
        actions[use_case],
    )

    assert "error" not in outcome
    assert column(engine, "sessions", "revoked_at", account["session_id"]) == EARLIER


def test_refresh_does_not_reuse_a_token_rotated_at_the_same_time(
    uow_factory, engine, account
) -> None:
    # Otro dispositivo (o un ladrón) acaba de renovar con el mismo refresh token. Con el bloqueo,
    # este intento espera, ya no encuentra el token y lo rechaza; sin él, renovaría otra vez.
    tokens = JwtTokenService(JWT_SECRET, 15)
    refresh = RefreshSession(uow_factory, tokens, SystemClock(), 90)
    old_hash = tokens.hash_refresh_token(account["login"].refresh_token)
    other_hash = tokens.hash_refresh_token("token de la otra renovación")

    outcome = run_during_concurrent_change(
        engine,
        "UPDATE auth.sessions SET refresh_token_hash = :new, previous_refresh_token_hash = :old "
        "WHERE id = :id",
        {"new": other_hash, "old": old_hash, "id": account["session_id"]},
        lambda: refresh.execute(account["login"].refresh_token),
    )

    assert isinstance(outcome.get("error"), InvalidToken)
    assert column(engine, "sessions", "refresh_token_hash", account["session_id"]) == other_hash
