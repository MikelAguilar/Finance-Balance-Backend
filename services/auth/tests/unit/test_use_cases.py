from datetime import timedelta

import pytest

from auth_service.application.use_cases import LogIn, RegisterUser
from auth_service.domain.errors import EmailAlreadyRegistered, InvalidCredentials, WeakPassword

from .fakes import FakeClock, FakeHasher, FakeTokens, FakeUnitOfWork

PASSWORD = "una contraseña larga"


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def hasher() -> FakeHasher:
    return FakeHasher()


@pytest.fixture
def register(uow, hasher, clock) -> RegisterUser:
    return RegisterUser(lambda: uow, hasher, clock)


@pytest.fixture
def log_in(uow, hasher, clock) -> LogIn:
    return LogIn(
        lambda: uow,
        hasher,
        FakeTokens(),
        clock,
        refresh_token_days=90,
        max_attempts=5,
        window_minutes=15,
    )


def test_register_saves_user_with_hash_and_normalized_email(register, uow, clock) -> None:
    user = register.execute(" Luis@Example.com", PASSWORD)

    assert user.email == "luis@example.com"
    assert user.password_hash == f"hashed:{PASSWORD}"
    assert user.created_at == clock.now()
    assert uow.users.get_by_email("luis@example.com") == user
    assert uow.commits == 1


def test_register_existing_email_fails_regardless_of_case(register) -> None:
    register.execute("luis@example.com", PASSWORD)

    with pytest.raises(EmailAlreadyRegistered):
        register.execute("LUIS@example.com", PASSWORD)


def test_register_with_short_password_fails_and_saves_nothing(register, uow) -> None:
    with pytest.raises(WeakPassword):
        register.execute("luis@example.com", "corta")

    assert uow.users.by_email == {}
    assert uow.commits == 0


def test_login_creates_session_and_returns_tokens(register, log_in, uow, clock) -> None:
    user = register.execute("luis@example.com", PASSWORD)

    result = log_in.execute("Luis@Example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    [session] = uow.sessions.items
    assert result.session_id == session.id
    assert result.access_token.startswith(f"access:{user.id}:{session.id}:")
    assert result.access_token_expires_at == clock.now() + timedelta(minutes=15)
    assert result.refresh_token == "refresh-1"
    assert result.refresh_token_expires_at == clock.now() + timedelta(days=90)
    assert session.user_id == user.id
    assert session.device_name == "Pixel 8"
    assert session.refresh_token_hash == "sha:refresh-1"
    assert session.is_active(clock.now())


def test_wrong_password_creates_no_session(register, log_in, uow) -> None:
    register.execute("luis@example.com", PASSWORD)

    with pytest.raises(InvalidCredentials):
        log_in.execute("luis@example.com", "otra contraseña larga", "pixel-8-abc", "Pixel 8")

    assert uow.sessions.items == []


def test_unknown_email_fails_the_same_and_still_verifies_a_hash(log_in, hasher) -> None:
    with pytest.raises(InvalidCredentials):
        log_in.execute("nadie@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    # Se verifica contra un hash de relleno para que la respuesta tarde lo mismo que con un
    # correo registrado: así el tiempo no revela qué correos existen.
    assert len(hasher.verified) == 1


def test_logging_in_again_on_same_device_revokes_previous(register, log_in, uow, clock) -> None:
    register.execute("luis@example.com", PASSWORD)
    log_in.execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")
    clock.advance(timedelta(minutes=5))

    log_in.execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    first, second = uow.sessions.items
    assert first.revoked_at == clock.now()
    assert second.is_active(clock.now())


def test_login_on_another_device_keeps_other_sessions(register, log_in, uow, clock) -> None:
    register.execute("luis@example.com", PASSWORD)
    log_in.execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    log_in.execute("luis@example.com", PASSWORD, "galaxy-s24-xyz", "Galaxy S24")

    assert all(s.is_active(clock.now()) for s in uow.sessions.items)
    assert len(uow.sessions.items) == 2
