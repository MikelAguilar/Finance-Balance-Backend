"""Pruebas contra PostgreSQL real. Se omiten si no existe la variable TEST_DATABASE_URL.

En CI la define el job `integracion`. La base indicada se vacía en cada prueba: no uses la de
desarrollo. Comparte base con las pruebas de auth, igual que en producción: cada servicio en su
esquema y con su propia tabla de versiones de Alembic.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"
# Tablas que se vacían después de cada prueba que usa la base.
TABLES: list[str] = []

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
    if TABLES and "engine" in request.fixturenames:
        with request.getfixturevalue("engine").begin() as connection:
            connection.execute(text(f"TRUNCATE {', '.join(TABLES)} CASCADE"))
