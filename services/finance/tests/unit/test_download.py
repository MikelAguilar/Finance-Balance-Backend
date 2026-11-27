from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from finance_service.domain.download import (
    CardMovement,
    Page,
    Stored,
    cut_page,
    missing_cards,
)
from finance_service.domain.errors import InvalidField
from finance_service.domain.model import MAX_CENTS
from finance_service.domain.sync import parse_sync_request

NOW = datetime(2026, 11, 26, tzinfo=UTC)


def stored(seq: int, value: object = None, id: UUID | None = None) -> Stored:
    return Stored(id=id or uuid4(), key=uuid4(), version=1, seq=seq, value=value)


def on_card(seq: int, card_id: UUID) -> Stored:
    return stored(seq, CardMovement(card_id=card_id, movement=None))


# --- La petición ---------------------------------------------------------------------------------


def test_the_app_says_from_which_change_it_wants_to_download() -> None:
    assert parse_sync_request({"cursor": 0}, NOW).cursor == 0
    assert parse_sync_request({"cursor": 41}, NOW).cursor == 41
    assert parse_sync_request({"cursor": MAX_CENTS}, NOW).cursor == MAX_CENTS


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({}, ("cursor", "required")),
        ({"cursor": -1}, ("cursor", "range")),
        ({"cursor": MAX_CENTS + 1}, ("cursor", "range")),
        ({"cursor": "3"}, ("cursor", "type")),
        ({"cursor": True}, ("cursor", "type")),
        ({"cursor": 0, "accounts": {}}, ("accounts", "unknown")),
        ([], ("body", "type")),
        ("cursor", ("body", "type")),
    ],
)
def test_an_invalid_request_names_the_field_and_the_rule(data: object, expected: tuple) -> None:
    with pytest.raises(InvalidField) as error:
        parse_sync_request(data, NOW)
    assert (error.value.field, error.value.rule) == expected


# --- La página -----------------------------------------------------------------------------------


def test_nothing_changed_keeps_the_cursor_where_it_was() -> None:
    assert cut_page([], [], [], after=17, limit=3) == Page([], [], [], cursor=17, has_more=False)


def test_a_page_takes_the_oldest_changes_of_all_tables_in_order() -> None:
    cards = [stored(2), stored(6)]
    movements = [stored(3), stored(5)]
    incomes = [stored(4)]

    page = cut_page(cards, movements, incomes, after=1, limit=3)

    assert page == Page(cards[:1], movements[:1], incomes, cursor=4, has_more=True)


def test_the_last_page_says_there_is_nothing_more() -> None:
    cards, movements, incomes = [stored(2)], [stored(3)], [stored(4)]

    page = cut_page(cards, movements, incomes, after=1, limit=3)

    assert page == Page(cards, movements, incomes, cursor=4, has_more=False)


def test_a_page_that_ends_on_a_card_can_still_have_more_movements() -> None:
    # Cada tabla llega con un registro de más: así se sabe si queda algo después de la página.
    cards = [stored(2), stored(3)]
    movements = [stored(4)]

    page = cut_page(cards, movements, [], after=1, limit=2)

    assert page == Page(cards, [], [], cursor=3, has_more=True)


def test_cards_of_the_page_movements_that_were_not_sent_are_missing() -> None:
    sent, in_page, later = uuid4(), uuid4(), uuid4()
    page = Page(
        cards=[stored(5, id=in_page)],
        movements=[on_card(6, sent), on_card(7, in_page), on_card(8, later), on_card(9, later)],
        incomes=[],
        cursor=9,
        has_more=True,
    )

    # Las anteriores al cursor ya llegaron; la base decide cuáles cambiaron después.
    assert missing_cards(page) == {sent, later}
