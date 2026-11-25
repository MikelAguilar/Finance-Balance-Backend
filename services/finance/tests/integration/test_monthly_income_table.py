from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError


def test_the_database_rejects_an_income_of_zero(insert, make_income) -> None:
    with pytest.raises(IntegrityError, match="ck_monthly_income_amount"):
        insert("monthly_income", make_income(amount_cents=0))


def test_one_current_income_per_account(insert, make_income) -> None:
    first = make_income()
    insert("monthly_income", first)
    with pytest.raises(IntegrityError, match="uq_monthly_income_user_current"):
        insert("monthly_income", make_income(user_id=first["user_id"]))


def test_a_deleted_income_does_not_block_a_new_one(insert, make_income) -> None:
    # Nada se borra: el ingreso anterior queda con deleted_at y se registra otro.
    first = make_income(deleted_at=datetime(2026, 11, 1, tzinfo=UTC))
    insert("monthly_income", first)
    insert("monthly_income", make_income(user_id=first["user_id"]))


def test_an_idempotency_key_is_unique_per_user(insert, make_income) -> None:
    first = make_income(deleted_at=datetime(2026, 11, 1, tzinfo=UTC))
    insert("monthly_income", first)
    repeated = make_income(user_id=first["user_id"], idempotency_key=first["idempotency_key"])
    with pytest.raises(IntegrityError, match="uq_monthly_income_user_idempotency_key"):
        insert("monthly_income", repeated)
