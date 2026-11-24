from typing import Self
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from auth_service.domain.errors import EmailAlreadyRegistered
from auth_service.domain.model import Session, User
from auth_service.infrastructure.db import SessionRow, UserRow

_SESSION_FIELDS = (
    "id",
    "user_id",
    "device_id",
    "device_name",
    "refresh_token_hash",
    "created_at",
    "last_used_at",
    "expires_at",
    "revoked_at",
)


class SqlUserRepository:
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def get_by_email(self, email: str) -> User | None:
        row = self._db.scalar(select(UserRow).where(UserRow.email == email))
        if row is None:
            return None
        return User(
            id=row.id, email=row.email, password_hash=row.password_hash, created_at=row.created_at
        )

    def add(self, user: User) -> None:
        self._db.add(
            UserRow(
                id=user.id,
                email=user.email,
                password_hash=user.password_hash,
                created_at=user.created_at,
            )
        )


class SqlSessionRepository:
    """Devuelve entidades del dominio y, al confirmar, copia sus cambios a las filas."""

    def __init__(self, db: OrmSession) -> None:
        self._db = db
        self._tracked: list[tuple[Session, SessionRow]] = []

    def add(self, session: Session) -> None:
        # Primero se escriben los cambios pendientes (por ejemplo, la revocación de la sesión
        # anterior del mismo dispositivo); si no, el índice único parcial rechazaría la nueva.
        self.sync()
        self._db.flush()
        row = SessionRow(**{field: getattr(session, field) for field in _SESSION_FIELDS})
        self._db.add(row)
        self._tracked.append((session, row))

    def list_unrevoked_for_device(self, user_id: UUID, device_id: str) -> list[Session]:
        rows = self._db.scalars(
            select(SessionRow).where(
                SessionRow.user_id == user_id,
                SessionRow.device_id == device_id,
                SessionRow.revoked_at.is_(None),
            )
        )
        sessions = []
        for row in rows:
            session = Session(**{field: getattr(row, field) for field in _SESSION_FIELDS})
            self._tracked.append((session, row))
            sessions.append(session)
        return sessions

    def sync(self) -> None:
        for session, row in self._tracked:
            for field in _SESSION_FIELDS:
                setattr(row, field, getattr(session, field))


class SqlUnitOfWork:
    def __init__(self, session_factory: sessionmaker[OrmSession]) -> None:
        self._session_factory = session_factory

    def __enter__(self) -> Self:
        self._db = self._session_factory()
        self.users = SqlUserRepository(self._db)
        self.sessions = SqlSessionRepository(self._db)
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Lo que no se confirmó con commit() se descarta.
        self._db.rollback()
        self._db.close()

    def commit(self) -> None:
        self.sessions.sync()
        try:
            self._db.commit()
        except IntegrityError as error:
            # Dos registros simultáneos con el mismo correo: el segundo choca con la restricción.
            if "uq_users_email" in str(error.orig):
                raise EmailAlreadyRegistered() from error
            raise
