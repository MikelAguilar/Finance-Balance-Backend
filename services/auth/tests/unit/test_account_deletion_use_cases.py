"""Eliminar la cuenta: solo borrado lógico (casos de uso, con dobles en memoria)."""

from uuid import uuid4

import pytest

from auth_service.application.use_cases import (
    Authenticate,
    DeleteAccount,
    GetProfile,
    LogIn,
    RefreshSession,
    RegisterUser,
)
from auth_service.domain.errors import InvalidCredentials, InvalidToken, WrongCurrentPassword

from .fakes import FakeClock, FakeHasher, FakeTokens, FakeUnitOfWork

PASSWORD = "una contraseña larga"
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
def register(uow, clock):
    use_case = RegisterUser(lambda: uow, FakeHasher(), clock)
    return lambda email=EMAIL: use_case.execute(email, PASSWORD, "Luis Miguel", "Aguilar García")


@pytest.fixture
def user(register):
    return register()


@pytest.fixture
def log_in(uow, tokens, clock):
    use_case = LogIn(lambda: uow, FakeHasher(), tokens, clock, 90, 5, 15)
    return lambda device, email=EMAIL: use_case.execute(email, PASSWORD, device, device.title())


@pytest.fixture
def delete(uow, clock) -> DeleteAccount:
    return DeleteAccount(lambda: uow, FakeHasher(), clock)


# ------------------------------------------------------------------ eliminar la cuenta


def test_delete_marks_the_account_and_revokes_every_session(
    uow, clock, user, log_in, delete
) -> None:
    log_in("telefono")
    log_in("tableta")
    commits = uow.commits

    delete.execute(user.id, PASSWORD)

    assert user.deleted_at == clock.now()
    assert all(session.revoked_at == clock.now() for session in uow.sessions.items)
    assert uow.commits == commits + 1
    # Borrado lógico: la cuenta y sus sesiones siguen guardadas.
    assert uow.users.items == [user]
    assert len(uow.sessions.items) == 2


def test_wrong_password_changes_nothing(uow, user, log_in, delete) -> None:
    log_in("telefono")
    commits = uow.commits

    with pytest.raises(WrongCurrentPassword):
        delete.execute(user.id, "otra contraseña larga")

    assert user.deleted_at is None
    assert uow.sessions.items[0].revoked_at is None
    assert uow.commits == commits


def test_deleting_a_missing_or_already_deleted_account_is_rejected(uow, user, delete) -> None:
    delete.execute(user.id, PASSWORD)
    commits = uow.commits

    for user_id in (user.id, uuid4()):
        with pytest.raises(WrongCurrentPassword):
            delete.execute(user_id, PASSWORD)
    assert uow.commits == commits


def test_deleted_account_cannot_log_in_and_looks_like_a_wrong_password(
    uow, user, log_in, delete
) -> None:
    delete.execute(user.id, PASSWORD)

    with pytest.raises(InvalidCredentials):
        log_in("telefono")
    # Cuenta como un fallo más del límite de intentos, igual que un correo inexistente.
    assert len(uow.login_attempts.failures) == 1


def test_old_tokens_of_a_deleted_account_stop_working(
    uow, tokens, clock, user, log_in, delete
) -> None:
    session = log_in("telefono")

    delete.execute(user.id, PASSWORD)

    with pytest.raises(InvalidToken):
        Authenticate(lambda: uow, tokens, clock).execute(session.access_token)
    with pytest.raises(InvalidToken):
        RefreshSession(lambda: uow, tokens, clock, 90).execute(session.refresh_token)
    with pytest.raises(InvalidToken):
        GetProfile(lambda: uow).execute(user.id)


def test_the_email_is_free_again_after_deleting(uow, user, register, log_in, delete) -> None:
    delete.execute(user.id, PASSWORD)

    new_user = register()

    assert new_user.id != user.id
    assert log_in("telefono").session_id is not None
    assert uow.users.get_by_email(EMAIL) == new_user
