"""Los datos de finanzas en PostgreSQL. Cada fila se convierte en su entidad del dominio, que se
valida al construirse: una fila que rompiera las reglas fallaría aquí y no llegaría a la app."""

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import asdict
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import sessionmaker

from finance_service.application.ports import Existing, Table, Write
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
    kind_name,
)
from finance_service.domain.sync import Current
from finance_service.infrastructure.db import CardRow, MonthlyIncomeRow, MovementRow, SyncColumns

# Candado de PostgreSQL por cuenta. En SQL las mayúsculas no importan: el mutante "select" es
# equivalente.
LOCK_ACCOUNT = "SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"  # pragma: no mutate
# La secuencia del número de cambio. PostgreSQL pasa a minúsculas los nombres sin comillas: el
# mutante en mayúsculas es equivalente.
CHANGE_SEQ = "finance.change_seq"  # pragma: no mutate


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


# --- Del dominio a la fila -----------------------------------------------------------------------


def card_values(card: Card) -> dict[str, Any]:
    return asdict(card)


def movement_values(value: CardMovement) -> dict[str, Any]:
    movement = value.movement
    kind = movement.kind
    return {
        "card_id": value.card_id,
        "amount_cents": movement.amount_cents,
        "occurred_at": movement.occurred.at,
        "occurred_offset_minutes": movement.occurred.offset_minutes,
        "kind": kind_name(kind),
        "months": kind.months if isinstance(kind, Installment) else None,
        "monthly_rate": kind.monthly_rate if isinstance(kind, Installment) else None,
        "payment_source": kind.source.value if isinstance(kind, Payment) else None,
        "review_status": movement.review_status.value,
        "owner_cut": movement.owner_cut,
    }


def income_values(income: MonthlyIncome) -> dict[str, Any]:
    return asdict(income)


# Cada tabla: su modelo, cómo se lee una fila y qué columnas escribe su entidad.
TABLES: dict[
    Table, tuple[type[SyncColumns], Callable[[Any], Stored[Any]], Callable[[Any], dict]]
] = {
    Table.CARDS: (CardRow, card_from, card_values),
    Table.MOVEMENTS: (MovementRow, movement_from, movement_values),
    Table.INCOMES: (MonthlyIncomeRow, income_from, income_values),
}


def existing_from(row: SyncColumns, read: Callable[[Any], Stored[Any]]) -> Existing[Any]:
    current = Current(
        version=row.version, updated_at=row.updated_at, last_change_id=row.last_change_id
    )
    return Existing(stored=read(row), current=current)


def stamp(write: Write[Any]) -> dict[str, Any]:
    return {
        "updated_at": write.updated_at,
        "server_updated_at": write.now,
        "last_change_id": write.change_id,
    }


class SqlSyncStore:
    def __init__(self, db: OrmSession, new_id: Callable[[], UUID] = uuid4) -> None:
        self._db = db
        # El servidor asigna los ids; las pruebas de contrato los fijan para comparar.
        self._new_id = new_id

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

    # --- Escrituras de la subida -----------------------------------------------------------------

    def find(
        self, table: Table, user_id: UUID, *, id: UUID | None = None, key: UUID | None = None
    ) -> Existing[Any] | None:
        model, read, _ = TABLES[table]
        column = model.id if id is not None else model.idempotency_key
        query = select(model).where(model.user_id == user_id, column == (id or key))
        row = self._db.scalars(query).one_or_none()
        return None if row is None else existing_from(row, read)

    def current_income(self, user_id: UUID) -> Existing[MonthlyIncome] | None:
        query = select(MonthlyIncomeRow).where(
            MonthlyIncomeRow.user_id == user_id, MonthlyIncomeRow.deleted_at.is_(None)
        )
        row = self._db.scalars(query).one_or_none()
        return None if row is None else existing_from(row, income_from)

    def create(self, table: Table, user_id: UUID, key: UUID, write: Write[Any]) -> Stored[Any]:
        model, read, values = TABLES[table]
        row = model(
            id=self._new_id(),
            user_id=user_id,
            idempotency_key=key,
            version=1,
            **values(write.value),
            **stamp(write),
        )
        self._db.add(row)
        self._db.flush()
        return read(row)

    def update(self, table: Table, id: UUID, version: int, write: Write[Any]) -> Stored[Any]:
        model, read, values = TABLES[table]
        # find ya comprobó que el registro es de la cuenta; el id es la llave primaria.
        row = self._db.get_one(model, id)
        for column, value in {**values(write.value), **stamp(write)}.items():
            setattr(row, column, value)
        row.version = version
        # Cada escritura toma el siguiente número de cambio: así baja en la próxima descarga.
        row.change_seq = func.nextval(CHANGE_SEQ)
        self._db.flush()
        return read(row)


def sql_store(
    session_factory: sessionmaker[OrmSession], new_id: Callable[[], UUID] = uuid4
) -> Callable[[], AbstractContextManager[SqlSyncStore]]:
    """Abre un SqlSyncStore dentro de una transacción; al salir se confirma o se deshace."""

    @contextmanager
    def open_store() -> Iterator[SqlSyncStore]:
        with session_factory() as db, db.begin():
            yield SqlSyncStore(db, new_id)

    return open_store
