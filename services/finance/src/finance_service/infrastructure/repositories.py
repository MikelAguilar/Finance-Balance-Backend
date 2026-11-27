"""Los datos de finanzas en PostgreSQL. Cada fila se convierte en su entidad del dominio, que se
valida al construirse: una fila que rompiera las reglas fallaría aquí y no llegaría a la app."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from uuid import UUID

from sqlalchemy import Select, select, text
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from finance_service.domain.download import CardMovement, Stored
from finance_service.domain.model import (
    Card,
    Installment,
    KindName,
    MonthlyIncome,
    Movement,
    MovementKind,
    Normal,
    OccurredAt,
    Payment,
    PaymentSource,
    ReviewStatus,
)
from finance_service.infrastructure.db import CardRow, MonthlyIncomeRow, MovementRow, SyncColumns

# Candado de PostgreSQL por cuenta. En SQL las mayúsculas no importan: el mutante "select" es
# equivalente.
LOCK_ACCOUNT = "SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"  # pragma: no mutate


def stored[T](row: SyncColumns, value: T) -> Stored[T]:
    return Stored(
        id=row.id, key=row.idempotency_key, version=row.version, seq=row.change_seq, value=value
    )


def card_from(row: CardRow) -> Stored[Card]:
    card = Card(
        name=row.name,
        cut_day=row.cut_day,
        personal_limit_cents=row.personal_limit_cents,
        bank_limit_cents=row.bank_limit_cents,
        used_at_creation_cents=row.used_at_creation_cents,
        installments_count_against_limit=row.installments_count_against_limit,
    )
    return stored(row, card)


def kind_from(row: MovementRow) -> MovementKind:
    name = KindName(row.kind)
    if name is KindName.INSTALLMENT:
        return Installment(months=row.months, monthly_rate=row.monthly_rate)
    if name is KindName.PAYMENT:
        return Payment(source=PaymentSource(row.payment_source))
    return Normal()


def movement_from(row: MovementRow) -> Stored[CardMovement]:
    movement = Movement(
        amount_cents=row.amount_cents,
        occurred=OccurredAt(at=row.occurred_at, offset_minutes=row.occurred_offset_minutes),
        kind=kind_from(row),
        review_status=ReviewStatus(row.review_status),
        owner_cut=row.owner_cut,
    )
    return stored(row, CardMovement(card_id=row.card_id, movement=movement))


def income_from(row: MonthlyIncomeRow) -> Stored[MonthlyIncome]:
    return stored(row, MonthlyIncome(amount_cents=row.amount_cents))


class SqlSyncStore:
    def __init__(self, db: OrmSession) -> None:
        self._db = db

    def lock_account(self, user_id: UUID) -> None:
        # Candado de PostgreSQL por cuenta que se suelta solo al terminar la transacción. Dos
        # cuentas con el mismo hash solo se esperan entre sí: nunca se mezclan sus datos.
        self._db.execute(text(LOCK_ACCOUNT), {"user_id": str(user_id)})

    def _changed[R: SyncColumns](
        self, model: type[R], user_id: UUID, after: int
    ) -> Select[tuple[R]]:
        return (
            select(model)
            .where(model.user_id == user_id, model.change_seq > after)
            .order_by(model.change_seq)
        )

    def cards_changed(self, user_id: UUID, after: int, limit: int) -> list[Stored[Card]]:
        rows = self._db.scalars(self._changed(CardRow, user_id, after).limit(limit))
        return [card_from(row) for row in rows]

    def movements_changed(
        self, user_id: UUID, after: int, limit: int
    ) -> list[Stored[CardMovement]]:
        rows = self._db.scalars(self._changed(MovementRow, user_id, after).limit(limit))
        return [movement_from(row) for row in rows]

    def incomes_changed(self, user_id: UUID, after: int, limit: int) -> list[Stored[MonthlyIncome]]:
        rows = self._db.scalars(self._changed(MonthlyIncomeRow, user_id, after).limit(limit))
        return [income_from(row) for row in rows]

    def cards_changed_among(self, user_id: UUID, ids: set[UUID], after: int) -> list[Stored[Card]]:
        rows = self._db.scalars(self._changed(CardRow, user_id, after).where(CardRow.id.in_(ids)))
        return [card_from(row) for row in rows]


def sql_store(
    session_factory: sessionmaker[OrmSession],
) -> Callable[[], AbstractContextManager[SqlSyncStore]]:
    """Abre un SqlSyncStore dentro de una transacción; al salir se confirma o se deshace."""

    @contextmanager
    def open_store() -> Iterator[SqlSyncStore]:
        with session_factory() as db, db.begin():
            yield SqlSyncStore(db)

    return open_store
