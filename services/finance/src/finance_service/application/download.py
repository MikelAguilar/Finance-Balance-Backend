from dataclasses import replace
from uuid import UUID

from finance_service.application.ports import SyncStore
from finance_service.domain.download import Page, cut_page, missing_cards

PAGE_SIZE = 500


def read_page(store: SyncStore, user_id: UUID, after: int, page_size: int) -> Page:
    """Lo que cambió en la cuenta después del cursor, una página. Va con el candado tomado: las
    tres consultas ven lo mismo y ningún número de cambio queda atrás del cursor sin enviarse."""
    # Uno de más por tabla: así se sabe si queda otra página.
    fetch = page_size + 1
    page = cut_page(
        store.cards_changed(user_id, after, fetch),
        store.movements_changed(user_id, after, fetch),
        store.incomes_changed(user_id, after, fetch),
        after=after,
        limit=page_size,
    )
    # Una tarjeta editada después de su movimiento viaja con él: la app nunca recibe un
    # movimiento sin su tarjeta. Las de antes del cursor ya las tiene.
    extra = store.cards_changed_among(user_id, missing_cards(page), page.cursor)
    return replace(page, cards=page.cards + extra)
