"""`POST /finance/sync`: aplica lo que subió la app y devuelve lo que cambió desde su cursor."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from finance_service.application.download import PAGE_SIZE, read_page
from finance_service.application.ports import Existing, OpenStore, SyncStore, Table, Write
from finance_service.domain.download import CardMovement, Page, Stored
from finance_service.domain.errors import InvalidField
from finance_service.domain.model import Card, MonthlyIncome
from finance_service.domain.sync import (
    CardRef,
    Change,
    Edit,
    Outcome,
    Upload,
    corrected_time,
    decide,
    parse_sync_request,
)


@dataclass(frozen=True)
class Result[T]:
    """Cómo quedó un cambio: aplicado (o ya aplicado antes) o perdido, y el registro como está."""

    change_id: UUID
    applied: bool
    record: Stored[T]


@dataclass(frozen=True)
class Results:
    cards: list[Result[Card]]
    movements: list[Result[CardMovement]]
    incomes: list[Result[MonthlyIncome]]


@dataclass(frozen=True)
class SyncResult:
    results: Results
    page: Page


class Applier:
    """Aplica una subida, cambio por cambio, dentro de la transacción de la sincronización."""

    def __init__(self, store: SyncStore, user_id: UUID, upload: Upload, now: datetime) -> None:
        self._store = store
        self._user_id = user_id
        self._upload = upload
        self._now = now

    def apply_all(self) -> Results:
        # Primero las tarjetas: un movimiento puede apuntar a una que se crea en esta subida.
        upload = self._upload
        cards = [self._apply(Table.CARDS, i, c, c.value) for i, c in enumerate(upload.cards)]
        movements = [self._apply_movement(i, c) for i, c in enumerate(upload.movements)]
        incomes = [self._apply(Table.INCOMES, i, c, c.value) for i, c in enumerate(upload.incomes)]
        return Results(cards, movements, incomes)

    def _apply_movement(self, index: int, change: Change[Any]) -> Result[Any]:
        if change.value is None:
            # Un borrado no trae tarjeta: el movimiento conserva la suya.
            return self._apply(Table.MOVEMENTS, index, change, None)
        # El dominio ya exigió la tarjeta de cada movimiento que trae datos: aquí siempre viene.
        card_id = self._card_id(change.card, f"changes.{Table.MOVEMENTS}[{index}]")
        return self._apply(Table.MOVEMENTS, index, change, CardMovement(card_id, change.value))

    def _card_id(self, ref: CardRef, path: str) -> UUID:
        if ref.id is not None:
            found = self._store.find(Table.CARDS, self._user_id, id=ref.id)
            field = "card.id"
        else:
            found = self._store.find(Table.CARDS, self._user_id, key=ref.key)
            field = "card.key"
        if found is None:
            raise InvalidField(field, "not_found", path)
        return found.stored.id

    def _existing(self, table: Table, change: Change[Any], path: str) -> Existing[Any] | None:
        target = change.target
        if isinstance(target, Edit):
            found = self._store.find(table, self._user_id, id=target.id)
            if found is None:
                # De otra cuenta responde igual que inexistente: no revela nada.
                raise InvalidField("id", "not_found", path)
            return found
        found = self._store.find(table, self._user_id, key=target.key)
        if found is None and table is Table.INCOMES:
            # Un ingreso vigente por cuenta: crear otro es un choque con el que ya está.
            return self._store.current_income(self._user_id)
        return found

    def _apply(self, table: Table, index: int, change: Change[Any], value: Any) -> Result[Any]:
        existing = self._existing(table, change, f"changes.{table}[{index}]")
        target = change.target
        edited_at = corrected_time(change.updated_at, self._upload.sent_at, self._now)
        write = Write(value, edited_at, change.change_id, self._now)
        if existing is None:
            # Un registro nuevo que el servidor no tiene (una edición sin registro ya fue
            # not_found, así que aquí el destino siempre es una clave).
            record = self._store.create(table, self._user_id, target.key, write)
            return Result(change.change_id, True, record)
        base_version = target.base_version if isinstance(target, Edit) else None
        outcome = decide(
            change.change_id, base_version, edited_at, existing.current, deleting=value is None
        )
        if outcome is Outcome.APPLY:
            version = existing.current.version + 1
            record = self._store.update(table, existing.stored.id, version, write)
        else:
            record = existing.stored
        return Result(change.change_id, outcome is not Outcome.LOST, record)


class Sync:
    def __init__(
        self,
        open_store: OpenStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        page_size: int = PAGE_SIZE,
    ) -> None:
        self._open_store = open_store
        self._clock = clock
        self._page_size = page_size

    def __call__(self, user_id: UUID, body: object) -> SyncResult:
        now = self._clock()
        request = parse_sync_request(body, now)
        with self._open_store() as store:
            # Un escritor por cuenta: subida y descarga ven la cuenta quieta.
            store.lock_account(user_id)
            upload = request.upload
            results = (
                Results([], [], [])
                if upload is None
                else Applier(store, user_id, upload, now).apply_all()
            )
            page = read_page(store, user_id, request.cursor, self._page_size)
        return SyncResult(results, page)
