import pytest
from pydantic import ValidationError

from auth_service.config import Settings

from ..conftest import DATABASE_URL, JWT_SECRET


def test_token_defaults() -> None:
    settings = Settings(database_url=DATABASE_URL, jwt_secret=JWT_SECRET)

    assert settings.access_token_minutes == 15
    assert settings.refresh_token_days == 90


def test_short_jwt_secret_prevents_startup() -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=DATABASE_URL, jwt_secret="corto")


def test_secret_is_hidden_when_printing_settings() -> None:
    settings = Settings(database_url=DATABASE_URL, jwt_secret=JWT_SECRET)

    assert JWT_SECRET not in repr(settings)
