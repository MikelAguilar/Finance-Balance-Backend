from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from auth_service.config import Settings
from auth_service.main import create_app

DATABASE_URL = "postgresql+psycopg://test:test@localhost:5432/test"
# Repetitivo a propósito: es de pruebas y no debe parecer un secreto real.
JWT_SECRET = "pruebas" * 6


@pytest.fixture
def make_client() -> Callable[[str], TestClient]:
    def _make(app_env: str) -> TestClient:
        settings = Settings(app_env=app_env, database_url=DATABASE_URL, jwt_secret=JWT_SECRET)
        return TestClient(create_app(settings))

    return _make
