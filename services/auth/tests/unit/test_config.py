import pytest
from pydantic import ValidationError

from auth_service.config import Settings

from ..conftest import DATABASE_URL, JWT_SECRET


def test_valores_por_defecto_de_los_tokens() -> None:
    settings = Settings(database_url=DATABASE_URL, jwt_secret=JWT_SECRET)

    assert settings.access_token_minutes == 15
    assert settings.refresh_token_days == 90


def test_secreto_jwt_corto_impide_arrancar() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, jwt_secret="corto")


def test_el_secreto_no_aparece_al_imprimir_la_configuracion() -> None:
    settings = Settings(database_url=DATABASE_URL, jwt_secret=JWT_SECRET)

    assert JWT_SECRET not in repr(settings)
