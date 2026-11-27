from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import MAX_CENTS, MonthlyIncome, parse_card
from finance_service.domain.sync import (
    MAX_CHANGES,
    CardRef,
    Edit,
    New,
    parse_sync_request,
)

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)
CDMX = timezone(timedelta(hours=-6))
U = "00000000-0000-4000-8000-00000000000{}".format
CARD = {"name": "Oro", "cut_day": 5, "personal_limit_cents": 100_000, "used_at_creation_cents": 0}
MOVEMENT = {
    "amount_cents": 45_050,
    "occurred_at": "2026-11-25T19:30:00-06:00",
    "kind": "normal",
    "review_status": "confirmed",
    "owner_cut": "2026-12-05",
}


def new(key: int, data: dict, change: int = 0, **extra: object) -> dict:
    return {
        "key": U(key),
        "change_id": f"00000000-0000-4000-8000-0000000000c{change or key}",
        "updated_at": "2026-11-26T05:00:00-06:00",
        "data": data,
        **extra,
    }


def upload(**changes: list) -> dict:
    return {"sent_at": "2026-11-26T05:30:00-06:00", "cursor": 3, "changes": changes}


def rejected(data: object) -> dict:
    with pytest.raises(InvalidField) as error:
        parse_sync_request(data, NOW)
    return {"path": error.value.path, "field": error.value.field, "rule": error.value.rule}


# --- Lo que se acepta ----------------------------------------------------------------------------


def test_without_changes_it_is_only_a_download() -> None:
    request = parse_sync_request({"cursor": 41}, NOW)
    assert (request.cursor, request.upload) == (41, None)


def test_an_upload_reads_creations_edits_and_card_references() -> None:
    edit = {
        "id": U(7),
        "base_version": 3,
        "change_id": U(8),
        "updated_at": "2026-11-26T04:00:00-06:00",
        "data": {"amount_cents": 2_500_000},
    }
    data = upload(
        cards=[new(1, CARD)],
        movements=[new(2, MOVEMENT, card={"key": U(1)}), new(3, MOVEMENT, card={"id": U(9)})],
        monthly_income=[edit],
    )

    request = parse_sync_request(data, NOW)

    sent = request.upload
    assert sent.sent_at == datetime(2026, 11, 26, 5, 30, tzinfo=CDMX)
    assert sent.cards[0].target == New(key=UUID(U(1)))
    assert sent.cards[0].value == parse_card(CARD)
    assert sent.cards[0].change_id == UUID("00000000-0000-4000-8000-0000000000c1")
    assert sent.cards[0].updated_at == datetime(2026, 11, 26, 5, tzinfo=CDMX)
    assert [m.card for m in sent.movements] == [CardRef(key=UUID(U(1))), CardRef(id=UUID(U(9)))]
    assert sent.incomes[0].target == Edit(id=UUID(U(7)), base_version=3)
    assert sent.incomes[0].value == MonthlyIncome(2_500_000)
    assert sent.incomes[0].card is None


def test_each_table_is_optional() -> None:
    sent = parse_sync_request(upload(cards=[new(1, CARD)]), NOW).upload
    assert (len(sent.cards), sent.movements, sent.incomes) == (1, [], [])


# --- Rechazos del sobre --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ([], ("", "body", "type")),
        ({"cursor": 0, "changes": {}}, ("", "sent_at", "required")),
        (
            {"cursor": 0, "sent_at": "2026-11-26T05:30:00", "changes": {}},
            ("", "sent_at", "missing_offset"),
        ),
        ({"cursor": 0, "sent_at": 5, "changes": {}}, ("", "sent_at", "type")),
        ({"cursor": 0, "sent_at": "ayer", "changes": {}}, ("", "sent_at", "format")),
        ({"cursor": 0, "sent_at": "2026-11-26T05:30:00Z", "changes": []}, ("", "changes", "type")),
        (upload(accounts=[]), ("changes", "accounts", "unknown")),
        (upload(cards={}), ("changes", "cards", "type")),
        (upload(cards=[[]]), ("changes.cards[0]", "change", "type")),
    ],
)
def test_an_invalid_envelope_names_the_path_the_field_and_the_rule(data, expected) -> None:
    assert rejected(data) == dict(zip(("path", "field", "rule"), expected, strict=True))


def test_more_than_500_changes_is_too_many() -> None:
    cards = [new(1, CARD, change=1)] * (MAX_CHANGES // 2)
    movements = [new(2, MOVEMENT, card={"key": U(1)})] * (MAX_CHANGES - len(cards) + 1)
    assert MAX_CHANGES == 500
    assert rejected(upload(cards=cards, movements=movements)) == {
        "path": "",
        "field": "changes",
        "rule": "too_many",
    }


def test_exactly_500_changes_are_accepted() -> None:
    cards = [new(1 + i % 9, CARD, change=1) for i in range(MAX_CHANGES)]
    for i, card in enumerate(cards):
        card["key"] = f"00000000-0000-4000-8000-{i:012d}"
        card["change_id"] = f"00000000-0000-4000-9000-{i:012d}"
    assert len(parse_sync_request(upload(cards=cards), NOW).upload.cards) == MAX_CHANGES


# --- Rechazos de cada cambio ---------------------------------------------------------------------


def change_error(change: dict, table: str = "cards") -> tuple:
    first = new(1, CARD) if table == "cards" else new(1, MOVEMENT, card={"key": U(1)})
    error = rejected(upload(**{table: [first, change]}))
    assert error["path"] == f"changes.{table}[1]"
    return error["field"], error["rule"]


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({**new(2, CARD), "key": None}, ("key", "required")),
        ({**new(2, CARD), "key": 5}, ("key", "type")),
        ({**new(2, CARD), "key": "no-es-uuid"}, ("key", "format")),
        ({**new(2, CARD), "id": U(5)}, ("key", "not_allowed")),
        ({**new(2, CARD), "change_id": None}, ("change_id", "required")),
        ({**new(2, CARD), "change_id": "no-es-uuid"}, ("change_id", "format")),
        ({**new(2, CARD), "updated_at": "2026-11-26T05:00:00"}, ("updated_at", "missing_offset")),
        ({**new(2, CARD), "data": None}, ("data", "required")),
        ({**new(2, CARD), "data": []}, ("data", "type")),
        ({**new(2, CARD), "card": {"key": U(1)}}, ("card", "unknown")),
        ({**new(2, CARD), "version": 1}, ("version", "unknown")),
        (new(2, {**CARD, "cut_day": 32}), ("cut_day", "range")),
    ],
)
def test_an_invalid_change_names_its_position_the_field_and_the_rule(change, expected) -> None:
    assert change_error(change) == expected


@pytest.mark.parametrize(
    ("edit", "expected"),
    [
        ({}, ("base_version", "required")),
        ({"base_version": 0}, ("base_version", "range")),
        ({"base_version": 2**31}, ("base_version", "range")),
        ({"base_version": True}, ("base_version", "type")),
        ({"base_version": 1, "id": "no-es-uuid"}, ("id", "format")),
    ],
)
def test_an_edit_needs_the_version_it_was_made_on(edit: dict, expected: tuple) -> None:
    change = {**new(2, CARD), "key": None, "id": U(5), **edit}
    assert change_error(change) == expected


def test_the_largest_version_is_accepted() -> None:
    change = {**new(2, CARD), "key": None, "id": U(5), "base_version": 2**31 - 1}
    sent = parse_sync_request(upload(cards=[change]), NOW).upload
    assert sent.cards[0].target == Edit(id=UUID(U(5)), base_version=2**31 - 1)


@pytest.mark.parametrize(
    ("card", "expected"),
    [
        (None, ("card", "required")),
        ("x", ("card", "type")),
        ({}, ("card", "required")),
        ({"id": U(1), "key": U(2)}, ("card.key", "not_allowed")),
        ({"key": "x"}, ("card.key", "format")),
        ({"id": "x"}, ("card.id", "format")),
        ({"name": "Oro"}, ("card.name", "unknown")),
    ],
)
def test_a_movement_points_to_one_card(card: object, expected: tuple) -> None:
    change = new(2, MOVEMENT, card=card)
    assert change_error(change, "movements") == expected


def test_a_movement_date_is_checked_against_the_server_clock() -> None:
    late = {**MOVEMENT, "occurred_at": "2026-11-28T12:00:00+00:00"}
    assert change_error(new(2, late, card={"key": U(1)}), "movements") == ("occurred_at", "future")


def test_an_invalid_income_names_its_position() -> None:
    error = rejected(upload(monthly_income=[new(1, {"amount_cents": 0})]))
    assert error == {"path": "changes.monthly_income[0]", "field": "amount_cents", "rule": "range"}


# --- Repetidos -----------------------------------------------------------------------------------


def test_the_same_new_record_twice_is_a_duplicate() -> None:
    assert change_error(new(1, CARD, change=2)) == ("key", "duplicate")


def test_the_same_edited_record_twice_is_a_duplicate() -> None:
    edit = {**new(2, CARD), "key": None, "id": U(5), "base_version": 1}
    error = rejected(upload(cards=[edit, {**edit, "change_id": U(9)}]))
    assert error == {"path": "changes.cards[1]", "field": "id", "rule": "duplicate"}


def test_the_same_change_twice_is_a_duplicate_even_in_another_table() -> None:
    movement = new(2, MOVEMENT, change=1, card={"key": U(1)})
    error = rejected(upload(cards=[new(1, CARD)], movements=[movement]))
    assert error == {"path": "changes.movements[0]", "field": "change_id", "rule": "duplicate"}


def test_the_same_income_twice_is_a_duplicate() -> None:
    income = {"amount_cents": 1}
    error = rejected(upload(monthly_income=[new(1, income), new(1, income, change=2)]))
    assert error == {"path": "changes.monthly_income[1]", "field": "key", "rule": "duplicate"}


def test_edits_of_two_different_records_are_not_duplicates() -> None:
    first = {**new(2, CARD), "key": None, "id": U(5), "base_version": 1}
    second = {**new(3, CARD), "key": None, "id": U(6), "base_version": 1}
    assert len(parse_sync_request(upload(cards=[first, second]), NOW).upload.cards) == 2


def test_the_same_key_in_two_tables_is_not_a_duplicate() -> None:
    movement = new(1, MOVEMENT, change=2, card={"key": U(1)})
    assert parse_sync_request(upload(cards=[new(1, CARD)], movements=[movement]), NOW)


def test_the_cursor_keeps_its_rules() -> None:
    assert rejected({"cursor": -1}) == {"path": "", "field": "cursor", "rule": "range"}
    assert parse_sync_request({"cursor": MAX_CENTS}, NOW).cursor == MAX_CENTS
