"""La subida de cambios contra PostgreSQL real, de la llamada HTTP a la base."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from finance_service.config import Settings
from finance_service.main import create_app

CARD = {"name": "Oro", "cut_day": 5, "personal_limit_cents": 100_000, "used_at_creation_cents": 0}
MOVEMENT = {
    "amount_cents": 45_050,
    "occurred_at": "2026-11-20T19:30:00-06:00",
    "kind": "normal",
    "review_status": "confirmed",
    "owner_cut": "2026-12-05",
}
NOW = datetime.now(UTC)


def iso(moment: datetime) -> str:
    return moment.isoformat()


def change(data: dict, *, key=None, id=None, base_version=None, edited=None, **extra) -> dict:
    """Un cambio de la app: nuevo (con `key`) o edición (con `id` y `base_version`)."""
    body = {"change_id": str(uuid4()), "updated_at": iso(edited or NOW), "data": data, **extra}
    if id is None:
        body["key"] = str(key or uuid4())
    else:
        body |= {"id": id, "base_version": base_version}
    return body


@pytest.fixture
def client(engine, database_url: str) -> Iterator[TestClient]:
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        yield client


class Phone:
    """Un teléfono de una cuenta, con su reloj (que puede ir adelantado o atrasado)."""

    def __init__(self, client: TestClient, user, clock_offset: timedelta = timedelta()) -> None:
        self.client, self.user, self.offset = client, user, clock_offset

    def clock(self, real: datetime) -> datetime:
        return real + self.offset

    def post(self, cursor: int = 0, sent_at: datetime | None = None, **changes):
        body = {"cursor": cursor, "sent_at": iso(self.clock(sent_at or datetime.now(UTC)))}
        body["changes"] = changes
        return self.client.post("/sync", json=body, headers={"X-User-Id": str(self.user)})

    def send(self, **changes) -> dict:
        response = self.post(**changes)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
def phone(client) -> Phone:
    return Phone(client, uuid4())


def count(engine, table: str, user) -> int:
    with engine.connect() as connection:
        query = text(f"SELECT count(*) FROM finance.{table} WHERE user_id = :user")
        return connection.execute(query, {"user": user}).scalar()


def statuses(answer: dict, table: str) -> list[str]:
    return [result["status"] for result in answer["results"][table]]


def records(answer: dict, table: str) -> list[dict]:
    return [result["record"] for result in answer["results"][table]]


# --- Tarjetas creadas sin red --------------------------------------------------------------------


def test_two_cards_created_offline_arrive_with_their_movements(phone, engine) -> None:
    gold, blue = uuid4(), uuid4()
    answer = phone.send(
        cards=[change(CARD, key=gold), change({**CARD, "name": "Azul"}, key=blue)],
        movements=[
            change(MOVEMENT, card={"key": str(blue)}),
            change(MOVEMENT, card={"key": str(gold)}),
            change({**MOVEMENT, "amount_cents": 1}, card={"key": str(gold)}),
        ],
    )

    cards = records(answer, "cards")
    card_ids = {card["key"]: card["id"] for card in cards}
    assert statuses(answer, "cards") == statuses(answer, "movements")[:2] == ["applied"] * 2
    assert [m["card"]["id"] for m in records(answer, "movements")] == [
        card_ids[str(blue)],
        card_ids[str(gold)],
        card_ids[str(gold)],
    ]
    assert all(record["version"] == 1 for record in cards + records(answer, "movements"))
    # La misma respuesta trae la descarga: lo recién creado ya tiene número de cambio.
    assert len(answer["changes"]["cards"]) == 2 and len(answer["changes"]["movements"]) == 3
    assert (count(engine, "cards", phone.user), count(engine, "movements", phone.user)) == (2, 3)


def test_a_movement_can_point_to_a_card_created_in_an_earlier_sync(phone) -> None:
    key = uuid4()
    first = phone.send(cards=[change(CARD, key=key)])
    card_id = records(first, "cards")[0]["id"]

    by_key = phone.send(movements=[change(MOVEMENT, card={"key": str(key)})])
    by_id = phone.send(movements=[change(MOVEMENT, card={"id": card_id})])

    assert records(by_key, "movements")[0]["card"] == records(by_id, "movements")[0]["card"]
    assert records(by_id, "movements")[0]["card"] == {"id": card_id}


def test_the_card_data_is_saved_as_sent(phone) -> None:
    payment = {**MOVEMENT, "kind": "payment", "payment_source": "cash"}
    installment = {**MOVEMENT, "kind": "installment", "months": 12, "monthly_rate": "0.015"}
    key = uuid4()
    answer = phone.send(
        cards=[change(CARD, key=key)],
        movements=[
            change(payment, card={"key": str(key)}),
            change(installment, card={"key": str(key)}),
        ],
        monthly_income=[change({"amount_cents": 2_500_000})],
    )

    downloaded = phone.send()["changes"]
    assert [m["data"] for m in downloaded["movements"]] == [
        payment,
        {**installment, "monthly_rate": "0.015000"},
    ]
    assert downloaded["cards"][0]["data"] == {
        **CARD,
        "bank_limit_cents": None,
        "installments_count_against_limit": True,
    }
    assert records(answer, "monthly_income")[0]["data"] == {"amount_cents": 2_500_000}


# --- Reintentos ----------------------------------------------------------------------------------


def test_sending_the_same_upload_again_never_duplicates(phone, engine) -> None:
    card = change(CARD)
    movement = change(MOVEMENT, card={"key": card["key"]})
    income = change({"amount_cents": 2_500_000})

    first = phone.send(cards=[card], movements=[movement], monthly_income=[income])
    again = phone.send(cards=[card], movements=[movement], monthly_income=[income])

    assert again["results"] == first["results"]
    counts = [
        count(engine, table, phone.user) for table in ("cards", "movements", "monthly_income")
    ]
    assert counts == [1, 1, 1]


def test_retrying_an_edit_does_not_apply_it_twice(phone) -> None:
    created = records(phone.send(cards=[change(CARD)]), "cards")[0]
    edit = change({**CARD, "name": "Platino"}, id=created["id"], base_version=1)

    first = phone.send(cards=[edit])
    again = phone.send(cards=[edit])

    assert records(first, "cards")[0]["version"] == records(again, "cards")[0]["version"] == 2
    assert statuses(again, "cards") == ["applied"]


def test_a_new_record_edited_again_before_its_answer_arrived_keeps_the_last_edit(phone) -> None:
    # Se creó, la respuesta se perdió y se volvió a editar sin red: la app aún no tiene el id.
    key = uuid4()
    phone.send(cards=[change(CARD, key=key, edited=NOW - timedelta(minutes=5))])

    answer = phone.send(cards=[change({**CARD, "name": "Platino"}, key=key)])

    assert records(answer, "cards")[0]["data"]["name"] == "Platino"
    assert records(answer, "cards")[0]["version"] == 2


# --- Dos teléfonos -------------------------------------------------------------------------------


def edit_from_two_phones(client, first_offset=timedelta(), second_offset=timedelta()):
    """Dos teléfonos de una cuenta y una tarjeta en su versión 1, creada por el primero."""
    user = uuid4()
    first, second = Phone(client, user, first_offset), Phone(client, user, second_offset)
    card = records(first.send(cards=[change(CARD)]), "cards")[0]
    return card, first, second


def test_an_edit_on_the_current_version_wins_whatever_the_clock(client) -> None:
    card, first, _ = edit_from_two_phones(client)
    long_ago = NOW - timedelta(days=30)

    answer = first.send(
        cards=[change({**CARD, "name": "A"}, id=card["id"], base_version=1, edited=long_ago)]
    )

    assert (statuses(answer, "cards"), records(answer, "cards")[0]["version"]) == (["applied"], 2)


def test_in_a_clash_the_later_edit_wins_and_the_earlier_one_is_lost(client) -> None:
    card, first, second = edit_from_two_phones(client)
    later = change({**CARD, "name": "Después"}, id=card["id"], base_version=1, edited=NOW)
    earlier = change(
        {**CARD, "name": "Antes"}, id=card["id"], base_version=1, edited=NOW - timedelta(minutes=1)
    )

    first.send(cards=[later])
    answer = second.send(cards=[earlier])

    assert statuses(answer, "cards") == ["lost"]
    assert records(answer, "cards")[0]["data"]["name"] == "Después"
    assert records(answer, "cards")[0]["version"] == 2


def test_a_phone_with_its_clock_behind_still_wins_when_it_edited_later(client) -> None:
    # El segundo teléfono va una hora atrasado: su hora dice "antes", pero editó después.
    card, first, second = edit_from_two_phones(client, second_offset=-timedelta(hours=1))
    real = datetime.now(UTC)
    first.send(cards=[change({**CARD, "name": "A"}, id=card["id"], base_version=1, edited=real)])

    edited = second.clock(real + timedelta(seconds=30))
    answer = second.send(
        cards=[change({**CARD, "name": "B"}, id=card["id"], base_version=1, edited=edited)]
    )

    assert (statuses(answer, "cards"), records(answer, "cards")[0]["version"]) == (["applied"], 3)


def test_a_phone_with_its_clock_ahead_does_not_win_for_that(client) -> None:
    # El segundo teléfono va un día adelantado: su hora dice "después", pero editó antes.
    card, first, second = edit_from_two_phones(client, second_offset=timedelta(days=1))
    real = datetime.now(UTC)
    first.send(cards=[change({**CARD, "name": "A"}, id=card["id"], base_version=1, edited=real)])

    edited = second.clock(real - timedelta(minutes=10))
    answer = second.send(
        cards=[change({**CARD, "name": "B"}, id=card["id"], base_version=1, edited=edited)]
    )

    assert statuses(answer, "cards") == ["lost"]


def test_an_edit_after_the_send_counts_as_made_at_the_send(client) -> None:
    # Editó con el reloj un año adelantado y lo regresó antes de enviar: esa hora imposible cuenta
    # como hecha al enviar, así que una edición real posterior le gana.
    card, first, second = edit_from_two_phones(client)
    impossible = datetime.now(UTC) + timedelta(days=365)
    second.send(
        cards=[change({**CARD, "name": "B"}, id=card["id"], base_version=1, edited=impossible)]
    )

    later = datetime.now(UTC) + timedelta(seconds=1)
    answer = first.send(
        cards=[change({**CARD, "name": "A"}, id=card["id"], base_version=1, edited=later)]
    )

    assert (statuses(answer, "cards"), records(answer, "cards")[0]["version"]) == (["applied"], 3)


def test_two_phones_creating_the_income_resolve_it_as_a_clash(client, engine) -> None:
    user = uuid4()
    first, second = Phone(client, user), Phone(client, user)
    first.send(
        monthly_income=[change({"amount_cents": 2_000_000}, edited=NOW - timedelta(hours=1))]
    )

    answer = second.send(monthly_income=[change({"amount_cents": 3_000_000}, edited=NOW)])

    record = records(answer, "monthly_income")[0]
    assert (statuses(answer, "monthly_income"), record["data"], record["version"]) == (
        ["applied"],
        {"amount_cents": 3_000_000},
        2,
    )
    assert count(engine, "monthly_income", user) == 1


def test_an_older_income_from_another_phone_is_lost(client) -> None:
    user = uuid4()
    first, second = Phone(client, user), Phone(client, user)
    first.send(monthly_income=[change({"amount_cents": 2_000_000}, edited=NOW)])

    answer = second.send(
        monthly_income=[change({"amount_cents": 3_000_000}, edited=NOW - timedelta(hours=1))]
    )

    assert statuses(answer, "monthly_income") == ["lost"]
    assert records(answer, "monthly_income")[0]["data"] == {"amount_cents": 2_000_000}


def test_a_replaced_income_does_not_clash_with_a_new_one(
    phone, insert, make_income, engine
) -> None:
    # Los ingresos anteriores se conservan con deleted_at: solo el vigente cuenta para el choque.
    insert("monthly_income", make_income(user_id=phone.user, deleted_at=NOW - timedelta(days=30)))

    answer = phone.send(monthly_income=[change({"amount_cents": 3_000_000})])

    record = records(answer, "monthly_income")[0]
    assert (statuses(answer, "monthly_income"), record["version"]) == (["applied"], 1)
    assert count(engine, "monthly_income", phone.user) == 2


# --- Rechazos: nada se guarda --------------------------------------------------------------------


def rejection(response) -> dict:
    assert response.status_code == 422, response.text
    return response.json()["detail"]


def test_a_movement_of_a_card_that_does_not_exist_rejects_the_whole_upload(phone, engine) -> None:
    response = phone.post(
        cards=[change(CARD)],
        movements=[change(MOVEMENT, card={"key": str(uuid4())})],
    )

    assert rejection(response) == {
        "path": "changes.movements[0]",
        "field": "card.key",
        "rule": "not_found",
    }
    assert count(engine, "cards", phone.user) == 0


def test_a_card_id_that_does_not_exist_is_not_found(phone) -> None:
    response = phone.post(movements=[change(MOVEMENT, card={"id": str(uuid4())})])
    assert rejection(response)["field"] == "card.id"
    assert rejection(response)["rule"] == "not_found"


def test_editing_a_record_that_does_not_exist_is_not_found(phone) -> None:
    response = phone.post(
        monthly_income=[change({"amount_cents": 1}, id=str(uuid4()), base_version=1)]
    )
    assert rejection(response) == {
        "path": "changes.monthly_income[0]",
        "field": "id",
        "rule": "not_found",
    }


def test_another_accounts_records_look_like_they_do_not_exist(client, engine) -> None:
    owner, intruder = Phone(client, uuid4()), Phone(client, uuid4())
    card = records(owner.send(cards=[change(CARD)]), "cards")[0]

    edit = intruder.post(cards=[change({**CARD, "name": "Mía"}, id=card["id"], base_version=1)])
    use = intruder.post(movements=[change(MOVEMENT, card={"id": card["id"]})])
    by_key = intruder.post(movements=[change(MOVEMENT, card={"key": card["key"]})])

    assert [rejection(r)["rule"] for r in (edit, use, by_key)] == ["not_found"] * 3
    assert owner.send()["changes"]["cards"][0]["data"]["name"] == "Oro"
    assert count(engine, "movements", intruder.user) == 0


def test_an_invalid_movement_rejects_the_cards_of_the_same_upload(phone, engine) -> None:
    key = uuid4()
    response = phone.post(
        cards=[change(CARD, key=key)],
        movements=[change({**MOVEMENT, "amount_cents": 0}, card={"key": str(key)})],
    )

    assert rejection(response) == {
        "path": "changes.movements[0]",
        "field": "amount_cents",
        "rule": "range",
    }
    assert count(engine, "cards", phone.user) == 0


# --- Un escritor por cuenta ----------------------------------------------------------------------


def test_an_upload_waits_while_another_sync_of_the_same_account_is_running(engine, phone) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
        {"user_id": str(phone.user)},
    )
    answers: list = []
    worker = threading.Thread(target=lambda: answers.append(phone.post(cards=[change(CARD)])))
    try:
        worker.start()
        worker.join(timeout=1)
        assert worker.is_alive(), "la subida no esperó al candado de la cuenta"
    finally:
        transaction.rollback()
        connection.close()
    worker.join(timeout=10)
    assert answers[0].status_code == 200
