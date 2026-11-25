from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

INSTALLMENT = {"kind": "installment", "months": 12, "monthly_rate": Decimal("0.03")}
PAYMENT = {"kind": "payment", "payment_source": "cash", "review_status": "confirmed"}


@pytest.fixture
def card(insert, make_card) -> dict:
    row = make_card()
    insert("cards", row)
    return row


@pytest.mark.parametrize(
    "kind",
    [{}, INSTALLMENT, {**INSTALLMENT, "months": 1, "monthly_rate": Decimal(0)}, PAYMENT],
)
def test_each_kind_of_movement_is_stored(insert, make_movement, card, kind: dict) -> None:
    insert("movements", make_movement(card, **kind))


def test_the_offset_and_the_exact_rate_come_back_as_stored(insert, make_movement, card, engine):
    insert("movements", make_movement(card, **INSTALLMENT, occurred_offset_minutes=60))
    with engine.connect() as connection:
        offset, rate = connection.execute(
            text("SELECT occurred_offset_minutes, monthly_rate FROM finance.movements")
        ).one()
    assert (offset, rate) == (60, Decimal("0.030000"))


@pytest.mark.parametrize(
    "change",
    [
        {"amount_cents": 0},
        {"occurred_offset_minutes": -721},
        {"occurred_offset_minutes": 841},
        {"review_status": "quizas"},
        {"kind": "regalo"},
        # Cada tipo lleva solo sus campos, y los lleva todos.
        {"months": 12},
        {"payment_source": "cash"},
        {**INSTALLMENT, "months": None},
        {**INSTALLMENT, "monthly_rate": None},
        {**INSTALLMENT, "months": 0},
        {**INSTALLMENT, "months": 121},
        {**INSTALLMENT, "monthly_rate": Decimal("-0.01")},
        {**INSTALLMENT, "monthly_rate": Decimal(1)},
        {**INSTALLMENT, "payment_source": "cash"},
        {**PAYMENT, "payment_source": None},
        {**PAYMENT, "payment_source": "card"},
        {**PAYMENT, "months": 3},
        {"version": 0},
    ],
)
def test_the_database_rejects_what_the_domain_rejects(insert, make_movement, card, change) -> None:
    with pytest.raises(IntegrityError, match="ck_movements_"):
        insert("movements", make_movement(card, **change))


def test_a_movement_needs_an_existing_card_of_the_same_account(insert, make_movement, card):
    with pytest.raises(IntegrityError, match="fk_movements_card"):
        insert("movements", make_movement({**card, "id": uuid4()}))
    # La tarjeta existe, pero es de otra cuenta.
    with pytest.raises(IntegrityError, match="fk_movements_card"):
        insert("movements", make_movement({**card, "user_id": uuid4()}))


def test_an_idempotency_key_is_unique_per_user(insert, make_movement, card) -> None:
    first = make_movement(card)
    insert("movements", first)
    with pytest.raises(IntegrityError, match="uq_movements_user_idempotency_key"):
        insert("movements", make_movement(card, idempotency_key=first["idempotency_key"]))
