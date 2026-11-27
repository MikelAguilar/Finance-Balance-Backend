"""La sincronización: lo que manda la app (cursor y cambios) y cómo se decide cada cambio.

Una subida trae registros completos. Cada uno es nuevo (`key`, la clave que generó la app) o una
edición (`id` del servidor y `base_version`, la versión sobre la que editó). `change_id` identifica
la edición: si llega dos veces, la segunda no se aplica.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import (
    Card,
    MonthlyIncome,
    Movement,
    parse_card,
    parse_monthly_income,
    parse_movement,
)
from finance_service.domain.rules import (
    MAX_BIGINT,
    Fields,
    iso_instant,
    items,
    mapping,
    uuid_text,
    whole_number,
)

MAX_CHANGES = 500
# `version` es INTEGER en la base.
MAX_VERSION = 2**31 - 1
CHANGE_FIELDS = ("key", "id", "base_version", "change_id", "updated_at", "data")


@dataclass(frozen=True)
class New:
    key: UUID


@dataclass(frozen=True)
class Edit:
    id: UUID
    base_version: int


@dataclass(frozen=True)
class CardRef:
    """La tarjeta de un movimiento: por su id, o por la clave de la app si se creó sin red."""

    id: UUID | None = None
    key: UUID | None = None


@dataclass(frozen=True)
class Change[T]:
    target: New | Edit
    change_id: UUID
    updated_at: datetime
    value: T
    card: CardRef | None = None


@dataclass(frozen=True)
class Upload:
    sent_at: datetime
    cards: list[Change[Card]]
    movements: list[Change[Movement]]
    incomes: list[Change[MonthlyIncome]]


@dataclass(frozen=True)
class SyncRequest:
    cursor: int
    upload: Upload | None


# --- Lectura -------------------------------------------------------------------------------------


def parse_target(fields: Fields) -> New | Edit:
    if fields.optional("id") is None:
        return New(key=uuid_text(fields.required("key"), "key"))
    if fields.optional("key") is not None:
        raise InvalidField("key", "not_allowed")
    return Edit(
        id=uuid_text(fields.required("id"), "id"),
        base_version=whole_number(fields.required("base_version"), "base_version", 1, MAX_VERSION),
    )


def parse_card_ref(value: object) -> CardRef:
    data = mapping(value, "card")
    fields = Fields({f"card.{name}": item for name, item in data.items()}, ("card.id", "card.key"))
    if fields.optional("card.id") is None:
        if fields.optional("card.key") is None:
            raise InvalidField("card", "required")
        return CardRef(key=uuid_text(fields.required("card.key"), "card.key"))
    if fields.optional("card.key") is not None:
        raise InvalidField("card.key", "not_allowed")
    return CardRef(id=uuid_text(fields.required("card.id"), "card.id"))


def parse_change[T](
    value: object, parse: Callable[[Mapping[str, object]], T], *, with_card: bool
) -> Change[T]:
    fields = Fields(mapping(value, "change"), CHANGE_FIELDS + (("card",) if with_card else ()))
    target = parse_target(fields)
    change_id = uuid_text(fields.required("change_id"), "change_id")
    updated_at = iso_instant(fields.required("updated_at"), "updated_at")
    data = mapping(fields.required("data"), "data")
    card = parse_card_ref(fields.required("card")) if with_card else None
    return Change(target, change_id, updated_at, parse(data), card)


def parse_table[T](
    values: list[object],
    table: str,
    parse: Callable[[Mapping[str, object]], T],
    with_card: bool = False,
) -> list[Change[T]]:
    parsed = []
    for index, value in enumerate(values):
        try:
            parsed.append(parse_change(value, parse, with_card=with_card))
        except InvalidField as error:
            raise error.at(f"changes.{table}[{index}]") from None
    return parsed


def parse_upload(data: Mapping[str, object], now: datetime) -> Upload:
    tables = ("cards", "movements", "monthly_income")
    try:
        changes = Fields(mapping(data["changes"], "changes"), tables)
        lists = {table: items(changes.optional(table, []), table) for table in tables}
    except InvalidField as error:
        raise error if error.field == "changes" else error.at("changes") from None
    sent_at = iso_instant(Fields(data, data).required("sent_at"), "sent_at")
    if sum(len(values) for values in lists.values()) > MAX_CHANGES:
        raise InvalidField("changes", "too_many")
    upload = Upload(
        sent_at=sent_at,
        cards=parse_table(lists["cards"], "cards", parse_card),
        movements=parse_table(
            lists["movements"], "movements", lambda value: parse_movement(value, now), True
        ),
        incomes=parse_table(lists["monthly_income"], "monthly_income", parse_monthly_income),
    )
    reject_duplicates(upload)
    return upload


def parse_sync_request(data: object, now: datetime) -> SyncRequest:
    """Lee `{"cursor": n}` y, si la app tiene cambios, `sent_at` y `changes`."""
    body = mapping(data, "body")
    fields = Fields(body, ("cursor", "sent_at", "changes"))
    cursor = whole_number(fields.required("cursor"), "cursor", 0, MAX_BIGINT)
    if "changes" not in body:
        return SyncRequest(cursor=cursor, upload=None)
    return SyncRequest(cursor=cursor, upload=parse_upload(body, now))


# --- Repetidos -----------------------------------------------------------------------------------


def reject_duplicates(upload: Upload) -> None:
    """Un registro va una sola vez por subida y cada edición tiene su propio change_id."""
    change_ids: set[UUID] = set()
    tables = (("cards", upload.cards), ("movements", upload.movements))
    for table, changes in (*tables, ("monthly_income", upload.incomes)):
        keys: set[UUID] = set()
        ids: set[UUID] = set()
        for index, change in enumerate(changes):
            path = f"changes.{table}[{index}]"
            target = change.target
            if isinstance(target, New):
                if target.key in keys:
                    raise InvalidField("key", "duplicate", path)
                keys.add(target.key)
            else:
                if target.id in ids:
                    raise InvalidField("id", "duplicate", path)
                ids.add(target.id)
            if change.change_id in change_ids:
                raise InvalidField("change_id", "duplicate", path)
            change_ids.add(change.change_id)


# --- La decisión ---------------------------------------------------------------------------------


class Outcome(StrEnum):
    APPLY = "apply"
    ALREADY_APPLIED = "already_applied"
    LOST = "lost"


@dataclass(frozen=True)
class Current:
    """Lo que la decisión necesita saber del registro que ya está en el servidor."""

    version: int
    updated_at: datetime
    last_change_id: UUID | None


def corrected_time(updated_at: datetime, sent_at: datetime, now: datetime) -> datetime:
    """La hora de edición en el reloj del servidor.

    Se le suma la diferencia entre el reloj del servidor y el del teléfono al enviar. Una edición
    posterior al envío solo puede venir de un reloj que se atrasó: cuenta como hecha al enviar.
    """
    return min(updated_at, sent_at) + (now - sent_at)


def decide(
    change_id: UUID, base_version: int | None, edited_at: datetime, current: Current
) -> Outcome:
    """Qué pasa con un cambio sobre un registro que ya está en el servidor. Un registro que el
    servidor no tiene se crea antes de llegar aquí."""
    if change_id == current.last_change_id:
        return Outcome.ALREADY_APPLIED
    if base_version == current.version:
        return Outcome.APPLY
    # Dos ediciones concurrentes: gana la más reciente. Si empatan, se queda lo que llegó primero.
    return Outcome.APPLY if edited_at > current.updated_at else Outcome.LOST
