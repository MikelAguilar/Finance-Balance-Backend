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

from auth_service.application.use_cases import LogIn, RefreshSession, RegisterUser
from auth_service.domain.errors import EmailAlreadyRegistered, InvalidToken
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
    results = run_at_once(lambda: services["register"].execute("luis@example.com", PASSWORD))

    assert kinds(results) == Counter({"ok": 1, EmailAlreadyRegistered.__name__: THREADS - 1})


def test_simultaneous_logins_on_the_same_device_leave_exactly_one_active_session(services):
    services["register"].execute("luis@example.com", PASSWORD)

    results = run_at_once(
        lambda: services["log_in"].execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")
    )

    assert kinds(results) == Counter({"ok": THREADS})
    with services["uow"]() as uow:
        user = uow.users.get_by_email("luis@example.com")
        assert len(uow.sessions.list_unrevoked_for_device(user.id, "pixel-8-abc")) == 1


def test_simultaneous_logins_on_different_devices_all_stay_active(services):
    services["register"].execute("luis@example.com", PASSWORD)
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
    services["register"].execute("luis@example.com", PASSWORD)
    first = services["log_in"].execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    results = run_at_once(lambda: services["refresh"].execute(first.refresh_token))

    # Uno gana; los demás llegan con un token que ya se cambió: es reutilización y la sesión se
    # cierra (comportamiento estricto del diseño). Nunca hay dos renovaciones exitosas.
    assert kinds(results) == Counter({"ok": 1, InvalidToken.__name__: THREADS - 1})
    with services["uow"]() as uow:
        session = uow.sessions.get(first.session_id)
        assert session.revoked_at is not None


def test_many_simultaneous_wrong_passwords_end_up_blocking_the_email(services):
    services["register"].execute("luis@example.com", PASSWORD)

    run_at_once(
        lambda: services["log_in"].execute("luis@example.com", "equivocada" * 2, "d", "d"), times=10
    )

    from auth_service.domain.errors import TooManyAttempts

    with pytest.raises(TooManyAttempts):
        services["log_in"].execute("luis@example.com", PASSWORD, "d", "d")
