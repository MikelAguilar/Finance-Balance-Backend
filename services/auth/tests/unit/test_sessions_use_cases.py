"""Renovar, autenticar, cambiar contraseña, cerrar sesión y límite de intentos."""

from datetime import timedelta

import pytest

from auth_service.application.use_cases import (
    Authenticate,
    ChangePassword,
    LogIn,
    LogOut,
    RefreshSession,
    RegisterUser,
)
from auth_service.domain.errors import (
    InvalidCredentials,
    InvalidToken,
    TooManyAttempts,
    WeakPassword,
    WrongCurrentPassword,
)

from .fakes import FakeClock, FakeHasher, FakeTokens, FakeUnitOfWork

PASSWORD = "una contraseña larga"
NEW_PASSWORD = "otra contraseña muy larga"
EMAIL = "luis@example.com"


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def tokens() -> FakeTokens:
    return FakeTokens()


@pytest.fixture
def hasher() -> FakeHasher:
    return FakeHasher()


@pytest.fixture
def user(uow, hasher, clock):
    return RegisterUser(lambda: uow, hasher, clock).execute(EMAIL, PASSWORD)


@pytest.fixture
def log_in(uow, hasher, tokens, clock) -> LogIn:
    return LogIn(
        lambda: uow, hasher, tokens, clock, refresh_token_days=90, max_attempts=5, window_minutes=15
    )


@pytest.fixture
def refresh(uow, tokens, clock) -> RefreshSession:
    return RefreshSession(lambda: uow, tokens, clock, refresh_token_days=90)


@pytest.fixture
def authenticate(uow, tokens, clock) -> Authenticate:
    return Authenticate(lambda: uow, tokens, clock)


def start(log_in, device_id="pixel-8-abc"):
    return log_in.execute(EMAIL, PASSWORD, device_id, "Teléfono")


# ------------------------------------------------------------------ renovar


def test_refresh_issues_new_tokens_and_old_one_stops_working(user, log_in, refresh, uow):
    first = start(log_in)

    renewed = refresh.execute(first.refresh_token)

    assert renewed.session_id == first.session_id
    assert renewed.refresh_token != first.refresh_token
    with pytest.raises(InvalidToken):
        refresh.execute("token-que-no-existe")
    [session] = uow.sessions.items
    assert session.refresh_token_hash == f"sha:{renewed.refresh_token}"
    assert session.previous_refresh_token_hash == f"sha:{first.refresh_token}"


def test_refresh_extends_session_90_days_from_use(user, log_in, refresh, clock, uow):
    first = start(log_in)
    clock.advance(timedelta(days=30))

    renewed = refresh.execute(first.refresh_token)

    assert renewed.refresh_token_expires_at == clock.now() + timedelta(days=90)
    assert uow.sessions.items[0].last_used_at == clock.now()


def test_reusing_old_refresh_token_revokes_session(user, log_in, refresh, uow, clock):
    first = start(log_in)
    renewed = refresh.execute(first.refresh_token)

    with pytest.raises(InvalidToken):
        refresh.execute(first.refresh_token)

    assert uow.sessions.items[0].revoked_at == clock.now()
    # Tampoco sirve el token nuevo: quien lo tenga (¿el ladrón?) debe volver a iniciar sesión.
    with pytest.raises(InvalidToken):
        refresh.execute(renewed.refresh_token)


def test_expired_session_cannot_be_refreshed(user, log_in, refresh, clock):
    first = start(log_in)
    clock.advance(timedelta(days=90))

    with pytest.raises(InvalidToken):
        refresh.execute(first.refresh_token)


def test_revoked_session_cannot_be_refreshed(user, log_in, refresh, uow, clock):
    first = start(log_in)
    uow.sessions.items[0].revoke(clock.now())

    with pytest.raises(InvalidToken):
        refresh.execute(first.refresh_token)


# ------------------------------------------------------------------ autenticar


def test_valid_token_with_active_session_identifies_user(user, log_in, authenticate):
    result = start(log_in)

    context = authenticate.execute(result.access_token)

    assert context.user_id == user.id
    assert context.session_id == result.session_id


def test_expired_token_is_rejected(user, log_in, authenticate, clock):
    result = start(log_in)
    clock.advance(timedelta(minutes=15))

    with pytest.raises(InvalidToken):
        authenticate.execute(result.access_token)


def test_token_of_revoked_session_is_rejected(user, log_in, authenticate, uow, clock):
    result = start(log_in)
    uow.sessions.items[0].revoke(clock.now())

    with pytest.raises(InvalidToken):
        authenticate.execute(result.access_token)


def test_token_without_matching_session_is_rejected(user, log_in, authenticate, uow):
    result = start(log_in)
    uow.sessions.items.clear()

    with pytest.raises(InvalidToken):
        authenticate.execute(result.access_token)


# ------------------------------------------------------------------ cambiar contraseña


def test_change_password_revokes_other_sessions_and_keeps_current(user, log_in, uow, hasher, clock):
    phone = start(log_in, "pixel-8-abc")
    start(log_in, "galaxy-s24-xyz")
    change = ChangePassword(lambda: uow, hasher, clock)

    change.execute(user.id, phone.session_id, PASSWORD, NEW_PASSWORD)

    current, other = uow.sessions.items
    assert current.is_active(clock.now())
    assert other.revoked_at == clock.now()
    assert uow.users.get(user.id).password_hash == f"hashed:{NEW_PASSWORD}"


def test_change_password_requires_correct_current_password(user, log_in, uow, hasher, clock):
    phone = start(log_in)

    with pytest.raises(WrongCurrentPassword):
        ChangePassword(lambda: uow, hasher, clock).execute(
            user.id, phone.session_id, "no es la actual", NEW_PASSWORD
        )

    assert uow.users.get(user.id).password_hash == f"hashed:{PASSWORD}"


def test_new_password_follows_policy(user, log_in, uow, hasher, clock):
    phone = start(log_in)

    with pytest.raises(WeakPassword):
        ChangePassword(lambda: uow, hasher, clock).execute(
            user.id, phone.session_id, PASSWORD, "corta"
        )


# ------------------------------------------------------------------ cerrar sesión


def test_logout_revokes_only_current_session(user, log_in, uow, clock):
    phone = start(log_in, "pixel-8-abc")
    start(log_in, "galaxy-s24-xyz")

    LogOut(lambda: uow, clock).execute(phone.session_id)

    current, other = uow.sessions.items
    assert current.revoked_at == clock.now()
    assert other.is_active(clock.now())


# ------------------------------------------------------------------ límite de intentos


def fail(log_in, email=EMAIL):
    with pytest.raises(InvalidCredentials):
        log_in.execute(email, "contraseña equivocada", "pixel-8-abc", "Teléfono")


def test_sixth_attempt_within_window_is_blocked(user, log_in, clock):
    for _ in range(5):
        fail(log_in)
        clock.advance(timedelta(minutes=1))

    with pytest.raises(TooManyAttempts) as error:
        log_in.execute(EMAIL, PASSWORD, "pixel-8-abc", "Teléfono")

    # El primer fallo fue hace 5 minutos: se libera en 10.
    assert error.value.retry_after_seconds == 10 * 60


def test_lockout_ends_when_window_passes(user, log_in, clock):
    for _ in range(5):
        fail(log_in)
    clock.advance(timedelta(minutes=15))

    assert start(log_in).access_token


def test_successful_login_clears_previous_failures(user, log_in, uow):
    for _ in range(4):
        fail(log_in)

    start(log_in)

    assert uow.login_attempts.failures == []


def test_failures_for_unknown_email_also_count(log_in):
    for _ in range(5):
        fail(log_in, "nadie@example.com")

    with pytest.raises(TooManyAttempts):
        log_in.execute("nadie@example.com", PASSWORD, "pixel-8-abc", "Teléfono")


def test_each_failure_is_committed_even_though_login_fails(user, log_in, uow):
    commits_before = uow.commits

    fail(log_in)

    assert uow.commits == commits_before + 1
    assert len(uow.login_attempts.failures) == 1


def test_logout_of_missing_session_is_a_no_op(uow, clock):
    from uuid import uuid4

    LogOut(lambda: uow, clock).execute(uuid4())

    assert uow.commits == 0
