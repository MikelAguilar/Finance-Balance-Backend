from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "finance"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


class SyncColumns:
    """Columnas que lleva todo registro que se sincroniza con la app.

    - El servidor asigna `id`; la app identifica un registro nuevo con `idempotency_key`.
    - `version` sube con cada cambio aplicado: si la app editó otra versión, hubo un choque.
    - `updated_at` es la hora de edición del teléfono (corregida); solo desempata choques.
    - `server_updated_at` lo pone el servidor. `deleted_at` es el borrado lógico: nada se borra.
    - Sin llave foránea a auth.users: cada servicio es dueño de su esquema.
    """

    id: Mapped[UUID] = mapped_column(primary_key=True)
    user_id: Mapped[UUID]
    idempotency_key: Mapped[UUID]
    version: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    server_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def sync_constraints(table: str) -> tuple:
    return (
        UniqueConstraint("user_id", "idempotency_key", name=f"uq_{table}_user_idempotency_key"),
        CheckConstraint("version >= 1", name=f"ck_{table}_version"),
    )


class CardRow(SyncColumns, Base):
    __tablename__ = "cards"
    __table_args__ = (
        *sync_constraints("cards"),
        CheckConstraint("length(btrim(name)) > 0", name="ck_cards_name"),
        CheckConstraint("cut_day BETWEEN 1 AND 31", name="ck_cards_cut_day"),
        CheckConstraint("personal_limit_cents > 0", name="ck_cards_personal_limit"),
        CheckConstraint("bank_limit_cents > 0", name="ck_cards_bank_limit"),
        CheckConstraint(
            "personal_limit_cents IS NOT NULL OR bank_limit_cents IS NOT NULL",
            name="ck_cards_at_least_one_limit",
        ),
        CheckConstraint("used_at_creation_cents >= 0", name="ck_cards_used_at_creation"),
    )

    name: Mapped[str] = mapped_column(String(50))
    cut_day: Mapped[int] = mapped_column(SmallInteger)
    personal_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    bank_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    used_at_creation_cents: Mapped[int] = mapped_column(BigInteger)
    installments_count_against_limit: Mapped[bool] = mapped_column(Boolean)


def include_finance_schema(name: str | None, type_: str, parent_names: dict) -> bool:
    """Filtro para Alembic: este servicio solo administra su propio esquema."""
    return name == SCHEMA if type_ == "schema" else True
