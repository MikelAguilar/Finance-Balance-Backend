from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA = "finance"


class Base(DeclarativeBase):
    metadata = MetaData(schema=SCHEMA)


# Los CHECK con las reglas de entrada viven solo en las migraciones: las pruebas de integración los
# prueban contra PostgreSQL, y Alembic no compara su texto con estos modelos (repetirlos aquí sería
# una segunda copia que nadie verifica).


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


def unique_idempotency_key(table: str) -> UniqueConstraint:
    return UniqueConstraint("user_id", "idempotency_key", name=f"uq_{table}_user_idempotency_key")


class CardRow(SyncColumns, Base):
    __tablename__ = "cards"
    __table_args__ = (
        unique_idempotency_key("cards"),
        # Destino de la llave foránea de movements: un movimiento solo apunta a una tarjeta de
        # su misma cuenta.
        UniqueConstraint("id", "user_id", name="uq_cards_id_user"),
    )

    name: Mapped[str] = mapped_column(String(50))
    cut_day: Mapped[int] = mapped_column(SmallInteger)
    personal_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    bank_limit_cents: Mapped[int | None] = mapped_column(BigInteger)
    used_at_creation_cents: Mapped[int] = mapped_column(BigInteger)
    installments_count_against_limit: Mapped[bool] = mapped_column(Boolean)


class MovementRow(SyncColumns, Base):
    __tablename__ = "movements"
    __table_args__ = (
        unique_idempotency_key("movements"),
        ForeignKeyConstraint(
            ["card_id", "user_id"],
            [f"{SCHEMA}.cards.id", f"{SCHEMA}.cards.user_id"],
            name="fk_movements_card",
        ),
    )

    card_id: Mapped[UUID]
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    # timestamptz descarta el offset: por eso se guarda aparte.
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurred_offset_minutes: Mapped[int] = mapped_column(SmallInteger)
    kind: Mapped[str] = mapped_column(String(11))
    months: Mapped[int | None] = mapped_column(SmallInteger)
    monthly_rate: Mapped[Decimal | None] = mapped_column(Numeric(7, 6))
    payment_source: Mapped[str | None] = mapped_column(String(5))
    review_status: Mapped[str] = mapped_column(String(14))
    owner_cut: Mapped[date] = mapped_column(Date)


class MonthlyIncomeRow(SyncColumns, Base):
    __tablename__ = "monthly_income"
    __table_args__ = (
        unique_idempotency_key("monthly_income"),
        # Un ingreso vigente por cuenta; los anteriores se conservan con deleted_at. Alembic no
        # compara la condición de un índice parcial: la que vale es la de la migración, probada
        # en test_monthly_income_table.
        Index(
            "uq_monthly_income_user_current",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),  # pragma: no mutate
        ),
    )

    amount_cents: Mapped[int] = mapped_column(BigInteger)


def include_finance_schema(name: str | None, type_: str, parent_names: dict) -> bool:
    """Filtro para Alembic: este servicio solo administra su propio esquema."""
    return name == SCHEMA if type_ == "schema" else True
