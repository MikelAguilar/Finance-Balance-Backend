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


def test_renovar_entrega_tokens_nuevos_y_el_anterior_deja_de_servir(user, log_in, refresh, uow):
    first = start(log_in)

    renewed = refresh.execute(first.refresh_token)

    assert renewed.session_id == first.session_id
    assert renewed.refresh_token != first.refresh_token
    with pytest.raises(InvalidToken):
        refresh.execute("token-que-no-existe")
    [session] = uow.sessions.items
    assert session.refresh_token_hash == f"sha:{renewed.refresh_token}"
    assert session.previous_refresh_token_hash == f"sha:{first.refresh_token}"


def test_renovar_extiende_la_sesion_90_dias_desde_el_uso(user, log_in, refresh, clock, uow):
    first = start(log_in)
    clock.advance(timedelta(days=30))

    renewed = refresh.execute(first.refresh_token)

    assert renewed.refresh_token_expires_at == clock.now() + timedelta(days=90)
    assert uow.sessions.items[0].last_used_at == clock.now()


def test_reutilizar_un_refresh_token_viejo_revoca_la_sesion(user, log_in, refresh, uow, clock):
    first = start(log_in)
    renewed = refresh.execute(first.refresh_token)

    with pytest.raises(InvalidToken):
        refresh.execute(first.refresh_token)

    assert uow.sessions.items[0].revoked_at == clock.now()
    # Tampoco sirve el token nuevo: quien lo tenga (¿el ladrón?) debe volver a iniciar sesión.
    with pytest.raises(InvalidToken):
        refresh.execute(renewed.refresh_token)


def test_no_se_renueva_una_sesion_vencida(user, log_in, refresh, clock):
    first = start(log_in)
    clock.advance(timedelta(days=90))

    with pytest.raises(InvalidToken):
        refresh.execute(first.refresh_token)


def test_no_se_renueva_una_sesion_revocada(user, log_in, refresh, uow, clock):
    first = start(log_in)
    uow.sessions.items[0].revoke(clock.now())

    with pytest.raises(InvalidToken):
        refresh.execute(first.refresh_token)


# ------------------------------------------------------------------ autenticar


def test_token_valido_con_sesion_activa_identifica_al_usuario(user, log_in, authenticate):
    result = start(log_in)

    context = authenticate.execute(result.access_token)

    assert context.user_id == user.id
    assert context.session_id == result.session_id


def test_token_vencido_se_rechaza(user, log_in, authenticate, clock):
    result = start(log_in)
    clock.advance(timedelta(minutes=15))

    with pytest.raises(InvalidToken):
        authenticate.execute(result.access_token)


def test_token_de_sesion_revocada_se_rechaza(user, log_in, authenticate, uow, clock):
    result = start(log_in)
    uow.sessions.items[0].revoke(clock.now())

    with pytest.raises(InvalidToken):
        authenticate.execute(result.access_token)


def test_token_que_no_corresponde_a_la_sesion_se_rechaza(user, log_in, authenticate, uow):
    result = start(log_in)
    uow.sessions.items.clear()

    with pytest.raises(InvalidToken):
        authenticate.execute(result.access_token)


# ------------------------------------------------------------------ cambiar contraseña


def test_cambiar_contrasena_revoca_las_demas_sesiones_y_conserva_la_actual(
    user, log_in, uow, hasher, clock
):
    phone = start(log_in, "pixel-8-abc")
    start(log_in, "galaxy-s24-xyz")
    change = ChangePassword(lambda: uow, hasher, clock)

    change.execute(user.id, phone.session_id, PASSWORD, NEW_PASSWORD)

    current, other = uow.sessions.items
    assert current.is_active(clock.now())
    assert other.revoked_at == clock.now()
    assert uow.users.get(user.id).password_hash == f"hashed:{NEW_PASSWORD}"


def test_cambiar_contrasena_exige_la_actual_correcta(user, log_in, uow, hasher, clock):
    phone = start(log_in)

    with pytest.raises(WrongCurrentPassword):
        ChangePassword(lambda: uow, hasher, clock).execute(
            user.id, phone.session_id, "no es la actual", NEW_PASSWORD
        )

    assert uow.users.get(user.id).password_hash == f"hashed:{PASSWORD}"


def test_la_contrasena_nueva_cumple_la_politica(user, log_in, uow, hasher, clock):
    phone = start(log_in)

    with pytest.raises(WeakPassword):
        ChangePassword(lambda: uow, hasher, clock).execute(
            user.id, phone.session_id, PASSWORD, "corta"
        )


# ------------------------------------------------------------------ cerrar sesión


def test_cerrar_sesion_revoca_solo_la_actual(user, log_in, uow, clock):
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


def test_el_sexto_intento_en_15_minutos_se_bloquea(user, log_in, clock):
    for _ in range(5):
        fail(log_in)
        clock.advance(timedelta(minutes=1))

    with pytest.raises(TooManyAttempts) as error:
        log_in.execute(EMAIL, PASSWORD, "pixel-8-abc", "Teléfono")

    # El primer fallo fue hace 5 minutos: se libera en 10.
    assert error.value.retry_after_seconds == 10 * 60


def test_el_bloqueo_termina_cuando_pasa_la_ventana(user, log_in, clock):
    for _ in range(5):
        fail(log_in)
    clock.advance(timedelta(minutes=15))

    assert start(log_in).access_token


def test_un_inicio_correcto_borra_los_fallos_anteriores(user, log_in, uow):
    for _ in range(4):
        fail(log_in)

    start(log_in)

    assert uow.login_attempts.failures == []


def test_los_fallos_con_correo_inexistente_tambien_cuentan(log_in):
    for _ in range(5):
        fail(log_in, "nadie@example.com")

    with pytest.raises(TooManyAttempts):
        log_in.execute("nadie@example.com", PASSWORD, "pixel-8-abc", "Teléfono")


def test_cada_fallo_se_confirma_aunque_el_inicio_falle(user, log_in, uow):
    commits_before = uow.commits

    fail(log_in)

    assert uow.commits == commits_before + 1
    assert len(uow.login_attempts.failures) == 1


def test_cerrar_una_sesion_inexistente_no_hace_nada(uow, clock):
    from uuid import uuid4

    LogOut(lambda: uow, clock).execute(uuid4())

    assert uow.commits == 0
