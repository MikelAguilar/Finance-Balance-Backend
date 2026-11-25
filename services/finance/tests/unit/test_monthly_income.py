import pytest

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import MAX_CENTS, MonthlyIncome, parse_monthly_income


def rejected(data: dict) -> tuple[str, str]:
    with pytest.raises(InvalidField) as error:
        parse_monthly_income(data)
    return error.value.field, error.value.rule


def test_a_monthly_income_in_cents() -> None:
    assert parse_monthly_income({"amount_cents": 2_500_000}) == MonthlyIncome(2_500_000)
    assert parse_monthly_income({"amount_cents": MAX_CENTS}).amount_cents == MAX_CENTS


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        # Sin ingreso no es 0: es no tener ingreso registrado.
        ({"amount_cents": 0}, ("amount_cents", "range")),
        ({"amount_cents": MAX_CENTS + 1}, ("amount_cents", "range")),
        ({"amount_cents": "25000"}, ("amount_cents", "type")),
        ({}, ("amount_cents", "required")),
        ({"amount_cents": 1, "currency": "MXN"}, ("currency", "unknown")),
    ],
)
def test_invalid_values_name_the_field_and_the_rule(data: dict, expected: tuple) -> None:
    assert rejected(data) == expected
