from alembic import context
from sqlalchemy import engine_from_config, pool

from auth_service.config import Settings
from auth_service.infrastructure.db import Base, include_auth_schema

target_metadata = Base.metadata
# La tabla de versiones de auth vive en public, con el esquema fijo: sin él, PostgreSQL la busca
# primero en el esquema con el nombre del usuario ("$user", public) y, si el usuario se llama
# finance, caería en el esquema de finanzas.
VERSION_TABLE_SCHEMA = "public"


def get_url() -> str:
    return Settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_auth_schema,
        version_table_schema=VERSION_TABLE_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        {"sqlalchemy.url": get_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_auth_schema,
            version_table_schema=VERSION_TABLE_SCHEMA,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
