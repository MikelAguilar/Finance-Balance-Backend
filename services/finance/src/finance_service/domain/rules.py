"""Reglas de entrada que comparten tarjetas, movimientos e ingreso."""

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from finance_service.domain.errors import InvalidField

# El dinero se guarda en centavos en un BIGINT de PostgreSQL: este es su máximo.
MAX_CENTS = 2**63 - 1


def whole_number(value: object, field: str, low: int, high: int) -> int:
    # bool hereda de int en Python (True == 1): un booleano nunca cuenta como número.
    if type(value) is not int:
        raise InvalidField(field, "type")
    if not low <= value <= high:
        raise InvalidField(field, "range")
    return value


def cents(value: object, field: str, *, minimum: int) -> int:
    return whole_number(value, field, minimum, MAX_CENTS)


def text(value: object, field: str, *, max_length: int) -> str:
    if not isinstance(value, str):
        raise InvalidField(field, "type")
    if not value.strip():
        raise InvalidField(field, "blank")
    if len(value) > max_length:
        raise InvalidField(field, "too_long")
    return value


def flag(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidField(field, "type")
    return value


class Fields:
    """Lee el dict que manda la app: rechaza campos que sobran y avisa de los que faltan."""

    def __init__(self, data: Mapping[str, object], allowed: Iterable[str]) -> None:
        unknown = sorted(set(data) - set(allowed))
        if unknown:
            raise InvalidField(unknown[0], "unknown")
        self._data = data

    def required(self, name: str) -> object:
        value = self._data.get(name)
        if value is None:
            raise InvalidField(name, "required")
        return value

    def optional(self, name: str, default: object = None) -> object:
        value = self._data.get(name)
        return default if value is None else value


def choice[E: StrEnum](options: type[E], value: object, field: str) -> E:
    if not isinstance(value, str):
        raise InvalidField(field, "type")
    try:
        return options(value)
    except ValueError:
        raise InvalidField(field, "range") from None


def iso_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise InvalidField(field, "type")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidField(field, "format") from None


def decimal_text(value: object, field: str) -> Decimal:
    """Un decimal exacto que llega como texto: un número de JSON es float y perdería precisión."""
    if not isinstance(value, str):
        raise InvalidField(field, "type")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise InvalidField(field, "format") from None
    if not number.is_finite():
        raise InvalidField(field, "format")
    return number
