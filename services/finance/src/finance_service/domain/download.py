"""Descarga por páginas: lo que cambió en el servidor después del cursor de la app."""

from dataclasses import dataclass
from heapq import merge
from uuid import UUID

from finance_service.domain.model import Card, MonthlyIncome, Movement


@dataclass(frozen=True)
class Stored[T]:
    """Un registro como está en el servidor.

    `key` es la clave que generó la app al crearlo (así reconoce lo que creó sin red), `version`
    la versión sobre la que editará y `seq` su número de cambio.
    """

    id: UUID
    key: UUID
    version: int
    seq: int
    value: T


@dataclass(frozen=True)
class CardMovement:
    card_id: UUID
    movement: Movement


@dataclass(frozen=True)
class Page:
    cards: list[Stored[Card]]
    movements: list[Stored[CardMovement]]
    incomes: list[Stored[MonthlyIncome]]
    cursor: int
    has_more: bool


def cut_page(
    cards: list[Stored[Card]],
    movements: list[Stored[CardMovement]],
    incomes: list[Stored[MonthlyIncome]],
    *,
    after: int,
    limit: int,
) -> Page:
    """Toma los `limit` cambios más viejos de las tres tablas, en orden de número de cambio.

    Cada lista llega ordenada y con hasta `limit + 1` registros: si en total sobra alguno,
    quedan más páginas.
    """
    taken = list(merge(cards, movements, incomes, key=lambda record: record.seq))
    # La página son justo los cambios hasta su último número: los demás quedan para la siguiente.
    cursor = taken[:limit][-1].seq if taken else after
    return Page(
        cards=[record for record in cards if record.seq <= cursor],
        movements=[record for record in movements if record.seq <= cursor],
        incomes=[record for record in incomes if record.seq <= cursor],
        cursor=cursor,
        has_more=len(taken) > limit,
    )


def missing_cards(page: Page) -> set[UUID]:
    """Las tarjetas de los movimientos de la página que no vienen en ella."""
    in_page = {card.id for card in page.cards}
    return {record.value.card_id for record in page.movements} - in_page
