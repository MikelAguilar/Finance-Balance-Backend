"""Dobles de prueba en memoria para los puertos de la capa de aplicación."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

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
    def __init__(self) -> None:
        self._counter = 0

    def issue_access_token(
        self, user_id: UUID, session_id: UUID, now: datetime
    ) -> tuple[str, datetime]:
        return f"access:{user_id}:{session_id}", now + timedelta(minutes=15)

    def new_refresh_token(self) -> str:
        self._counter += 1
        return f"refresh-{self._counter}"

    def hash_refresh_token(self, token: str) -> str:
        return f"sha:{token}"


class FakeUsers:
    def __init__(self) -> None:
        self.by_email: dict[str, User] = {}

    def get_by_email(self, email: str) -> User | None:
        return self.by_email.get(email)

    def add(self, user: User) -> None:
        self.by_email[user.email] = user


class FakeSessions:
    def __init__(self) -> None:
        self.items: list[Session] = []

    def add(self, session: Session) -> None:
        self.items.append(session)

    def list_unrevoked_for_device(self, user_id: UUID, device_id: str) -> list[Session]:
        return [
            s
            for s in self.items
            if s.user_id == user_id and s.device_id == device_id and s.revoked_at is None
        ]


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.users = FakeUsers()
        self.sessions = FakeSessions()
        self.commits = 0

    def __enter__(self) -> "FakeUnitOfWork":
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1
