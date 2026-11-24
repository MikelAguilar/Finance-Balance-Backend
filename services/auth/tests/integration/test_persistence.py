"""Repositorios, restricciones de la base y migraciones contra PostgreSQL real."""

from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.exc import IntegrityError

from auth_service.domain.errors import EmailAlreadyRegistered
from auth_service.domain.model import Session, User
from auth_service.infrastructure.db import Base, build_session_factory, include_auth_schema
from auth_service.infrastructure.repositories import SqlUnitOfWork

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def uow_factory(settings):
    return partial(SqlUnitOfWork, build_session_factory(settings.database_url))


def new_user(email="luis@example.com") -> User:
    return User(id=uuid4(), email=email, password_hash="hash", created_at=NOW)


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


def test_el_usuario_guardado_se_recupera_igual(uow_factory) -> None:
    user = new_user()
    with uow_factory() as uow:
        uow.users.add(user)
        uow.commit()

    with uow_factory() as uow:
        assert uow.users.get_by_email("luis@example.com") == user


def test_sin_commit_no_se_guarda_nada(uow_factory) -> None:
    with uow_factory() as uow:
        uow.users.add(new_user())

    with uow_factory() as uow:
        assert uow.users.get_by_email("luis@example.com") is None


def test_correo_duplicado_en_carrera_se_traduce_a_error_del_dominio(uow_factory) -> None:
    # Simula dos registros simultáneos: los dos pasaron la verificación previa.
    with uow_factory() as uow:
        uow.users.add(new_user())
        uow.commit()

    with uow_factory() as uow, pytest.raises(EmailAlreadyRegistered):
        uow.users.add(new_user())
        uow.commit()


def test_la_base_impide_dos_sesiones_sin_revocar_en_el_mismo_dispositivo(uow_factory) -> None:
    user = new_user()
    with uow_factory() as uow:
        uow.users.add(user)
        uow.sessions.add(new_session(user.id))
        uow.commit()

    with uow_factory() as uow, pytest.raises(IntegrityError):
        uow.sessions.add(new_session(user.id))
        uow.commit()


def test_revocar_y_crear_en_la_misma_transaccion_funciona(uow_factory) -> None:
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


def test_los_modelos_coinciden_con_las_migraciones(engine) -> None:
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection,
            opts={"include_schemas": True, "include_name": include_auth_schema},
        )
        assert compare_metadata(context, Base.metadata) == []


def test_las_migraciones_se_pueden_revertir_y_reaplicar(alembic_config, engine) -> None:
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
