from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import (
    CHAR,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    UniqueConstraint,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.orm import Session as OrmSession

SCHEMA = "auth"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class UserRow(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))


class SessionRow(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("refresh_token_hash", name="uq_sessions_refresh_token_hash"),
        Index("ix_auth_sessions_user_id", "user_id"),
        Index("ix_auth_sessions_previous_refresh_token_hash", "previous_refresh_token_hash"),
        # Como máximo una sesión sin revocar por dispositivo de cada usuario.
        Index(
            "uq_sessions_user_device_unrevoked",
            "user_id",
            "device_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"))
    device_id: Mapped[str] = mapped_column(String(100))
    device_name: Mapped[str] = mapped_column(String(100))
    refresh_token_hash: Mapped[str] = mapped_column(CHAR(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    previous_refresh_token_hash: Mapped[str | None] = mapped_column(CHAR(64))


class LoginAttemptRow(Base):
    """Inicios de sesión fallidos, para el límite de intentos por correo."""

    __tablename__ = "login_attempts"
    __table_args__ = (Index("ix_auth_login_attempts_email_attempted_at", "email", "attempted_at"),)

    id: Mapped[UUID] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254))
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def include_auth_schema(name: str | None, type_: str, parent_names: dict) -> bool:
    """Filtro para Alembic: este servicio solo administra su propio esquema."""
    return name == SCHEMA if type_ == "schema" else True


def build_session_factory(database_url: str) -> sessionmaker[OrmSession]:
    engine: Engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(engine, expire_on_commit=False)


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
