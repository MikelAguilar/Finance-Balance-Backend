"""La descarga por páginas contra PostgreSQL real, de la llamada HTTP a la base."""

import json
import threading
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from finance_service.application.download import PAGE_SIZE, Download
from finance_service.config import Settings
from finance_service.infrastructure.repositories import sql_store
from finance_service.main import create_app

EXAMPLES = Path(__file__).parents[2] / "contract" / "sync-examples.json"


@pytest.fixture
def client(engine, database_url: str) -> Iterator[TestClient]:
    # Con `with`, la app arranca y se apaga: al apagarse cierra sus conexiones.
    with TestClient(create_app(Settings(database_url=database_url))) as client:
        yield client


@pytest.fixture
def download_in_pages_of(engine):
    def _make(size: int) -> Download:
        return Download(sql_store(sessionmaker(engine)), page_size=size)

    return _make


def sync(client: TestClient, user_id: UUID, cursor: int) -> dict:
    response = client.post("/sync", json={"cursor": cursor}, headers={"X-User-Id": str(user_id)})
    assert response.status_code == 200, response.text
    return response.json()


def touch(engine, table: str, id: UUID) -> None:
    """Una edición: la fila toma el siguiente número de cambio."""
    with engine.begin() as connection:
        connection.execute(
            text(
                f"UPDATE finance.{table} SET change_seq = nextval('finance.change_seq') "
                "WHERE id = :id"
            ),
            {"id": id},
        )


def ids(records: list) -> list:
    return [record.id for record in records]


# --- El contrato con la app ----------------------------------------------------------------------


@pytest.fixture
def numbers_from_one(engine) -> None:
    # Los ejemplos traen cursores fijos: la secuencia empieza en 1 para esta prueba.
    with engine.begin() as connection:
        connection.execute(text("ALTER SEQUENCE finance.change_seq RESTART WITH 1"))


def test_the_examples_shared_with_the_app_are_what_the_server_answers(
    client, insert, make_card, make_movement, make_income, numbers_from_one
) -> None:
    examples = json.loads(EXAMPLES.read_text(encoding="utf-8"))["examples"]
    user = uuid4()
    # ids del servidor terminan en 1…4; claves de la app en a1…a4.
    uid = "00000000-0000-4000-8000-00000000000{}".format
    key = "00000000-0000-4000-8000-0000000000a{}".format
    card = make_card(id=UUID(uid(1)), idempotency_key=UUID(key(1)), user_id=user, version=2)
    insert("cards", card)
    insert(
        "movements",
        make_movement(
            card,
            id=UUID(uid(2)),
            idempotency_key=UUID(key(2)),
            amount_cents=1_200_000,
            occurred_at=datetime(2026, 11, 21, 1, 30, tzinfo=UTC),
            occurred_offset_minutes=-360,
            kind="installment",
            months=12,
            monthly_rate=Decimal("0.015"),
            review_status="confirmed",
        ),
    )
    insert(
        "movements",
        make_movement(
            card,
            id=UUID(uid(3)),
            idempotency_key=UUID(key(3)),
            amount_cents=300_000,
            occurred_at=datetime(2026, 11, 26, 2, tzinfo=UTC),
            occurred_offset_minutes=60,
            kind="payment",
            payment_source="debit",
            owner_cut=date(2026, 12, 5),
        ),
    )
    insert(
        "monthly_income", make_income(id=UUID(uid(4)), idempotency_key=UUID(key(4)), user_id=user)
    )

    for example in examples:
        response = client.post("/sync", json=example["request"], headers={"X-User-Id": str(user)})
        assert response.json() == example["response"], example["name"]


# --- Cada cuenta ve lo suyo ----------------------------------------------------------------------


def test_an_account_never_downloads_another_accounts_records(
    client, insert, make_card, make_movement, make_income
) -> None:
    mine, theirs = make_card(), make_card()
    insert("cards", mine)
    insert("cards", theirs)
    insert("movements", make_movement(theirs))
    insert("monthly_income", make_income(user_id=theirs["user_id"]))

    changes = sync(client, mine["user_id"], 0)["changes"]

    assert [card["id"] for card in changes["cards"]] == [str(mine["id"])]
    assert changes["movements"] == changes["monthly_income"] == []


def test_a_new_account_downloads_nothing_and_keeps_its_cursor(client) -> None:
    assert sync(client, uuid4(), 0) == {
        "cursor": 0,
        "has_more": False,
        "changes": {"cards": [], "movements": [], "monthly_income": []},
    }


def test_after_the_cursor_only_what_changed_since(client, engine, insert, make_card) -> None:
    old, edited = make_card(), make_card()
    edited["user_id"] = old["user_id"]
    insert("cards", old)
    insert("cards", edited)
    cursor = sync(client, old["user_id"], 0)["cursor"]
    touch(engine, "cards", edited["id"])

    answer = sync(client, old["user_id"], cursor)

    assert [card["id"] for card in answer["changes"]["cards"]] == [str(edited["id"])]
    assert answer["cursor"] > cursor


# --- Páginas -------------------------------------------------------------------------------------


def test_a_full_page_is_500_records_and_says_there_are_more(client, engine, make_card) -> None:
    user = uuid4()
    rows = [make_card(user_id=user) for _ in range(PAGE_SIZE + 1)]
    with engine.begin() as connection:
        columns = ", ".join(rows[0])
        values = ", ".join(f":{column}" for column in rows[0])
        connection.execute(text(f"INSERT INTO finance.cards ({columns}) VALUES ({values})"), rows)

    first = sync(client, user, 0)
    last = sync(client, user, first["cursor"])

    assert (len(first["changes"]["cards"]), first["has_more"]) == (PAGE_SIZE, True)
    assert (len(last["changes"]["cards"]), last["has_more"]) == (1, False)


def test_pages_follow_the_order_of_the_changes_across_tables(
    download_in_pages_of, insert, make_card, make_movement, make_income
) -> None:
    card = make_card()
    movement = make_movement(card)
    income = make_income(user_id=card["user_id"])
    insert("cards", card)
    insert("movements", movement)
    insert("monthly_income", income)
    download = download_in_pages_of(2)

    first = download(card["user_id"], 0)
    second = download(card["user_id"], first.cursor)

    assert (ids(first.cards), ids(first.movements), ids(first.incomes)) == (
        [card["id"]],
        [movement["id"]],
        [],
    )
    assert first.has_more
    assert (ids(second.cards), ids(second.movements), ids(second.incomes)) == (
        [],
        [],
        [income["id"]],
    )
    assert not second.has_more


def test_a_card_edited_after_its_movement_travels_with_it(
    download_in_pages_of, engine, insert, make_card, make_movement
) -> None:
    card, other = make_card(), make_card()
    other["user_id"] = card["user_id"]
    insert("cards", card)
    insert("cards", other)
    movement = make_movement(card)
    insert("movements", movement)
    touch(engine, "cards", card["id"])  # Ahora la tarjeta va después del movimiento.
    download = download_in_pages_of(2)

    first = download(card["user_id"], 0)
    second = download(card["user_id"], first.cursor)

    # La página trae `other` y el movimiento; su tarjeta viaja con él aunque le toque después.
    assert ids(first.cards) == [other["id"], card["id"]]
    assert ids(first.movements) == [movement["id"]]
    assert ids(second.cards) == [card["id"]]
    assert first.cards[1] == second.cards[0]


def test_a_card_sent_in_an_earlier_page_does_not_travel_again(
    download_in_pages_of, insert, make_card, make_movement
) -> None:
    card = make_card()
    insert("cards", card)
    insert("movements", make_movement(card))
    download = download_in_pages_of(1)

    first = download(card["user_id"], 0)
    second = download(card["user_id"], first.cursor)

    assert (ids(first.cards), len(second.movements), second.cards) == ([card["id"]], 1, [])


# --- Un escritor por cuenta ----------------------------------------------------------------------


def hold_account_lock(engine, user_id: UUID):
    connection = engine.connect()
    transaction = connection.begin()
    connection.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:user_id, 0))"),
        {"user_id": str(user_id)},
    )
    return connection, transaction


def test_a_download_waits_while_another_sync_of_the_same_account_is_running(
    engine, download_in_pages_of, insert, make_card
) -> None:
    card = make_card()
    insert("cards", card)
    download = download_in_pages_of(PAGE_SIZE)
    connection, transaction = hold_account_lock(engine, card["user_id"])
    results: list = []
    worker = threading.Thread(target=lambda: results.append(download(card["user_id"], 0)))
    try:
        worker.start()
        worker.join(timeout=1)
        assert worker.is_alive(), "la descarga no esperó al candado de la cuenta"
    finally:
        transaction.rollback()
        connection.close()
    worker.join(timeout=10)
    assert ids(results[0].cards) == [card["id"]]


def test_another_account_does_not_wait(engine, download_in_pages_of, insert, make_card) -> None:
    card = make_card()
    insert("cards", card)
    connection, transaction = hold_account_lock(engine, uuid4())
    try:
        assert ids(download_in_pages_of(PAGE_SIZE)(card["user_id"], 0).cards) == [card["id"]]
    finally:
        transaction.rollback()
        connection.close()


# --- La base reinicia ----------------------------------------------------------------------------


def test_after_the_database_drops_its_connections_the_next_sync_works(engine, database_url) -> None:
    # Como si PostgreSQL se reiniciara: las conexiones que la app tiene guardadas ya no sirven. Solo
    # se cortan las de esta app (por su nombre): la base la comparten otras pruebas.
    name = "finanzas-reinicio"
    separator = "&" if "?" in database_url else "?"
    settings = Settings(database_url=f"{database_url}{separator}application_name={name}")
    user = uuid4()
    with TestClient(create_app(settings)) as client:
        sync(client, user, 0)
        with engine.begin() as connection:
            killed = connection.execute(
                text(
                    "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity "
                    "WHERE application_name = :name"
                ),
                {"name": name},
            ).scalar()
        assert killed >= 1

        assert sync(client, user, 0)["cursor"] == 0
