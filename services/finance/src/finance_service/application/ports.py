from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID

from finance_service.domain.download import CardMovement, Stored
from finance_service.domain.model import Card, MonthlyIncome
from finance_service.domain.sync import Current


class Table(StrEnum):
    CARDS = "cards"
    MOVEMENTS = "movements"
    INCOMES = "monthly_income"


@dataclass(frozen=True)
class Existing[T]:
    """Un registro que ya está en el servidor y lo que la decisión necesita saber de él."""

    stored: Stored[T]
    current: Current


@dataclass(frozen=True)
class Write[T]:
    """Lo que se guarda al aplicar un cambio."""

    # None: borrar el registro.
    value: T | None
    # La hora de edición del teléfono, ya corregida con el reloj del servidor.
    updated_at: datetime
    change_id: UUID
    now: datetime


class SyncStore(Protocol):
    """Los datos de finanzas dentro de una transacción. Lo que cambió va por número de cambio."""

    def lock_account(self, user_id: UUID) -> None:
        """Un escritor por cuenta: espera a que termine otra sincronización de la misma cuenta."""

    def cards_changed(self, user_id: UUID, after: int, limit: int) -> list[Stored[Card]]: ...

    def movements_changed(
        self, user_id: UUID, after: int, limit: int
    ) -> list[Stored[CardMovement]]: ...

    def incomes_changed(
        self, user_id: UUID, after: int, limit: int
    ) -> list[Stored[MonthlyIncome]]: ...

    def cards_changed_among(
        self, user_id: UUID, ids: set[UUID], after: int
    ) -> list[Stored[Card]]: ...

    def find(
        self, table: Table, user_id: UUID, *, id: UUID | None = None, key: UUID | None = None
    ) -> Existing[Any] | None:
        """El registro de la cuenta con ese id (o esa clave de la app); de otra cuenta, None."""

    def current_income(self, user_id: UUID) -> Existing[MonthlyIncome] | None: ...

    def create(self, table: Table, user_id: UUID, key: UUID, write: Write[Any]) -> Stored[Any]: ...

    def update(self, table: Table, id: UUID, version: int, write: Write[Any]) -> Stored[Any]:
        """Escribe sobre un registro que find ya devolvió para la cuenta."""


class OpenStore(Protocol):
    def __call__(self) -> AbstractContextManager[SyncStore]: ...
