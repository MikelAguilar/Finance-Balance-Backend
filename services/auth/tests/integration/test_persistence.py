"""Repositorios, restricciones de la base y migraciones contra PostgreSQL real."""

from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from auth_service.domain.errors import EmailAlreadyRegistered
from auth_service.domain.model import Session, User
from auth_service.infrastructure.db import Base, build_session_factory, include_auth_schema
from auth_service.infrastructure.repositories import SqlUnitOfWork

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def uow_factory(settings):
    session_factory = build_session_factory(settings.database_url)
    yield partial(SqlUnitOfWork, session_factory)
    session_factory.kw["bind"].dispose()


def new_user(email="luis@example.com") -> User:
    return User(
        id=uuid4(),
        email=email,
        password_hash="hash",
        created_at=NOW,
        first_name="Luis Miguel",
        last_name="Aguilar García",
    )


def new_session(user_id, device_id="pixel-8-abc") -> Session:
    return Session(
        id=uuid4(),
        user_id=user_id,
        device_id=device_id,
        device_name="Pixel 8",
        refresh_token_hash=uuid4().hex + uuid4().hex,
        created_at=NOW,
        last_used_at=NOW,
        expires_at=NOW + timedelta(days=90),
    )


def test_saved_user_round_trips(uow_factory) -> None:
    user = new_user()
    with uow_factory() as uow:
        uow.users.add(user)
        uow.commit()

    with uow_factory() as uow:
        assert uow.users.get_by_email("luis@example.com") == user


def test_names_round_trip_with_any_unicode_and_up_to_100_characters(uow_factory) -> None:
    user = new_user()
    with uow_factory() as uow:
        uow.users.add(user)
        uow.commit()

    with uow_factory() as uow:
        stored = uow.users.get(user.id)
        stored.first_name = "Zoë 🙂 李"
        stored.last_name = "ñ" * 100
        uow.commit()
    with uow_factory() as uow:
        stored = uow.users.get(user.id)
        assert (stored.first_name, stored.last_name) == ("Zoë 🙂 李", "ñ" * 100)


@pytest.mark.parametrize("field", ["first_name", "last_name"])
def test_database_rejects_a_user_without_first_or_last_name(uow_factory, field) -> None:
    user = new_user()
    setattr(user, field, None)
    with pytest.raises(IntegrityError), uow_factory() as uow:
        uow.users.add(user)
        uow.commit()


def test_nothing_is_saved_without_commit(uow_factory) -> None:
    with uow_factory() as uow:
        uow.users.add(new_user())

    with uow_factory() as uow:
        assert uow.users.get_by_email("luis@example.com") is None


def test_duplicate_email_race_becomes_domain_error(uow_factory) -> None:
    # Simula dos registros simultáneos: los dos pasaron la verificación previa.
    with uow_factory() as uow:
        uow.users.add(new_user())
        uow.commit()

    with uow_factory() as uow, pytest.raises(EmailAlreadyRegistered):
        uow.users.add(new_user())
        uow.commit()


def test_database_forbids_two_unrevoked_sessions_per_device(uow_factory) -> None:
    user = new_user()
    with uow_factory() as uow:
        uow.users.add(user)
        uow.sessions.add(new_session(user.id))
        uow.commit()

    with uow_factory() as uow, pytest.raises(IntegrityError):
        uow.sessions.add(new_session(user.id))
        uow.commit()


def test_revoke_and_create_in_same_transaction(uow_factory) -> None:
    user = new_user()
    with uow_factory() as uow:
        uow.users.add(user)
        uow.sessions.add(new_session(user.id))
        uow.commit()

    with uow_factory() as uow:
        [previous] = uow.sessions.list_unrevoked_for_device(user.id, "pixel-8-abc")
        previous.revoke(NOW)
        uow.sessions.add(new_session(user.id))
        uow.commit()

    with uow_factory() as uow:
        assert len(uow.sessions.list_unrevoked_for_device(user.id, "pixel-8-abc")) == 1


def test_models_match_migrations(engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_schemas": True, "include_name": include_auth_schema},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_migrations_downgrade_and_upgrade(alembic_config, engine) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")


def test_migration_0005_keeps_existing_names_both_ways(alembic_config, engine) -> None:
    """Las cuentas que ya existían no pierden su nombre al subir ni al bajar la migración."""
    command.downgrade(alembic_config, "0004_user_name")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO auth.users (id, email, password_hash, created_at, name) VALUES "
                    "(gen_random_uuid(), 'con@example.com', 'h', now(), 'Luis Miguel'), "
                    "(gen_random_uuid(), 'sin@example.com', 'h', now(), NULL)"
                )
            )

        command.upgrade(alembic_config, "head")
        with engine.connect() as connection:
            upgraded = connection.execute(
                text("SELECT email, first_name, last_name FROM auth.users ORDER BY email")
            ).all()
        assert [tuple(row) for row in upgraded] == [
            ("con@example.com", "Luis Miguel", ""),
            ("sin@example.com", "", ""),
        ]

        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE auth.users SET first_name = :first, last_name = :last "
                    "WHERE email = 'con@example.com'"
                ),
                {"first": "x" * 100, "last": "Aguilar García"},
            )
        command.downgrade(alembic_config, "0004_user_name")
        with engine.connect() as connection:
            downgraded = connection.execute(
                text("SELECT email, name FROM auth.users ORDER BY email")
            ).all()
        # «nombre apellido» recortado a 100 caracteres; sin nombre ni apellido queda NULL.
        assert [tuple(row) for row in downgraded] == [
            ("con@example.com", "x" * 100),
            ("sin@example.com", None),
        ]
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM auth.users"))
        command.upgrade(alembic_config, "head")
