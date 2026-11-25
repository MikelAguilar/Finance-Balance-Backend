from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
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


# Cada tipo lleva solo sus campos, y los lleva todos. Los IS NOT NULL no sobran: en un CHECK,
# una comparación con NULL da NULL, y PostgreSQL deja pasar el NULL.
MOVEMENT_KIND_RULE = """
(kind = 'normal' AND months IS NULL AND monthly_rate IS NULL AND payment_source IS NULL)
OR (kind = 'installment' AND months IS NOT NULL AND monthly_rate IS NOT NULL
    AND months BETWEEN 1 AND 120 AND monthly_rate >= 0 AND monthly_rate < 1
    AND payment_source IS NULL)
OR (kind = 'payment' AND months IS NULL AND monthly_rate IS NULL
    AND payment_source IS NOT NULL AND payment_source IN ('debit', 'cash'))
"""


class MovementRow(SyncColumns, Base):
    __tablename__ = "movements"
    __table_args__ = (
        *sync_constraints("movements"),
        ForeignKeyConstraint(
            ["card_id", "user_id"],
            [f"{SCHEMA}.cards.id", f"{SCHEMA}.cards.user_id"],
            name="fk_movements_card",
        ),
        CheckConstraint("amount_cents > 0", name="ck_movements_amount"),
        CheckConstraint(
            "occurred_offset_minutes BETWEEN -720 AND 840", name="ck_movements_occurred_offset"
        ),
        CheckConstraint(MOVEMENT_KIND_RULE, name="ck_movements_kind"),
        CheckConstraint(
            "review_status IN ('pending_review', 'confirmed')", name="ck_movements_review_status"
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
        *sync_constraints("monthly_income"),
        CheckConstraint("amount_cents > 0", name="ck_monthly_income_amount"),
        # Un ingreso vigente por cuenta; los anteriores se conservan con deleted_at.
        Index(
            "uq_monthly_income_user_current",
            "user_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    amount_cents: Mapped[int] = mapped_column(BigInteger)


def include_finance_schema(name: str | None, type_: str, parent_names: dict) -> bool:
    """Filtro para Alembic: este servicio solo administra su propio esquema."""
    return name == SCHEMA if type_ == "schema" else True
