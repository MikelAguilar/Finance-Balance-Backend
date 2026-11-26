from contextlib import AbstractContextManager
from typing import Protocol
from uuid import UUID

from finance_service.domain.download import CardMovement, Stored
from finance_service.domain.model import Card, MonthlyIncome


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


class OpenStore(Protocol):
    def __call__(self) -> AbstractContextManager[SyncStore]: ...
