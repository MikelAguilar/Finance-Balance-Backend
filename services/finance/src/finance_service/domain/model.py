"""Datos fuente de finanzas. Cada entidad se valida al construirse: no existe una inválida.

Los cálculos (cortes, mensualidades, medidores) viven en la app; aquí solo están las reglas de
entrada que el servidor también debe hacer cumplir. Cada parse_* lee el dict que manda la app y
solo toma los campos: la validación la hace la entidad al construirse.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from finance_service.domain.errors import InvalidField
from finance_service.domain.rules import (
    MAX_CENTS,
    Fields,
    cents,
    choice,
    decimal_text,
    flag,
    iso_date,
    iso_instant,
    text,
    whole_number,
)

__all__ = [
    "MAX_CENTS",
    "Card",
    "Installment",
    "MonthlyIncome",
    "Movement",
    "Normal",
    "OccurredAt",
    "Payment",
    "PaymentSource",
    "ReviewStatus",
    "parse_card",
    "parse_monthly_income",
    "parse_movement",
    "parse_occurred_at",
]

CARD_NAME_MAX_LENGTH = 50
# Los offsets que existen en el mundo van de UTC−12:00 a UTC+14:00.
MIN_OFFSET_MINUTES, MAX_OFFSET_MINUTES = -720, 840
# Margen para relojes un poco adelantados; más allá, la fecha es un error.
MAX_AHEAD = timedelta(hours=24)
MAX_MONTHS = 120
# NUMERIC(7, 6) en la base: tasas mensuales de 0 a 0.999999.
RATE_DECIMALS = 6


# --- Tarjetas ------------------------------------------------------------------------------------


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


# --- Fecha del movimiento ------------------------------------------------------------------------


@dataclass(frozen=True)
class OccurredAt:
    """El instante de la compra (en UTC) y el offset del teléfono en ese momento.

    Con los dos, la app muestra cada compra con la hora del lugar donde se hizo.
    """

    at: datetime
    offset_minutes: int

    def __post_init__(self) -> None:
        if self.at.utcoffset() is None:
            raise InvalidField("occurred_at", "missing_offset")
        whole_number(self.offset_minutes, "occurred_at", MIN_OFFSET_MINUTES, MAX_OFFSET_MINUTES)


def parse_occurred_at(value: object, now: datetime) -> OccurredAt:
    """Lee la fecha ISO 8601 con offset que manda la app (`2026-11-26T03:00:00+01:00`)."""
    moment = iso_instant(value, "occurred_at")
    # iso_instant ya exigió el offset.
    minutes, seconds = divmod(int(moment.utcoffset().total_seconds()), 60)
    if seconds:
        raise InvalidField("occurred_at", "range")
    if moment > now + MAX_AHEAD:
        raise InvalidField("occurred_at", "future")
    return OccurredAt(at=moment.astimezone(UTC), offset_minutes=minutes)


# --- Movimientos ---------------------------------------------------------------------------------


class ReviewStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    CONFIRMED = "confirmed"


class PaymentSource(StrEnum):
    DEBIT = "debit"
    CASH = "cash"


class KindName(StrEnum):
    NORMAL = "normal"
    INSTALLMENT = "installment"
    PAYMENT = "payment"


@dataclass(frozen=True)
class Normal:
    """Un cargo normal."""


@dataclass(frozen=True)
class Installment:
    """Una compra a meses. Sin intereses (MSI), la tasa es 0."""

    months: int
    monthly_rate: Decimal

    def __post_init__(self) -> None:
        whole_number(self.months, "months", 1, MAX_MONTHS)
        if not isinstance(self.monthly_rate, Decimal) or not self.monthly_rate.is_finite():
            raise InvalidField("monthly_rate", "type")
        # Finito ya comprobado: el exponente es un entero (ceros a la derecha no cuentan).
        if int(self.monthly_rate.normalize().as_tuple().exponent) < -RATE_DECIMALS:
            raise InvalidField("monthly_rate", "precision")
        if not 0 <= self.monthly_rate < 1:
            raise InvalidField("monthly_rate", "range")


@dataclass(frozen=True)
class Payment:
    """El pago de la tarjeta, y de dónde salió el dinero."""

    source: PaymentSource

    def __post_init__(self) -> None:
        if not isinstance(self.source, PaymentSource):
            raise InvalidField("payment_source", "range")


MovementKind = Normal | Installment | Payment

# Los campos propios de cada tipo; en otro tipo no se permiten.
KIND_FIELDS = {
    KindName.NORMAL: (),
    KindName.INSTALLMENT: ("months", "monthly_rate"),
    KindName.PAYMENT: ("payment_source",),
}
MOVEMENT_FIELDS = ("amount_cents", "occurred_at", "kind", "review_status", "owner_cut")


def kind_name(kind: MovementKind) -> KindName:
    if isinstance(kind, Installment):
        return KindName.INSTALLMENT
    if isinstance(kind, Payment):
        return KindName.PAYMENT
    return KindName.NORMAL


@dataclass(frozen=True)
class Movement:
    amount_cents: int
    occurred: OccurredAt
    kind: MovementKind
    review_status: ReviewStatus
    owner_cut: date

    def __post_init__(self) -> None:
        cents(self.amount_cents, "amount_cents", minimum=1)
        if not isinstance(self.occurred, OccurredAt):
            raise InvalidField("occurred_at", "type")
        if not isinstance(self.kind, Normal | Installment | Payment):
            raise InvalidField("kind", "range")
        if not isinstance(self.review_status, ReviewStatus):
            raise InvalidField("review_status", "range")
        # datetime hereda de date: el corte es un día, no un instante.
        if type(self.owner_cut) is not date:
            raise InvalidField("owner_cut", "type")


def parse_kind(fields: Fields, name: KindName) -> MovementKind:
    for other, extra in KIND_FIELDS.items():
        for field in extra:
            if other is not name and fields.optional(field) is not None:
                raise InvalidField(field, "not_allowed")
    if name is KindName.INSTALLMENT:
        rate = decimal_text(fields.required("monthly_rate"), "monthly_rate")
        return Installment(months=fields.required("months"), monthly_rate=rate)
    if name is KindName.PAYMENT:
        source = choice(PaymentSource, fields.required("payment_source"), "payment_source")
        return Payment(source=source)
    return Normal()


def parse_movement(data: Mapping[str, object], now: datetime) -> Movement:
    allowed = MOVEMENT_FIELDS + tuple(f for extra in KIND_FIELDS.values() for f in extra)
    fields = Fields(data, allowed)
    amount = fields.required("amount_cents")
    occurred = parse_occurred_at(fields.required("occurred_at"), now)
    kind = parse_kind(fields, choice(KindName, fields.required("kind"), "kind"))
    return Movement(
        amount_cents=amount,
        occurred=occurred,
        kind=kind,
        review_status=choice(ReviewStatus, fields.required("review_status"), "review_status"),
        owner_cut=iso_date(fields.required("owner_cut"), "owner_cut"),
    )


# --- Ingreso mensual -----------------------------------------------------------------------------


@dataclass(frozen=True)
class MonthlyIncome:
    """El ingreso de cada mes. No tener ingreso es no tener registro, no un ingreso de 0."""

    amount_cents: int

    def __post_init__(self) -> None:
        cents(self.amount_cents, "amount_cents", minimum=1)


def parse_monthly_income(data: Mapping[str, object]) -> MonthlyIncome:
    fields = Fields(data, MonthlyIncome.__dataclass_fields__)
    return MonthlyIncome(amount_cents=fields.required("amount_cents"))
