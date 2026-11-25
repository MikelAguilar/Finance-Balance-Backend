"""Perfil, lista de dispositivos y cierre de la sesión de otro dispositivo (casos de uso)."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest

from auth_service.application.use_cases import (
    Authenticate,
    GetProfile,
    ListSessions,
    LogIn,
    RefreshSession,
    RegisterUser,
    RevokeSession,
    UpdateProfile,
)
from auth_service.domain.errors import InvalidToken, SessionNotFound
from auth_service.domain.model import Session

from .fakes import FakeClock, FakeHasher, FakeTokens, FakeUnitOfWork

PASSWORD = "una contraseña larga"
EMAIL = "luis@example.com"
OTHER_EMAIL = "ana@example.com"


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
    return RegisterUser(lambda: uow, FakeHasher(), clock).execute


@pytest.fixture
def user(register):
    return register(EMAIL, PASSWORD, "Luis Miguel", "Aguilar García")


@pytest.fixture
def log_in(uow, tokens, clock):
    use_case = LogIn(lambda: uow, FakeHasher(), tokens, clock, 90, 5, 15)
    return lambda device, email=EMAIL: use_case.execute(email, PASSWORD, device, device.title())


@pytest.fixture
def list_sessions(uow, clock) -> ListSessions:
    return ListSessions(lambda: uow, clock)


@pytest.fixture
def revoke(uow, clock) -> RevokeSession:
    return RevokeSession(lambda: uow, clock)


def session_ids(sessions: list[Session]) -> list[UUID]:
    return [s.id for s in sessions]


# ------------------------------------------------------------------ perfil


def test_profile_has_the_names_given_at_registration(uow, user) -> None:
    profile = GetProfile(lambda: uow).execute(user.id)

    assert profile.email == EMAIL
    assert (profile.first_name, profile.last_name) == ("Luis Miguel", "Aguilar García")


def test_update_profile_changes_both_names_in_one_commit(uow, user) -> None:
    commits = uow.commits

    updated = UpdateProfile(lambda: uow).execute(user.id, first_name="Ana", last_name="López")

    assert (updated.first_name, updated.last_name) == ("Ana", "López")
    stored = GetProfile(lambda: uow).execute(user.id)
    assert (stored.first_name, stored.last_name) == ("Ana", "López")
    assert uow.commits == commits + 1


def test_update_profile_changes_only_the_first_name(uow, user) -> None:
    updated = UpdateProfile(lambda: uow).execute(user.id, first_name="Luis")

    assert (updated.first_name, updated.last_name) == ("Luis", "Aguilar García")


def test_update_profile_changes_only_the_last_name(uow, user) -> None:
    updated = UpdateProfile(lambda: uow).execute(user.id, last_name="Aguilar")

    assert (updated.first_name, updated.last_name) == ("Luis Miguel", "Aguilar")


def test_update_profile_without_changes_keeps_both_names(uow, user) -> None:
    updated = UpdateProfile(lambda: uow).execute(user.id)

    assert (updated.first_name, updated.last_name) == ("Luis Miguel", "Aguilar García")


def test_update_profile_does_not_touch_email_or_password(uow, user) -> None:
    before = replace(user)

    after = UpdateProfile(lambda: uow).execute(user.id, first_name="Otro", last_name="Nombre")

    assert (after.email, after.password_hash, after.created_at) == (
        before.email,
        before.password_hash,
        before.created_at,
    )


@pytest.mark.parametrize("use_case", [GetProfile, UpdateProfile])
def test_profile_of_a_missing_account_is_an_invalid_token(uow, use_case) -> None:
    with pytest.raises(InvalidToken):
        if use_case is GetProfile:
            use_case(lambda: uow).execute(uuid4())
        else:
            use_case(lambda: uow).execute(uuid4(), first_name="Nombre")
    assert uow.commits == 0


# ------------------------------------------------------------------ lista de dispositivos


def test_list_is_empty_without_sessions(user, list_sessions) -> None:
    assert list_sessions.execute(user.id) == []


def test_list_orders_by_most_recent_use(user, log_in, list_sessions, uow, tokens, clock) -> None:
    phone = log_in("telefono")
    clock.advance(timedelta(minutes=1))
    tablet = log_in("tableta")
    clock.advance(timedelta(minutes=1))
    # Renovar el teléfono lo vuelve el más reciente.
    RefreshSession(lambda: uow, tokens, clock, 90).execute(phone.refresh_token)

    assert session_ids(list_sessions.execute(user.id)) == [phone.session_id, tablet.session_id]


def test_list_breaks_ties_by_creation_and_then_by_id(user, uow, clock, list_sessions) -> None:
    now = clock.now()

    def add(created_minutes_ago: int, session_id: UUID) -> Session:
        created = now - timedelta(minutes=created_minutes_ago)
        session = Session(
            id=session_id,
            user_id=user.id,
            device_id=str(session_id),
            device_name="x",
            refresh_token_hash=f"h{session_id}",
            created_at=created,
            last_used_at=now,
            expires_at=now + timedelta(days=1),
        )
        uow.sessions.add(session)
        return session

    older = add(10, UUID(int=9))
    newer_low_id = add(1, UUID(int=1))
    newer_high_id = add(1, UUID(int=2))

    assert session_ids(list_sessions.execute(user.id)) == [
        newer_high_id.id,
        newer_low_id.id,
        older.id,
    ]


def test_list_hides_revoked_expired_and_other_users_sessions(
    user, register, log_in, list_sessions, uow, clock
) -> None:
    register(OTHER_EMAIL, PASSWORD, "Otra", "Persona")
    log_in("de-ana", email=OTHER_EMAIL)
    revoked = log_in("revocado")
    uow.sessions.get(revoked.session_id).revoke(clock.now())
    expired = log_in("vencido")
    uow.sessions.get(expired.session_id).expires_at = clock.now()
    active = log_in("activo")

    assert session_ids(list_sessions.execute(user.id)) == [active.session_id]


def test_session_is_listed_until_the_exact_expiry_instant(
    user, log_in, list_sessions, clock
) -> None:
    result = log_in("telefono")
    clock.current = result.refresh_token_expires_at - timedelta(microseconds=1)

    assert session_ids(list_sessions.execute(user.id)) == [result.session_id]

    clock.advance(timedelta(microseconds=1))
    assert list_sessions.execute(user.id) == []


def test_listing_does_not_commit(user, log_in, list_sessions, uow) -> None:
    log_in("telefono")
    commits = uow.commits

    list_sessions.execute(user.id)

    assert uow.commits == commits


# ------------------------------------------------------------------ cerrar otro dispositivo


def test_revoking_another_device_closes_only_that_session(
    user, log_in, revoke, uow, tokens, clock
) -> None:
    phone, tablet = log_in("telefono"), log_in("tableta")
    authenticate = Authenticate(lambda: uow, tokens, clock)

    revoke.execute(user.id, tablet.session_id)

    assert uow.sessions.get(tablet.session_id).revoked_at == clock.now()
    with pytest.raises(InvalidToken):
        authenticate.execute(tablet.access_token)
    with pytest.raises(InvalidToken):
        RefreshSession(lambda: uow, tokens, clock, 90).execute(tablet.refresh_token)
    assert authenticate.execute(phone.access_token).session_id == phone.session_id


def test_revoking_the_current_session_by_id_works_like_log_out(
    user, log_in, revoke, uow, tokens, clock
) -> None:
    phone = log_in("telefono")

    revoke.execute(user.id, phone.session_id)

    with pytest.raises(InvalidToken):
        Authenticate(lambda: uow, tokens, clock).execute(phone.access_token)


def test_revoking_twice_is_idempotent_and_keeps_the_first_date(
    user, log_in, revoke, uow, clock
) -> None:
    tablet = log_in("tableta")
    revoke.execute(user.id, tablet.session_id)
    first = uow.sessions.get(tablet.session_id).revoked_at
    commits = uow.commits
    clock.advance(timedelta(hours=1))

    revoke.execute(user.id, tablet.session_id)

    assert uow.sessions.get(tablet.session_id).revoked_at == first
    assert uow.commits == commits


def test_revoking_an_expired_session_marks_it_revoked(user, log_in, revoke, uow, clock) -> None:
    tablet = log_in("tableta")
    clock.advance(timedelta(days=91))

    revoke.execute(user.id, tablet.session_id)

    assert uow.sessions.get(tablet.session_id).revoked_at == clock.now()


def test_revoking_another_users_session_looks_like_it_does_not_exist(
    user, register, log_in, revoke, uow
) -> None:
    register(OTHER_EMAIL, PASSWORD, "Otra", "Persona")
    anas = log_in("de-ana", email=OTHER_EMAIL)

    with pytest.raises(SessionNotFound):
        revoke.execute(user.id, anas.session_id)

    assert uow.sessions.get(anas.session_id).revoked_at is None


def test_revoking_an_unknown_session_raises_not_found(user, revoke, uow) -> None:
    with pytest.raises(SessionNotFound):
        revoke.execute(user.id, uuid4())
    assert uow.commits == 1  # solo el del registro


def test_device_can_log_in_again_after_being_revoked(user, log_in, revoke, list_sessions) -> None:
    tablet = log_in("tableta")
    revoke.execute(user.id, tablet.session_id)

    again = log_in("tableta")

    assert session_ids(list_sessions.execute(user.id)) == [again.session_id]
