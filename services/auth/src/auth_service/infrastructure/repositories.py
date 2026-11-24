"""Repositorios y unidad de trabajo con SQLAlchemy.

Los repositorios devuelven entidades del dominio (dataclasses), no filas de SQLAlchemy: así el
dominio no depende de la base. Cada entidad entregada queda "rastreada" junto con su fila, y al
confirmar se copian sus cambios a la fila.
"""

from datetime import datetime
from typing import Self
from uuid import UUID, uuid4

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from auth_service.domain.errors import EmailAlreadyRegistered
from auth_service.domain.model import Session, User
from auth_service.infrastructure.db import LoginAttemptRow, SessionRow, UserRow

_USER_FIELDS = ("id", "email", "password_hash", "created_at")
_SESSION_FIELDS = (
    "id",
    "user_id",
    "device_id",
    "device_name",
    "refresh_token_hash",
    "previous_refresh_token_hash",
    "created_at",
    "last_used_at",
    "expires_at",
    "revoked_at",
)


class _Tracker:
    """Recuerda qué entidad corresponde a qué fila para copiar los cambios al confirmar."""

    def __init__(self, fields: tuple[str, ...]) -> None:
        self._fields = fields
        self._pairs: list[tuple[object, object]] = []

    def to_entity(self, entity_type: type, row: object):
        entity = entity_type(**{field: getattr(row, field) for field in self._fields})
        self._pairs.append((entity, row))
        return entity

    def to_row(self, row_type: type, entity: object):
        row = row_type(**{field: getattr(entity, field) for field in self._fields})
        self._pairs.append((entity, row))
        return row

    def sync(self) -> None:
        for entity, row in self._pairs:
            for field in self._fields:
                setattr(row, field, getattr(entity, field))


class SqlUserRepository:
    def __init__(self, db: OrmSession) -> None:
        self._db = db
        self._tracker = _Tracker(_USER_FIELDS)

    def get(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        row = self._db.get(UserRow, user_id, with_for_update=for_update)
        return None if row is None else self._tracker.to_entity(User, row)

    def get_by_email(self, email: str, *, for_update: bool = False) -> User | None:
        query = select(UserRow).where(UserRow.email == email)
        row = self._db.scalar(query.with_for_update() if for_update else query)
        return None if row is None else self._tracker.to_entity(User, row)

    def add(self, user: User) -> None:
        self._db.add(self._tracker.to_row(UserRow, user))

    def sync(self) -> None:
        self._tracker.sync()


class SqlSessionRepository:
    def __init__(self, db: OrmSession) -> None:
        self._db = db
        self._tracker = _Tracker(_SESSION_FIELDS)

    def add(self, session: Session) -> None:
        # Primero se escriben los cambios pendientes (por ejemplo, la revocación de la sesión
        # anterior del mismo dispositivo); si no, el índice único parcial rechazaría la nueva.
        self.sync()
        self._db.flush()
        self._db.add(self._tracker.to_row(SessionRow, session))

    def get(self, session_id: UUID) -> Session | None:
        row = self._db.get(SessionRow, session_id)
        return None if row is None else self._tracker.to_entity(Session, row)

    def get_by_refresh_hash(self, token_hash: str, *, for_update: bool = False) -> Session | None:
        return self._first(SessionRow.refresh_token_hash == token_hash, for_update=for_update)

    def get_by_previous_refresh_hash(self, token_hash: str) -> Session | None:
        return self._first(SessionRow.previous_refresh_token_hash == token_hash)

    def list_unrevoked_for_device(self, user_id: UUID, device_id: str) -> list[Session]:
        return self._all(
            SessionRow.user_id == user_id,
            SessionRow.device_id == device_id,
            SessionRow.revoked_at.is_(None),
        )

    def list_unrevoked_for_user(self, user_id: UUID) -> list[Session]:
        return self._all(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))

    def sync(self) -> None:
        self._tracker.sync()

    def _first(self, condition, *, for_update: bool = False) -> Session | None:
        query = select(SessionRow).where(condition)
        row = self._db.scalar(query.with_for_update() if for_update else query)
        return None if row is None else self._tracker.to_entity(Session, row)

    def _all(self, *conditions) -> list[Session]:
        rows = self._db.scalars(select(SessionRow).where(*conditions))
        return [self._tracker.to_entity(Session, row) for row in rows]


class SqlLoginAttemptRepository:
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def add_failure(self, email: str, at: datetime) -> None:
        self._db.add(LoginAttemptRow(id=uuid4(), email=email, attempted_at=at))

    def list_failures_since(self, email: str, since: datetime) -> list[datetime]:
        return list(
            self._db.scalars(
                select(LoginAttemptRow.attempted_at)
                .where(LoginAttemptRow.email == email, LoginAttemptRow.attempted_at > since)
                .order_by(LoginAttemptRow.attempted_at)
            )
        )

    def clear(self, email: str) -> None:
        self._db.execute(delete(LoginAttemptRow).where(LoginAttemptRow.email == email))


class SqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self._db = self._session_factory()
        self.users = SqlUserRepository(self._db)
        self.sessions = SqlSessionRepository(self._db)
        self.login_attempts = SqlLoginAttemptRepository(self._db)
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Lo que no se confirmó con commit() se descarta.
        self._db.rollback()
        self._db.close()

    def commit(self) -> None:
        self.users.sync()
        self.sessions.sync()
        try:
            self._db.commit()
        except IntegrityError as error:
            # Dos registros simultáneos con el mismo correo: el segundo choca con la restricción.
            if "uq_users_email" in str(error.orig):
                raise EmailAlreadyRegistered() from error
            raise
