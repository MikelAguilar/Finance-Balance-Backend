from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DATABASE_URL = "postgresql+psycopg://test:test@localhost:5432/test"


@pytest.fixture
def crear_cliente() -> Callable[[str], TestClient]:
    def _crear(app_env: str) -> TestClient:
        settings = Settings(app_env=app_env, database_url=DATABASE_URL)
        return TestClient(create_app(settings))

    return _crear
