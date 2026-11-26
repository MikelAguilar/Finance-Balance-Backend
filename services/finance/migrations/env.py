from alembic import context
from sqlalchemy import engine_from_config, pool, text

from finance_service.config import Settings
from finance_service.infrastructure.db import SCHEMA, Base, include_finance_schema

target_metadata = Base.metadata

# Finanzas comparte la base con auth. Su tabla de versiones vive en su propio esquema: así cada
# servicio sube y baja sus migraciones sin ver las del otro (la de auth está en public).
OPTIONS = {
    "target_metadata": target_metadata,
    "include_schemas": True,
    "include_name": include_finance_schema,
    "version_table_schema": SCHEMA,
}


def run_migrations_offline() -> None:
    context.configure(url=Settings().database_url, literal_binds=True, **OPTIONS)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": Settings().database_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # La tabla de versiones necesita el esquema antes de la primera migración.
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(connection=connection, **OPTIONS)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
