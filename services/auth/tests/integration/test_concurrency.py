"""Peticiones simultáneas contra PostgreSQL real.

Simulan lo que pasa cuando la app reintenta por mala señal, cuando dos teléfonos actúan a la vez
o cuando alguien lanza muchas peticiones juntas. Cada prueba usa hilos que esperan en una
barrera para arrancar exactamente al mismo tiempo.
"""

import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest

from auth_service.application.use_cases import (
    DeleteAccount,
    ListSessions,
    LogIn,
    RefreshSession,
    RegisterUser,
    RevokeSession,
    UpdateProfile,
)
from auth_service.domain.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidToken,
    WrongCurrentPassword,
)
from auth_service.infrastructure.db import SystemClock, build_session_factory
from auth_service.infrastructure.repositories import SqlUnitOfWork
from auth_service.infrastructure.security import Argon2PasswordHasher, JwtTokenService

from ..conftest import JWT_SECRET

PASSWORD = "una contraseña larga"
THREADS = 8


@pytest.fixture
def services(settings):
    session_factory = build_session_factory(settings.database_url)
    uow = partial(SqlUnitOfWork, session_factory)
    hasher, tokens, clock = Argon2PasswordHasher(), JwtTokenService(JWT_SECRET, 15), SystemClock()
    yield {
        "register": RegisterUser(uow, hasher, clock),
        "log_in": LogIn(uow, hasher, tokens, clock, 90, max_attempts=5, window_minutes=15),
        "refresh": RefreshSession(uow, tokens, clock, 90),
        "revoke": RevokeSession(uow, clock),
        "update_profile": UpdateProfile(uow),
        "list_sessions": ListSessions(uow, clock),
        "delete_account": DeleteAccount(uow, hasher, clock),
        "uow": uow,
    }
    session_factory.kw["bind"].dispose()


def run_at_once(action: Callable[[], object], times: int = THREADS) -> list[object]:
    """Ejecuta `action` en varios hilos a la vez; devuelve resultado o excepción de cada uno."""
    barrier = threading.Barrier(times)

    def task():
        barrier.wait()
        try:
            return action()
        except Exception as error:  # noqa: BLE001 - se devuelve para analizarla
            return error

    with ThreadPoolExecutor(max_workers=times) as pool:
        return list(pool.map(lambda _: task(), range(times)))


def kinds(results: list[object]) -> Counter:
    return Counter("ok" if not isinstance(r, Exception) else type(r).__name__ for r in results)


def test_simultaneous_registrations_of_the_same_email_create_exactly_one_account(services):
    results = run_at_once(
        lambda: services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    )

    assert kinds(results) == Counter({"ok": 1, EmailAlreadyRegistered.__name__: THREADS - 1})


def test_simultaneous_logins_on_the_same_device_leave_exactly_one_active_session(services):
    services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")

    results = run_at_once(
        lambda: services["log_in"].execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")
    )

    assert kinds(results) == Counter({"ok": THREADS})
    with services["uow"]() as uow:
        user = uow.users.get_by_email("luis@example.com")
        assert len(uow.sessions.list_unrevoked_for_device(user.id, "pixel-8-abc")) == 1


def test_simultaneous_logins_on_different_devices_all_stay_active(services):
    services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    counter = iter(range(THREADS))
    lock = threading.Lock()

    def log_in_new_device():
        with lock:
            device = f"dispositivo-{next(counter)}"
        return services["log_in"].execute("luis@example.com", PASSWORD, device, device)

    results = run_at_once(log_in_new_device)

    assert kinds(results) == Counter({"ok": THREADS})
    with services["uow"]() as uow:
        user = uow.users.get_by_email("luis@example.com")
        assert len(uow.sessions.list_unrevoked_for_user(user.id)) == THREADS


def test_the_same_refresh_token_used_at_once_works_only_once(services):
    services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    first = services["log_in"].execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    results = run_at_once(lambda: services["refresh"].execute(first.refresh_token))

    # Uno gana; los demás llegan con un token que ya se cambió: es reutilización y la sesión se
    # cierra (comportamiento estricto del diseño). Nunca hay dos renovaciones exitosas.
    assert kinds(results) == Counter({"ok": 1, InvalidToken.__name__: THREADS - 1})
    with services["uow"]() as uow:
        session = uow.sessions.get(first.session_id)
        assert session.revoked_at is not None


def test_many_simultaneous_wrong_passwords_end_up_blocking_the_email(services):
    services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")

    run_at_once(
        lambda: services["log_in"].execute("luis@example.com", "equivocada" * 2, "d", "d"), times=10
    )

    from auth_service.domain.errors import TooManyAttempts

    with pytest.raises(TooManyAttempts):
        services["log_in"].execute("luis@example.com", PASSWORD, "d", "d")


def test_closing_the_same_device_many_times_at_once_always_succeeds(services):
    user = services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    tablet = services["log_in"].execute("luis@example.com", PASSWORD, "tableta", "Tableta")

    results = run_at_once(lambda: services["revoke"].execute(user.id, tablet.session_id))

    assert kinds(results) == Counter({"ok": THREADS})
    with services["uow"]() as uow:
        assert uow.sessions.get(tablet.session_id).revoked_at is not None


@pytest.mark.parametrize("round_", range(10))
def test_closing_a_device_while_it_refreshes_never_leaves_it_open(services, round_):
    user = services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    tablet = services["log_in"].execute("luis@example.com", PASSWORD, "tableta", "Tableta")
    actions = iter(
        [
            lambda: services["revoke"].execute(user.id, tablet.session_id),
            lambda: services["refresh"].execute(tablet.refresh_token),
        ]
    )
    lock = threading.Lock()

    def next_action():
        with lock:
            action = next(actions)
        return action()

    results = run_at_once(next_action, times=2)

    # Gane quien gane: cerrar siempre funciona, la renovación funciona o da InvalidToken, y al
    # final la sesión queda cerrada (también el refresh token nuevo, si se llegó a emitir).
    assert set(kinds(results)) <= {"ok", InvalidToken.__name__}
    with services["uow"]() as uow:
        assert uow.sessions.get(tablet.session_id).revoked_at is not None
    assert services["list_sessions"].execute(user.id) == []
    renewed = [r for r in results if r is not None and not isinstance(r, Exception)]
    for result in renewed:
        with pytest.raises(InvalidToken):
            services["refresh"].execute(result.refresh_token)


def test_simultaneous_full_renames_never_mix_two_of_them(services):
    user = services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    numbers = iter(range(THREADS))
    lock = threading.Lock()

    def rename():
        with lock:
            i = next(numbers)
        updated = services["update_profile"].execute(
            user.id, first_name=f"Nombre {i}", last_name=f"Apellido {i}"
        )
        return updated.first_name, updated.last_name

    results = run_at_once(rename)

    assert kinds(results) == Counter({"ok": THREADS})
    with services["uow"]() as uow:
        stored = uow.users.get(user.id)
    # Gana uno completo: nunca el nombre de un cambio con el apellido de otro.
    assert (stored.first_name, stored.last_name) in results
    assert stored.first_name.split()[1] == stored.last_name.split()[1]


def test_changing_first_and_last_name_at_once_loses_neither(services):
    """Uno cambia el nombre y otro el apellido al mismo tiempo: los dos cambios se quedan."""
    user = services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    numbers = iter(range(THREADS))
    lock = threading.Lock()

    def rename():
        with lock:
            i = next(numbers)
        if i % 2:
            return services["update_profile"].execute(user.id, first_name=f"Nombre {i}")
        return services["update_profile"].execute(user.id, last_name=f"Apellido {i}")

    results = run_at_once(rename)

    assert kinds(results) == Counter({"ok": THREADS})
    with services["uow"]() as uow:
        stored = uow.users.get(user.id)
    assert stored.first_name.startswith("Nombre ")
    assert stored.last_name.startswith("Apellido ")


def test_deleting_the_account_many_times_at_once_succeeds_only_once(services):
    user = services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")

    results = run_at_once(lambda: services["delete_account"].execute(user.id, PASSWORD))

    # El primero la elimina; los demás esperan el bloqueo y ya no encuentran la cuenta.
    assert kinds(results) == Counter({"ok": 1, WrongCurrentPassword.__name__: THREADS - 1})


def test_logins_racing_an_account_deletion_never_leave_an_active_session(services):
    user = services["register"].execute("luis@example.com", PASSWORD, "Luis", "Aguilar")
    counter = iter(range(THREADS))
    lock = threading.Lock()

    def delete_or_log_in():
        with lock:
            turn = next(counter)
        if turn == 0:
            return services["delete_account"].execute(user.id, PASSWORD)
        device = f"dispositivo-{turn}"
        return services["log_in"].execute("luis@example.com", PASSWORD, device, device)

    results = run_at_once(delete_or_log_in)

    # Cada inicio de sesión ocurre antes (y su sesión se revoca) o después (y se rechaza).
    assert set(kinds(results)) <= {"ok", InvalidCredentials.__name__}
    with services["uow"]() as uow:
        assert uow.users.get(user.id) is None
        assert uow.sessions.list_unrevoked_for_user(user.id) == []
