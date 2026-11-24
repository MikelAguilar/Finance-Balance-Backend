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

    def decode_access_token(self, token: str, now: datetime) -> tuple[UUID, UUID]:
        """Devuelve (usuario, sesión) o lanza InvalidToken."""
        ...

    def new_refresh_token(self) -> str: ...

    def hash_refresh_token(self, token: str) -> str: ...


class UserRepository(Protocol):
    def get(self, user_id: UUID) -> User | None: ...

    def get_by_email(self, email: str) -> User | None: ...

    def add(self, user: User) -> None: ...


class SessionRepository(Protocol):
    def add(self, session: Session) -> None: ...

    def get(self, session_id: UUID) -> Session | None: ...

    def get_by_refresh_hash(self, token_hash: str) -> Session | None: ...

    def get_by_previous_refresh_hash(self, token_hash: str) -> Session | None: ...

    def list_unrevoked_for_device(self, user_id: UUID, device_id: str) -> list[Session]: ...

    def list_unrevoked_for_user(self, user_id: UUID) -> list[Session]: ...


class LoginAttemptRepository(Protocol):
    def add_failure(self, email: str, at: datetime) -> None: ...

    def list_failures_since(self, email: str, since: datetime) -> list[datetime]:
        """Fechas de los fallos posteriores a `since`, de la más antigua a la más reciente."""
        ...

    def clear(self, email: str) -> None: ...


class UnitOfWork(Protocol):
    """Una transacción: todo lo que se hace dentro se confirma junto con commit() o nada."""

    users: UserRepository
    sessions: SessionRepository
    login_attempts: LoginAttemptRepository

    def __enter__(self) -> Self: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def commit(self) -> None: ...
