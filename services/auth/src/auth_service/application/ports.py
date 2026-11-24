"""Puertos: lo que los casos de uso necesitan del exterior, sin saber cómo se implementa."""

from datetime import datetime
from typing import Protocol, Self
from uuid import UUID

from auth_service.domain.model import Session, User


class Clock(Protocol):
    def now(self) -> datetime: ...


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...

    def verify(self, password_hash: str, password: str) -> bool: ...


class TokenService(Protocol):
    def issue_access_token(
        self, user_id: UUID, session_id: UUID, now: datetime
    ) -> tuple[str, datetime]: ...

    def new_refresh_token(self) -> str: ...

    def hash_refresh_token(self, token: str) -> str: ...


class UserRepository(Protocol):
    def get_by_email(self, email: str) -> User | None: ...

    def add(self, user: User) -> None: ...


class SessionRepository(Protocol):
    def add(self, session: Session) -> None: ...

    def list_unrevoked_for_device(self, user_id: UUID, device_id: str) -> list[Session]: ...


class UnitOfWork(Protocol):
    """Una transacción: todo lo que se hace dentro se confirma junto con commit() o nada."""

    users: UserRepository
    sessions: SessionRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def commit(self) -> None: ...
