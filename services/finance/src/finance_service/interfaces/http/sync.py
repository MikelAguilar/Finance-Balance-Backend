"""`POST /sync`: el único endpoint de finanzas. El gateway lo publica en /finance/sync.

El cuerpo lo validan las funciones parse_* del dominio (las mismas reglas que prueban los casos
compartidos con la app), no un modelo de Pydantic: así cada regla vive en un solo lugar.
"""

from collections.abc import Callable
from dataclasses import asdict
from datetime import timedelta, timezone
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status

from finance_service.application.sync import Result, SyncResult
from finance_service.domain.download import CardMovement, Page, Stored
from finance_service.domain.errors import InvalidField
from finance_service.domain.model import (
    Card,
    Installment,
    MonthlyIncome,
    Movement,
    Payment,
    kind_name,
)

router = APIRouter(tags=["finance"])


def current_user(x_user_id: Annotated[str | None, Header()] = None) -> UUID:
    """El usuario que verificó el gateway. Finanzas no publica puerto: solo el gateway llega aquí,
    y antes borra cualquier X-User-Id que venga de fuera. Sin él (o mal formado) es un 401."""
    try:
        return UUID(x_user_id)
    except (TypeError, ValueError):  # TypeError: no vino
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
    kind = movement.kind
    data["kind"] = kind_name(kind)
    if isinstance(kind, Installment):
        # La tasa viaja como texto: un número de JSON es float y perdería precisión.
        data |= {"months": kind.months, "monthly_rate": f"{kind.monthly_rate:f}"}
    if isinstance(kind, Payment):
        data["payment_source"] = kind.source.value
    return data


def record[T](stored: Stored[T], data: dict[str, object]) -> dict[str, object]:
    deleted_at = stored.deleted_at
    return {
        "id": str(stored.id),
        "key": str(stored.key),
        "version": stored.version,
        "deleted_at": None if deleted_at is None else deleted_at.isoformat(),
        "data": data,
    }


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


def result_json[T](result: Result[T], to_json: Callable[[Stored[T]], dict[str, object]]) -> dict:
    return {
        "change_id": str(result.change_id),
        "status": "applied" if result.applied else "lost",
        "record": to_json(result.record),
    }


def sync_json(answer: SyncResult) -> dict[str, object]:
    results = answer.results
    return {
        # En el orden en que llegaron: la app reconoce cada uno por su change_id y toma del
        # registro el id y la versión que le asignó el servidor.
        "results": {
            "cards": [result_json(result, card_json) for result in results.cards],
            "movements": [result_json(result, movement_json) for result in results.movements],
            "monthly_income": [result_json(result, income_json) for result in results.incomes],
        },
        **page_json(answer.page),
    }


@router.post("/sync")
def sync(
    request: Request,
    user_id: Annotated[UUID, Depends(current_user)],
    body: Annotated[Any, Body()],
) -> dict[str, object]:
    try:
        answer = request.app.state.sync(user_id, body)
    except InvalidField as error:
        # Si una parte de la subida no vale, no se guarda nada (la transacción se deshace).
        detail = {"path": error.path, "field": error.field, "rule": error.rule}
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail) from None
    return sync_json(answer)
