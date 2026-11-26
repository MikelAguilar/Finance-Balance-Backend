from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from finance_service.domain.download import CardMovement, Page, Stored
from finance_service.domain.model import (
    Card,
    Installment,
    MonthlyIncome,
    Movement,
    Normal,
    OccurredAt,
    Payment,
    PaymentSource,
    ReviewStatus,
    parse_card,
    parse_monthly_income,
    parse_movement,
)
from finance_service.interfaces.http.sync import card_json, income_json, movement_json

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)
USER = uuid4()
CARD = Card(
    name="Oro",
    cut_day=5,
    personal_limit_cents=1_000_000,
    bank_limit_cents=None,
    used_at_creation_cents=0,
    installments_count_against_limit=False,
)
# 03:00 en Madrid (UTC+1): el instante se guarda en UTC y el offset aparte.
OCCURRED = OccurredAt(at=datetime(2026, 11, 26, 2, tzinfo=UTC), offset_minutes=60)


def movement(kind: object) -> Movement:
    return Movement(
        amount_cents=45_050,
        occurred=OCCURRED,
        kind=kind,
        review_status=ReviewStatus.CONFIRMED,
        owner_cut=date(2026, 12, 5),
    )


def stored[T](value: T) -> Stored[T]:
    return Stored(id=uuid4(), key=uuid4(), version=3, seq=7, value=value)


class FakeDownload:
    def __init__(self, page: Page) -> None:
        self.page = page
        self.calls: list[tuple[UUID, int]] = []

    def __call__(self, user_id: UUID, after: int) -> Page:
        self.calls.append((user_id, after))
        return self.page


@pytest.fixture
def client(make_client) -> tuple[TestClient, FakeDownload]:
    client = make_client("development")
    fake = FakeDownload(Page([], [], [], cursor=9, has_more=False))
    client.app.state.download = fake
    return client, fake


# --- Lo que baja se puede volver a subir ---------------------------------------------------------


def test_a_downloaded_card_reads_back_as_the_same_card() -> None:
    json = card_json(stored(CARD))
    assert parse_card(json["data"]) == CARD


@pytest.mark.parametrize(
    "kind",
    [
        Normal(),
        Installment(months=12, monthly_rate=Decimal("0.015")),
        Installment(months=3, monthly_rate=Decimal("0")),
        Payment(source=PaymentSource.CASH),
    ],
)
def test_a_downloaded_movement_reads_back_as_the_same_movement(kind: object) -> None:
    json = movement_json(stored(CardMovement(card_id=uuid4(), movement=movement(kind))))
    assert parse_movement(json["data"], NOW) == movement(kind)


def test_a_downloaded_income_reads_back_as_the_same_income() -> None:
    json = income_json(stored(MonthlyIncome(2_500_000)))
    assert parse_monthly_income(json["data"]) == MonthlyIncome(2_500_000)


def test_a_movement_shows_the_time_where_it_was_bought_and_its_card() -> None:
    card_id = uuid4()
    record = stored(CardMovement(card_id=card_id, movement=movement(Normal())))

    json = movement_json(record)

    assert json["data"]["occurred_at"] == "2026-11-26T03:00:00+01:00"
    assert json["card"] == {"id": str(card_id)}
    assert (json["id"], json["key"], json["version"]) == (str(record.id), str(record.key), 3)


def test_the_rate_travels_as_exact_text() -> None:
    kind = Installment(months=12, monthly_rate=Decimal("0.015000"))
    json = movement_json(stored(CardMovement(card_id=uuid4(), movement=movement(kind))))
    assert json["data"]["monthly_rate"] == "0.015000"


# --- La llamada ----------------------------------------------------------------------------------


def test_the_download_is_for_the_user_the_gateway_verified(client) -> None:
    client, fake = client

    response = client.post("/sync", json={"cursor": 4}, headers={"X-User-Id": str(USER)})

    assert response.status_code == 200
    assert response.json() == {
        "cursor": 9,
        "has_more": False,
        "changes": {"cards": [], "movements": [], "monthly_income": []},
    }
    assert fake.calls == [(USER, 4)]


@pytest.mark.parametrize("headers", [{}, {"X-User-Id": ""}, {"X-User-Id": "no-es-un-uuid"}])
def test_without_a_verified_user_it_is_a_401(client, headers: dict) -> None:
    client, fake = client

    response = client.post("/sync", json={"cursor": 0}, headers=headers)

    assert response.status_code == 401
    assert fake.calls == []


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ({"cursor": -1}, {"field": "cursor", "rule": "range"}),
        ({}, {"field": "cursor", "rule": "required"}),
        ([1], {"field": "body", "rule": "type"}),
    ],
)
def test_an_invalid_body_is_a_422_that_names_the_field_and_the_rule(
    client, body: object, detail: dict
) -> None:
    client, fake = client

    response = client.post("/sync", json=body, headers={"X-User-Id": str(USER)})

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert fake.calls == []


def test_the_user_is_checked_before_the_body(client) -> None:
    # Quien no pasó por el gateway no se entera de qué cuerpo es válido.
    client, _ = client
    assert client.post("/sync", json={"cursor": -1}).status_code == 401
