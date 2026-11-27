from dataclasses import replace
from uuid import UUID

from finance_service.application.ports import OpenStore
from finance_service.domain.download import Page, cut_page, missing_cards

PAGE_SIZE = 500


class Download:
    """Lo que cambió en la cuenta después del cursor, una página a la vez."""

    def __init__(self, open_store: OpenStore, page_size: int = PAGE_SIZE) -> None:
        self._open_store = open_store
        self._page_size = page_size

    def __call__(self, user_id: UUID, after: int) -> Page:
        with self._open_store() as store:
            # Con el candado, nadie escribe en la cuenta mientras se lee: las tres consultas ven
            # lo mismo y ningún número de cambio queda atrás del cursor sin haberse enviado.
            store.lock_account(user_id)
            # Uno de más por tabla: así se sabe si queda otra página.
            fetch = self._page_size + 1
            page = cut_page(
                store.cards_changed(user_id, after, fetch),
                store.movements_changed(user_id, after, fetch),
                store.incomes_changed(user_id, after, fetch),
                after=after,
                limit=self._page_size,
            )
            # Una tarjeta editada después de su movimiento viaja con él: la app nunca recibe un
            # movimiento sin su tarjeta. Las de antes del cursor ya las tiene.
            extra = store.cards_changed_among(user_id, missing_cards(page), page.cursor)
            return replace(page, cards=page.cards + extra)
