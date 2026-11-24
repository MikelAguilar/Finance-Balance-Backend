"""Pruebas contra PostgreSQL real. Se omiten si no existe la variable TEST_DATABASE_URL.

En CI la define el job `integracion`, que levanta PostgreSQL como servicio. En local:
    TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost:5432/base uv run pytest
La base indicada se vacía en cada prueba: no uses la de desarrollo.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from auth_service.config import Settings
from auth_service.main import create_app

from ..conftest import JWT_SECRET

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"

pytestmark = pytest.mark.integration


@pytest.fixture(scope="session")
def database_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Sin TEST_DATABASE_URL: las pruebas de integración necesitan PostgreSQL.")
    return url


@pytest.fixture(scope="session")
def alembic_config(database_url: str) -> Config:
    # migrations/env.py lee la configuración desde el entorno, igual que en producción.
    os.environ["DATABASE_URL"] = database_url
    os.environ["JWT_SECRET"] = JWT_SECRET
    return Config(str(ALEMBIC_INI))


@pytest.fixture(scope="session")
def engine(alembic_config: Config, database_url: str) -> Iterator[Engine]:
    command.upgrade(alembic_config, "head")
    engine = create_engine(database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "engine" in request.fixturenames:
        with request.getfixturevalue("engine").begin() as connection:
            connection.execute(text("TRUNCATE auth.users CASCADE"))


@pytest.fixture
def settings(engine: Engine, database_url: str) -> Settings:
    return Settings(app_env="development", database_url=database_url, jwt_secret=JWT_SECRET)


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))
