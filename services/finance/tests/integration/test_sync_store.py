"""Lo que promete SqlSyncStore: lo de la cuenta después del cursor, en orden y hasta `limit`."""

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from finance_service.infrastructure.repositories import SqlSyncStore


@pytest.fixture
def store(engine) -> Iterator[SqlSyncStore]:
    # Sin índices, PostgreSQL lee la tabla en el orden en que se guardó: el orden de la respuesta
    # no puede depender del plan de la consulta.
    with sessionmaker(engine)() as db, db.begin():
        db.execute(text("SET LOCAL enable_indexscan = off"))
        db.execute(text("SET LOCAL enable_bitmapscan = off"))
        yield SqlSyncStore(db)


# Números de cambio a propósito al revés del orden en que se insertan: la base no los devuelve
# ordenados por casualidad.
SEQS = [30, 20, 10]
REPLACED = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.fixture
def three_of_each(insert, make_card, make_movement, make_income) -> UUID:
    user = uuid4()
    cards = [make_card(user_id=user, change_seq=seq) for seq in SEQS]
    for card in cards:
        insert("cards", card)
    for seq in SEQS:
        insert("movements", make_movement(cards[0], change_seq=seq + 1))
        # Solo hay un ingreso vigente: los demás son anteriores, ya reemplazados.
        insert("monthly_income", make_income(user_id=user, change_seq=seq + 2, deleted_at=REPLACED))
    return user


@pytest.mark.parametrize(
    ("method", "offset"),
    [("cards_changed", 0), ("movements_changed", 1), ("incomes_changed", 2)],
)
def test_changes_come_in_order_and_up_to_the_limit(store, three_of_each, method, offset) -> None:
    changed = getattr(store, method)

    assert [record.seq for record in changed(three_of_each, 0, 2)] == [10 + offset, 20 + offset]
    assert [record.seq for record in changed(three_of_each, 10 + offset, 5)] == [
        20 + offset,
        30 + offset,
    ]
