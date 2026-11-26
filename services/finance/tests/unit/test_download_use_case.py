from contextlib import contextmanager
from uuid import UUID, uuid4

from finance_service.application.download import Download
from finance_service.domain.download import Stored


class CountingStore:
    """Un almacén que guarda cuántos registros le pidieron de cada tabla."""

    def __init__(self) -> None:
        self.limits: dict[str, int | None] = {}

    def lock_account(self, user_id: UUID) -> None:
        pass

    def _changed(self, table: str, limit: int | None) -> list[Stored]:
        self.limits[table] = limit
        return []

    def cards_changed(self, user_id: UUID, after: int, limit: int) -> list[Stored]:
        return self._changed("cards", limit)

    def movements_changed(self, user_id: UUID, after: int, limit: int) -> list[Stored]:
        return self._changed("movements", limit)

    def incomes_changed(self, user_id: UUID, after: int, limit: int) -> list[Stored]:
        return self._changed("incomes", limit)

    def cards_changed_among(self, user_id: UUID, ids: set[UUID], after: int) -> list[Stored]:
        return []


def test_each_page_reads_at_most_one_page_plus_one_record_from_each_table() -> None:
    # Con uno de más se sabe si queda otra página; sin límite, cada página leería la cuenta entera.
    store = CountingStore()

    @contextmanager
    def open_store():
        yield store

    Download(open_store, page_size=7)(uuid4(), 0)

    assert store.limits == {"cards": 8, "movements": 8, "incomes": 8}
