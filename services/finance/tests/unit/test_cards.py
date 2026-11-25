import pytest
from hypothesis import given
from hypothesis import strategies as st

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import MAX_CENTS, Card, parse_card

VALID = {
    "name": "Oro",
    "cut_day": 5,
    "personal_limit_cents": 1_000_000,
    "bank_limit_cents": 2_500_000,
    "used_at_creation_cents": 0,
    "installments_count_against_limit": False,
}


def rejected(data: dict) -> tuple[str, str]:
    with pytest.raises(InvalidField) as error:
        parse_card(data)
    return error.value.field, error.value.rule


def test_a_valid_card_keeps_every_value() -> None:
    assert parse_card(VALID) == Card(
        name="Oro",
        cut_day=5,
        personal_limit_cents=1_000_000,
        bank_limit_cents=2_500_000,
        used_at_creation_cents=0,
        installments_count_against_limit=False,
    )


def test_optional_values_have_defaults() -> None:
    data = {"name": "Oro", "cut_day": 5, "bank_limit_cents": 1, "used_at_creation_cents": 0}
    card = parse_card(data)
    assert card.personal_limit_cents is None
    assert card.installments_count_against_limit is True


def test_the_name_is_trimmed() -> None:
    assert parse_card({**VALID, "name": "  Oro  "}).name == "Oro"


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"name": "   "}, ("name", "blank")),
        ({"name": "x" * 51}, ("name", "too_long")),
        ({"name": 7}, ("name", "type")),
        ({"cut_day": 0}, ("cut_day", "range")),
        ({"cut_day": 32}, ("cut_day", "range")),
        ({"cut_day": "5"}, ("cut_day", "type")),
        # En Python True vale 1: un booleano nunca pasa por número.
        ({"cut_day": True}, ("cut_day", "type")),
        ({"cut_day": 5.0}, ("cut_day", "type")),
        ({"personal_limit_cents": 0}, ("personal_limit_cents", "range")),
        ({"bank_limit_cents": -1}, ("bank_limit_cents", "range")),
        ({"bank_limit_cents": MAX_CENTS + 1}, ("bank_limit_cents", "range")),
        ({"personal_limit_cents": None, "bank_limit_cents": None}, ("limits", "at_least_one")),
        ({"used_at_creation_cents": -1}, ("used_at_creation_cents", "range")),
        ({"installments_count_against_limit": 1}, ("installments_count_against_limit", "type")),
        ({"color": "rojo"}, ("color", "unknown")),
    ],
)
def test_invalid_values_name_the_field_and_the_rule(change: dict, expected: tuple) -> None:
    assert rejected({**VALID, **change}) == expected


@pytest.mark.parametrize("field", ["name", "cut_day", "used_at_creation_cents"])
def test_required_values(field: str) -> None:
    data = dict(VALID)
    del data[field]
    assert rejected(data) == (field, "required")


def test_the_limits_and_used_amount_accept_their_edges() -> None:
    card = parse_card({**VALID, "personal_limit_cents": 1, "bank_limit_cents": MAX_CENTS})
    assert (card.personal_limit_cents, card.bank_limit_cents) == (1, MAX_CENTS)
    used = parse_card({**VALID, "used_at_creation_cents": MAX_CENTS}).used_at_creation_cents
    assert used == MAX_CENTS


@given(st.integers(min_value=1, max_value=31))
def test_every_cut_day_from_1_to_31_is_valid(day: int) -> None:
    assert parse_card({**VALID, "cut_day": day}).cut_day == day


def test_a_card_cannot_be_built_invalid_without_parsing() -> None:
    with pytest.raises(InvalidField):
        Card(
            name="Oro",
            cut_day=40,
            personal_limit_cents=None,
            bank_limit_cents=1,
            used_at_creation_cents=0,
            installments_count_against_limit=True,
        )
