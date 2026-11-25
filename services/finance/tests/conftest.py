from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from finance_service.config import Settings
from finance_service.main import create_app

# Puerto cerrado a propósito: si una prueba sin base llega a conectarse, falla al instante.
DATABASE_URL = "postgresql+psycopg://test:test@127.0.0.1:1/test?connect_timeout=1"


@pytest.fixture
def make_settings() -> Callable[..., Settings]:
    def _make(**values: str) -> Settings:
        return Settings(**{"database_url": DATABASE_URL, **values})

    return _make


@pytest.fixture
def make_client(make_settings) -> Callable[[str], TestClient]:
    def _make(app_env: str) -> TestClient:
        return TestClient(create_app(make_settings(app_env=app_env)))

    return _make
