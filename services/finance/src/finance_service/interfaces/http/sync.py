"""`POST /sync`: el único endpoint de finanzas. El gateway lo publica en /finance/sync.

El cuerpo lo validan las funciones parse_* del dominio (las mismas reglas que prueban los casos
compartidos con la app), no un modelo de Pydantic: así cada regla vive en un solo lugar.
"""

from dataclasses import asdict
from datetime import timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status

from finance_service.domain.download import CardMovement, Page, Stored, parse_download_request
from finance_service.domain.errors import InvalidField
from finance_service.domain.model import (
    Card,
    Installment,
    KindName,
    MonthlyIncome,
    Movement,
    Payment,
)

router = APIRouter(tags=["finance"])


def current_user(x_user_id: Annotated[str, Header()] = "") -> UUID:
    """El usuario que verificó el gateway. Finanzas no publica puerto: solo el gateway llega aquí,
    y antes borra cualquier X-User-Id que venga de fuera. Sin él (o mal formado) es un 401."""
    try:
        return UUID(x_user_id)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED) from None


# --- Del dominio al JSON que lee la app ----------------------------------------------------------
# Cada `data` tiene la misma forma que la app manda al crear o editar: lo que baja se puede volver
# a subir tal cual.


def movement_data(movement: Movement) -> dict[str, object]:
    local = timezone(timedelta(minutes=movement.occurred.offset_minutes))
    data: dict[str, object] = {
        "amount_cents": movement.amount_cents,
        "occurred_at": movement.occurred.at.astimezone(local).isoformat(),
        "review_status": movement.review_status.value,
        "owner_cut": movement.owner_cut.isoformat(),
    }
    match movement.kind:
        case Installment(months=months, monthly_rate=rate):
            # La tasa viaja como texto: un número de JSON es float y perdería precisión.
            data |= {"kind": KindName.INSTALLMENT, "months": months, "monthly_rate": f"{rate:f}"}
        case Payment(source=source):
            data |= {"kind": KindName.PAYMENT, "payment_source": source.value}
        case _:
            data |= {"kind": KindName.NORMAL}
    return data


def record[T](stored: Stored[T], data: dict[str, object]) -> dict[str, object]:
    return {"id": str(stored.id), "key": str(stored.key), "version": stored.version, "data": data}


def card_json(stored: Stored[Card]) -> dict[str, object]:
    return record(stored, asdict(stored.value))


def movement_json(stored: Stored[CardMovement]) -> dict[str, object]:
    return {
        **record(stored, movement_data(stored.value.movement)),
        "card": {"id": str(stored.value.card_id)},
    }


def income_json(stored: Stored[MonthlyIncome]) -> dict[str, object]:
    return record(stored, asdict(stored.value))


def page_json(page: Page) -> dict[str, object]:
    return {
        "cursor": page.cursor,
        "has_more": page.has_more,
        # La app guarda primero las tarjetas: así cada movimiento encuentra la suya.
        "changes": {
            "cards": [card_json(card) for card in page.cards],
            "movements": [movement_json(movement) for movement in page.movements],
            "monthly_income": [income_json(income) for income in page.incomes],
        },
    }


@router.post("/sync")
def sync(
    request: Request,
    user_id: Annotated[UUID, Depends(current_user)],
    body: Annotated[Any, Body()],
) -> dict[str, object]:
    try:
        cursor = parse_download_request(body)
    except InvalidField as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, {"field": error.field, "rule": error.rule}
        ) from None
    return page_json(request.app.state.download(user_id, cursor))
