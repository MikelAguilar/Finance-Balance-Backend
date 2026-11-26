import pytest
from sqlalchemy.exc import IntegrityError


def test_a_valid_card_is_stored(insert, make_card) -> None:
    insert("cards", make_card(personal_limit_cents=None))


@pytest.mark.parametrize(
    "change",
    [
        {"name": "   "},
        {"cut_day": 0},
        {"cut_day": 32},
        {"personal_limit_cents": 0},
        {"bank_limit_cents": 0},
        {"personal_limit_cents": None, "bank_limit_cents": None},
        {"used_at_creation_cents": -1},
        {"version": 0},
    ],
)
def test_the_database_rejects_what_the_domain_rejects(insert, make_card, change: dict) -> None:
    with pytest.raises(IntegrityError, match="ck_cards_"):
        insert("cards", make_card(**change))


def test_an_idempotency_key_is_unique_per_user(insert, make_card) -> None:
    first = make_card()
    insert("cards", first)
    # Otra cuenta puede generar la misma clave sin chocar.
    insert("cards", make_card(idempotency_key=first["idempotency_key"]))
    repeated = make_card(user_id=first["user_id"], idempotency_key=first["idempotency_key"])
    with pytest.raises(IntegrityError, match="uq_cards_user_idempotency_key"):
        insert("cards", repeated)
