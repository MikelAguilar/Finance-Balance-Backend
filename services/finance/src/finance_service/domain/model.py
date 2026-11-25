"""Datos fuente de finanzas. Cada entidad se valida al construirse: no existe una inválida.

Los cálculos (cortes, mensualidades, medidores) viven en la app; aquí solo están las reglas de
entrada que el servidor también debe hacer cumplir.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from finance_service.domain.errors import InvalidField
from finance_service.domain.rules import MAX_CENTS, Fields, cents, flag, text, whole_number

__all__ = ["MAX_CENTS", "Card", "parse_card"]

CARD_NAME_MAX_LENGTH = 50


@dataclass(frozen=True)
class Card:
    name: str
    cut_day: int
    personal_limit_cents: int | None
    bank_limit_cents: int | None
    used_at_creation_cents: int
    installments_count_against_limit: bool

    def __post_init__(self) -> None:
        text(self.name, "name", max_length=CARD_NAME_MAX_LENGTH)
        whole_number(self.cut_day, "cut_day", 1, 31)
        for field in ("personal_limit_cents", "bank_limit_cents"):
            limit = getattr(self, field)
            if limit is not None:
                cents(limit, field, minimum=1)
        if self.personal_limit_cents is None and self.bank_limit_cents is None:
            raise InvalidField("limits", "at_least_one")
        cents(self.used_at_creation_cents, "used_at_creation_cents", minimum=0)
        flag(self.installments_count_against_limit, "installments_count_against_limit")


def parse_card(data: Mapping[str, object]) -> Card:
    """Lee la tarjeta que manda la app. Solo toma los campos: Card los valida al construirse."""
    fields = Fields(data, Card.__dataclass_fields__)
    name = fields.required("name")
    return Card(
        name=name.strip() if isinstance(name, str) else name,
        cut_day=fields.required("cut_day"),
        personal_limit_cents=fields.optional("personal_limit_cents"),
        bank_limit_cents=fields.optional("bank_limit_cents"),
        used_at_creation_cents=fields.required("used_at_creation_cents"),
        installments_count_against_limit=fields.optional("installments_count_against_limit", True),
    )
