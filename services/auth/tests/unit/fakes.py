"""Dobles de prueba en memoria para los puertos de la capa de aplicación."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from auth_service.domain.errors import InvalidToken
from auth_service.domain.model import Session, User


class FakeClock:
    def __init__(self, now: datetime = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> None:
        self.current += delta


class FakeHasher:
    """Hash reversible y evidente: suficiente para probar la lógica, no para producción."""

    def __init__(self) -> None:
        self.verified: list[tuple[str, str]] = []

    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password_hash: str, password: str) -> bool:
        self.verified.append((password_hash, password))
        return password_hash == f"hashed:{password}"


class FakeTokens:
    """Tokens legibles: «access:<usuario>:<sesión>:<vencimiento>»."""

    def __init__(self) -> None:
        self._counter = 0

    def issue_access_token(
        self, user_id: UUID, session_id: UUID, now: datetime
    ) -> tuple[str, datetime]:
        expires_at = now + timedelta(minutes=15)
        return f"access:{user_id}:{session_id}:{expires_at.timestamp()}", expires_at

    def decode_access_token(self, token: str, now: datetime) -> tuple[UUID, UUID]:
        try:
            kind, user_id, session_id, expires = token.split(":")
            if kind != "access" or float(expires) <= now.timestamp():
                raise InvalidToken()
            return UUID(user_id), UUID(session_id)
        except ValueError as error:
            raise InvalidToken() from error

    def new_refresh_token(self) -> str:
        self._counter += 1
        return f"refresh-{self._counter}"

    def hash_refresh_token(self, token: str) -> str:
        return f"sha:{token}"


class FakeUsers:
    """Como la base: las cuentas eliminadas siguen guardadas, pero `get` no las devuelve."""

    def __init__(self) -> None:
        self.items: list[User] = []

    def get(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        return next((u for u in self.items if u.id == user_id and u.deleted_at is None), None)

    def get_by_email(self, email: str, *, for_update: bool = False) -> User | None:
        return next((u for u in self.items if u.email == email and u.deleted_at is None), None)

    def add(self, user: User) -> None:
        self.items.append(user)


class FakeSessions:
    def __init__(self) -> None:
        self.items: list[Session] = []

    def add(self, session: Session) -> None:
        self.items.append(session)

    def get(self, session_id: UUID, *, for_update: bool = False) -> Session | None:
        return next((s for s in self.items if s.id == session_id), None)

    def get_by_refresh_hash(self, token_hash: str, *, for_update: bool = False) -> Session | None:
        return next((s for s in self.items if s.refresh_token_hash == token_hash), None)

    def get_by_previous_refresh_hash(self, token_hash: str) -> Session | None:
        return next((s for s in self.items if s.previous_refresh_token_hash == token_hash), None)

    def list_unrevoked_for_device(self, user_id: UUID, device_id: str) -> list[Session]:
        return [
            s
            for s in self.items
            if s.user_id == user_id and s.device_id == device_id and s.revoked_at is None
        ]

    def list_unrevoked_for_user(self, user_id: UUID) -> list[Session]:
        return [s for s in self.items if s.user_id == user_id and s.revoked_at is None]


class FakeLoginAttempts:
    def __init__(self) -> None:
        self.failures: list[tuple[str, datetime]] = []

    def add_failure(self, email: str, at: datetime) -> None:
        self.failures.append((email, at))

    def list_failures_since(self, email: str, since: datetime) -> list[datetime]:
        return sorted(at for e, at in self.failures if e == email and at > since)

    def clear(self, email: str) -> None:
        self.failures = [(e, at) for e, at in self.failures if e != email]


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.users = FakeUsers()
        self.sessions = FakeSessions()
        self.login_attempts = FakeLoginAttempts()
        self.commits = 0

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1
