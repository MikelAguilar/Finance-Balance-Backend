from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from auth_service.domain.errors import WeakPassword
from auth_service.domain.model import (
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    Session,
    check_password_policy,
    normalize_email,
)

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


def make_session(**overrides) -> Session:
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "device_id": "pixel-8-abc",
        "device_name": "Pixel 8",
        "refresh_token_hash": "a" * 64,
        "created_at": NOW,
        "last_used_at": NOW,
        "expires_at": NOW + timedelta(days=90),
    }
    return Session(**(values | overrides))


def test_el_correo_se_guarda_en_minusculas_y_sin_espacios() -> None:
    assert normalize_email("  Luis@Example.COM ") == "luis@example.com"


@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH])
def test_contrasena_en_los_limites_es_valida(length: int) -> None:
    check_password_policy("x" * length)


@pytest.mark.parametrize("length", [MIN_PASSWORD_LENGTH - 1, MAX_PASSWORD_LENGTH + 1])
def test_contrasena_fuera_de_los_limites_se_rechaza(length: int) -> None:
    with pytest.raises(WeakPassword):
        check_password_policy("x" * length)


def test_la_contrasena_no_exige_simbolos() -> None:
    check_password_policy("solo letras y espacios")


def test_sesion_nueva_esta_activa() -> None:
    assert make_session().is_active(NOW)


def test_sesion_vencida_no_esta_activa() -> None:
    session = make_session(expires_at=NOW)

    assert not session.is_active(NOW)


def test_sesion_revocada_no_esta_activa() -> None:
    session = make_session()

    session.revoke(NOW)

    assert session.revoked_at == NOW
    assert not session.is_active(NOW)


def test_revocar_dos_veces_conserva_la_primera_fecha() -> None:
    session = make_session()
    session.revoke(NOW)

    session.revoke(NOW + timedelta(hours=1))

    assert session.revoked_at == NOW
