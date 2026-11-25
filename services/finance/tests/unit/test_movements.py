from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import (
    MAX_CENTS,
    Installment,
    Movement,
    Normal,
    OccurredAt,
    Payment,
    PaymentSource,
    ReviewStatus,
    parse_movement,
)

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
NORMAL = {
    "amount_cents": 45_050,
    "occurred_at": "2026-11-25T03:00:00-06:00",
    "kind": "normal",
    "review_status": "pending_review",
    "owner_cut": "2026-12-05",
}
INSTALLMENT = {**NORMAL, "kind": "installment", "months": 12, "monthly_rate": "0.03"}
PAYMENT = {**NORMAL, "kind": "payment", "payment_source": "debit", "review_status": "confirmed"}


def rejected(data: dict) -> tuple[str, str]:
    with pytest.raises(InvalidField) as error:
        parse_movement(data, NOW)
    return error.value.field, error.value.rule


def test_a_normal_charge() -> None:
    assert parse_movement(NORMAL, NOW) == Movement(
        amount_cents=45_050,
        occurred=OccurredAt(at=datetime(2026, 11, 25, 9, tzinfo=UTC), offset_minutes=-360),
        kind=Normal(),
        review_status=ReviewStatus.PENDING_REVIEW,
        owner_cut=date(2026, 12, 5),
    )


def test_an_installment_purchase_keeps_the_rate_exact() -> None:
    movement = parse_movement(INSTALLMENT, NOW)
    assert movement.kind == Installment(months=12, monthly_rate=Decimal("0.03"))


def test_interest_free_months_use_a_zero_rate() -> None:
    kind = parse_movement({**INSTALLMENT, "monthly_rate": "0"}, NOW).kind
    assert kind == Installment(months=12, monthly_rate=Decimal(0))


def test_a_card_payment_says_where_the_money_came_from() -> None:
    assert parse_movement(PAYMENT, NOW).kind == Payment(source=PaymentSource.DEBIT)
    cash = parse_movement({**PAYMENT, "payment_source": "cash"}, NOW).kind
    assert cash == Payment(source=PaymentSource.CASH)


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({**NORMAL, "amount_cents": 0}, ("amount_cents", "range")),
        ({**NORMAL, "amount_cents": MAX_CENTS + 1}, ("amount_cents", "range")),
        ({**NORMAL, "amount_cents": 450.5}, ("amount_cents", "type")),
        ({**NORMAL, "occurred_at": "2026-11-25T03:00:00"}, ("occurred_at", "missing_offset")),
        ({**NORMAL, "kind": "regalo"}, ("kind", "range")),
        ({**NORMAL, "review_status": "quizas"}, ("review_status", "range")),
        ({**NORMAL, "owner_cut": "5 de diciembre"}, ("owner_cut", "format")),
        ({**NORMAL, "owner_cut": 20261205}, ("owner_cut", "type")),
        ({**NORMAL, "months": 12}, ("months", "not_allowed")),
        ({**NORMAL, "payment_source": "cash"}, ("payment_source", "not_allowed")),
        ({**INSTALLMENT, "months": 0}, ("months", "range")),
        ({**INSTALLMENT, "months": 121}, ("months", "range")),
        ({**INSTALLMENT, "monthly_rate": "-0.01"}, ("monthly_rate", "range")),
        ({**INSTALLMENT, "monthly_rate": "1"}, ("monthly_rate", "range")),
        ({**INSTALLMENT, "monthly_rate": "0.0000001"}, ("monthly_rate", "precision")),
        # La tasa viaja como texto: un número de JSON es float y perdería precisión.
        ({**INSTALLMENT, "monthly_rate": 0.03}, ("monthly_rate", "type")),
        ({**INSTALLMENT, "monthly_rate": "tres"}, ("monthly_rate", "format")),
        ({**INSTALLMENT, "monthly_rate": "NaN"}, ("monthly_rate", "format")),
        ({**INSTALLMENT, "monthly_rate": "Infinity"}, ("monthly_rate", "format")),
        ({**INSTALLMENT, "payment_source": "cash"}, ("payment_source", "not_allowed")),
        ({**PAYMENT, "payment_source": "tarjeta"}, ("payment_source", "range")),
        ({**PAYMENT, "monthly_rate": "0"}, ("monthly_rate", "not_allowed")),
        ({**NORMAL, "card": "Oro"}, ("card", "unknown")),
    ],
)
def test_invalid_values_name_the_field_and_the_rule(data: dict, expected: tuple) -> None:
    assert rejected(data) == expected


@pytest.mark.parametrize(
    "field", ["amount_cents", "occurred_at", "kind", "review_status", "owner_cut"]
)
def test_required_values(field: str) -> None:
    data = dict(NORMAL)
    del data[field]
    assert rejected(data) == (field, "required")


@pytest.mark.parametrize(
    ("data", "field"),
    [(INSTALLMENT, "months"), (INSTALLMENT, "monthly_rate"), (PAYMENT, "payment_source")],
)
def test_each_kind_requires_its_own_values(data: dict, field: str) -> None:
    data = dict(data)
    del data[field]
    assert rejected(data) == (field, "required")


def test_months_and_rate_accept_their_edges() -> None:
    edges = {**INSTALLMENT, "months": 1, "monthly_rate": "0.999999"}
    assert parse_movement(edges, NOW).kind == Installment(1, Decimal("0.999999"))
    assert parse_movement({**INSTALLMENT, "months": 120}, NOW).kind.months == 120


def test_a_movement_cannot_be_built_invalid() -> None:
    with pytest.raises(InvalidField):
        Installment(months=0, monthly_rate=Decimal(0))
    with pytest.raises(InvalidField):
        Payment(source="tarjeta")
    with pytest.raises(InvalidField):
        Movement(
            amount_cents=-1,
            occurred=OccurredAt(at=NOW, offset_minutes=0),
            kind=Normal(),
            review_status=ReviewStatus.CONFIRMED,
            owner_cut=date(2026, 12, 5),
        )


VALID_PARTS = {
    "amount_cents": 1,
    "occurred": OccurredAt(at=NOW, offset_minutes=0),
    "kind": Normal(),
    "review_status": ReviewStatus.CONFIRMED,
    "owner_cut": date(2026, 12, 5),
}


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({"occurred": "2026-11-25T03:00:00Z"}, ("occurred_at", "type")),
        ({"kind": "normal"}, ("kind", "range")),
        ({"review_status": "confirmed"}, ("review_status", "range")),
        # datetime hereda de date: un instante no sirve como día de corte.
        ({"owner_cut": NOW}, ("owner_cut", "type")),
    ],
)
def test_a_movement_built_directly_only_takes_domain_values(change: dict, expected: tuple) -> None:
    with pytest.raises(InvalidField) as error:
        Movement(**{**VALID_PARTS, **change})
    assert (error.value.field, error.value.rule) == expected


@pytest.mark.parametrize("rate", [0.03, Decimal("NaN")])
def test_an_installment_built_directly_needs_a_finite_decimal_rate(rate: object) -> None:
    with pytest.raises(InvalidField) as error:
        Installment(months=12, monthly_rate=rate)
    assert (error.value.field, error.value.rule) == ("monthly_rate", "type")
