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
    return LogIn(lambda: uow, hasher, FakeTokens(), clock, refresh_token_days=90)


def test_registrar_guarda_el_usuario_con_hash_y_correo_normalizado(register, uow, clock) -> None:
    user = register.execute(" Luis@Example.com", PASSWORD)

    assert user.email == "luis@example.com"
    assert user.password_hash == f"hashed:{PASSWORD}"
    assert user.created_at == clock.now()
    assert uow.users.get_by_email("luis@example.com") == user
    assert uow.commits == 1


def test_registrar_un_correo_existente_falla_sin_importar_mayusculas(register) -> None:
    register.execute("luis@example.com", PASSWORD)

    with pytest.raises(EmailAlreadyRegistered):
        register.execute("LUIS@example.com", PASSWORD)


def test_registrar_con_contrasena_corta_falla_y_no_guarda(register, uow) -> None:
    with pytest.raises(WeakPassword):
        register.execute("luis@example.com", "corta")

    assert uow.users.by_email == {}
    assert uow.commits == 0


def test_iniciar_sesion_crea_una_sesion_y_devuelve_tokens(register, log_in, uow, clock) -> None:
    user = register.execute("luis@example.com", PASSWORD)

    result = log_in.execute("Luis@Example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    [session] = uow.sessions.items
    assert result.session_id == session.id
    assert result.access_token == f"access:{user.id}:{session.id}"
    assert result.access_token_expires_at == clock.now() + timedelta(minutes=15)
    assert result.refresh_token == "refresh-1"
    assert result.refresh_token_expires_at == clock.now() + timedelta(days=90)
    assert session.user_id == user.id
    assert session.device_name == "Pixel 8"
    assert session.refresh_token_hash == "sha:refresh-1"
    assert session.is_active(clock.now())


def test_contrasena_incorrecta_no_crea_sesion(register, log_in, uow) -> None:
    register.execute("luis@example.com", PASSWORD)

    with pytest.raises(InvalidCredentials):
        log_in.execute("luis@example.com", "otra contraseña larga", "pixel-8-abc", "Pixel 8")

    assert uow.sessions.items == []


def test_correo_inexistente_falla_igual_y_tambien_verifica_un_hash(log_in, hasher) -> None:
    with pytest.raises(InvalidCredentials):
        log_in.execute("nadie@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    # Se verifica contra un hash de relleno para que la respuesta tarde lo mismo que con un
    # correo registrado: así el tiempo no revela qué correos existen.
    assert len(hasher.verified) == 1


def test_volver_a_iniciar_sesion_en_el_mismo_dispositivo_revoca_la_anterior(
    register, log_in, uow, clock
) -> None:
    register.execute("luis@example.com", PASSWORD)
    log_in.execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")
    clock.advance(timedelta(minutes=5))

    log_in.execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    first, second = uow.sessions.items
    assert first.revoked_at == clock.now()
    assert second.is_active(clock.now())


def test_iniciar_sesion_en_otro_dispositivo_no_cierra_las_demas(
    register, log_in, uow, clock
) -> None:
    register.execute("luis@example.com", PASSWORD)
    log_in.execute("luis@example.com", PASSWORD, "pixel-8-abc", "Pixel 8")

    log_in.execute("luis@example.com", PASSWORD, "galaxy-s24-xyz", "Galaxy S24")

    assert all(s.is_active(clock.now()) for s in uow.sessions.items)
    assert len(uow.sessions.items) == 2
