"""Nada vivo se borra de la base. Solo la limpieza manual de Luis (después de un respaldo) puede
eliminar filas, y únicamente las que ya tienen deleted_at."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

DELETED = datetime(2026, 9, 1, tzinfo=UTC)


@pytest.fixture
def rows(insert, make_card, make_movement, make_income):
    """Una fila de cada tabla, todas vivas o todas ya borradas."""

    def _rows(deleted_at: datetime | None) -> dict[str, dict]:
        card = make_card(deleted_at=deleted_at)
        made = {
            "cards": card,
            "movements": make_movement(card, deleted_at=deleted_at),
            "monthly_income": make_income(deleted_at=deleted_at),
        }
        for table, row in made.items():
            insert(table, row)
        return made

    return _rows


def delete(engine, table: str, row: dict) -> None:
    with engine.begin() as connection:
        connection.execute(text(f"DELETE FROM finance.{table} WHERE id = :id"), {"id": row["id"]})


def remaining(engine, table: str, row: dict) -> int:
    with engine.connect() as connection:
        query = text(f"SELECT count(*) FROM finance.{table} WHERE id = :id")
        return connection.execute(query, {"id": row["id"]}).scalar_one()


@pytest.mark.parametrize("table", ["movements", "cards", "monthly_income"])
def test_a_live_row_cannot_be_deleted(engine, rows, table) -> None:
    row = rows(None)[table]
    with pytest.raises(DBAPIError, match="deleted_at"):
        delete(engine, table, row)
    assert remaining(engine, table, row) == 1


@pytest.mark.parametrize("table", ["movements", "cards", "monthly_income"])
def test_a_row_already_marked_as_deleted_can_be_cleaned_up(engine, rows, table) -> None:
    made = rows(DELETED)
    if table == "cards":
        delete(engine, "movements", made["movements"])
    delete(engine, table, made[table])
    assert remaining(engine, table, made[table]) == 0


def test_a_deleted_card_with_live_movements_cannot_be_cleaned_up(
    engine, insert, make_card, make_movement
) -> None:
    # Borrar una tarjeta no toca sus movimientos; mientras alguno siga vivo, la tarjeta se queda.
    card = make_card(deleted_at=DELETED)
    insert("cards", card)
    insert("movements", make_movement(card))
    with pytest.raises(DBAPIError, match="fk_movements_card"):
        delete(engine, "cards", card)
    assert remaining(engine, "cards", card) == 1
