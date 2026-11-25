"""Pruebas contra PostgreSQL real. Se omiten si no existe la variable TEST_DATABASE_URL.

En CI la define el job `integracion`. La base indicada se vacía en cada prueba: no uses la de
desarrollo. Comparte base con las pruebas de auth, igual que en producción: cada servicio en su
esquema y con su propia tabla de versiones de Alembic.
"""

import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

ALEMBIC_INI = Path(__file__).parents[2] / "alembic.ini"
# Tablas que se vacían después de cada prueba que usa la base.
TABLES: list[str] = ["finance.cards"]

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


# --- Filas de ejemplo ----------------------------------------------------------------------------
# Prueban las reglas de la base sin pasar por el dominio. La base repite esas reglas como respaldo:
# si algún día otro código escribe sin validar, PostgreSQL lo rechaza igual.

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def sync_columns() -> dict:
    return {
        "id": uuid4(),
        "user_id": uuid4(),
        "idempotency_key": uuid4(),
        "version": 1,
        "updated_at": NOW,
        "server_updated_at": NOW,
        "deleted_at": None,
    }


@pytest.fixture
def make_card() -> Callable[..., dict]:
    def _make(**changes: object) -> dict:
        return {
            **sync_columns(),
            "name": "Oro",
            "cut_day": 5,
            "personal_limit_cents": 1_000_000,
            "bank_limit_cents": 2_500_000,
            "used_at_creation_cents": 0,
            "installments_count_against_limit": True,
            **changes,
        }

    return _make


@pytest.fixture
def insert(engine) -> Callable[[str, dict], None]:
    def _insert(table: str, row: dict) -> None:
        columns = ", ".join(row)
        values = ", ".join(f":{column}" for column in row)
        with engine.begin() as connection:
            connection.execute(
                text(f"INSERT INTO finance.{table} ({columns}) VALUES ({values})"), row
            )

    return _insert
