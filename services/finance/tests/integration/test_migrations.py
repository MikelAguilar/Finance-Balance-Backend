from collections.abc import Iterator

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from finance_service.infrastructure.db import SCHEMA, Base, include_finance_schema

# Las tablas de finanzas que deben existir después de migrar.
TABLES: set[str] = set()


@pytest.fixture
def other_service_schema(engine) -> Iterator[None]:
    """El esquema de otro servicio en la misma base (como auth en producción)."""
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA otro_servicio"))
        connection.execute(text("CREATE TABLE otro_servicio.datos (id int)"))
    yield
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA otro_servicio CASCADE"))


def finance_tables(engine) -> set[str]:
    return set(inspect(engine).get_table_names(schema="finance"))


def test_migrations_live_in_their_own_schema_with_their_own_version_table(engine) -> None:
    assert finance_tables(engine) == {"alembic_version", *TABLES}
    # La tabla de versiones de auth (en public) no es la de finanzas: cada servicio sube y baja
    # sus migraciones sin ver las del otro.
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM finance.alembic_version")).scalar()


def test_models_match_the_migrations_and_ignore_other_schemas(engine, other_service_schema) -> None:
    with engine.connect() as connection:
        opts = {
            "include_schemas": True,
            "include_name": include_finance_schema,
            "version_table_schema": SCHEMA,
        }
        context = MigrationContext.configure(connection, opts=opts)
        assert compare_metadata(context, Base.metadata) == []


def test_migrations_go_down_and_up_without_touching_other_schemas(
    alembic_config, engine, other_service_schema
) -> None:
    try:
        command.downgrade(alembic_config, "base")
        assert finance_tables(engine) == {"alembic_version"}
        assert inspect(engine).get_table_names(schema="otro_servicio") == ["datos"]
    finally:
        command.upgrade(alembic_config, "head")
    assert finance_tables(engine) == {"alembic_version", *TABLES}
