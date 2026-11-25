from datetime import UTC, datetime, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finance_service.domain.errors import InvalidField
from finance_service.domain.model import OccurredAt, parse_occurred_at

NOW = datetime(2026, 11, 25, 12, tzinfo=UTC)


def rejected(value: object) -> str:
    with pytest.raises(InvalidField) as error:
        parse_occurred_at(value, NOW)
    assert error.value.field == "occurred_at"
    return error.value.rule


def test_keeps_the_instant_and_the_offset_where_it_happened() -> None:
    # Compra en Madrid a las 03:00 (UTC+1): son las 02:00 en UTC y las 20:00 del día anterior en
    # Ciudad de México. Se guarda el instante y el offset para mostrarla como se registró.
    occurred = parse_occurred_at("2026-11-25T03:00:00+01:00", NOW)
    assert occurred == OccurredAt(at=datetime(2026, 11, 25, 2, tzinfo=UTC), offset_minutes=60)
    assert occurred.at.tzinfo is UTC


def test_negative_offsets_and_utc() -> None:
    assert parse_occurred_at("2026-11-24T20:00:00-06:00", NOW).offset_minutes == -360
    assert parse_occurred_at("2026-11-25T02:00:00Z", NOW).offset_minutes == 0


def test_a_date_and_time_without_offset_is_rejected() -> None:
    assert rejected("2026-11-25T03:00:00") == "missing_offset"
    assert rejected("2026-11-25") == "missing_offset"


@pytest.mark.parametrize("value", ["ayer", "2026-13-01T00:00:00Z", ""])
def test_unreadable_dates_are_rejected(value: str) -> None:
    assert rejected(value) == "format"


def test_only_text_is_accepted() -> None:
    assert rejected(1764036000) == "type"


def test_offsets_outside_the_real_world_are_rejected() -> None:
    assert parse_occurred_at("2026-11-25T03:00:00-12:00", NOW).offset_minutes == -720
    assert parse_occurred_at("2026-11-25T03:00:00+14:00", NOW).offset_minutes == 840
    assert rejected("2026-11-25T03:00:00-12:01") == "range"
    assert rejected("2026-11-25T03:00:00+14:01") == "range"
    # Un offset con segundos no existe en ninguna zona actual.
    assert rejected("2026-11-25T03:00:00+01:00:30") == "range"


def test_up_to_24_hours_in_the_future_is_accepted_and_past_dates_too() -> None:
    limit = NOW + timedelta(hours=24)
    assert parse_occurred_at(limit.isoformat(), NOW).at == limit
    assert rejected((limit + timedelta(seconds=1)).isoformat()) == "future"
    # Registrar tarde es legítimo.
    assert parse_occurred_at("2020-01-01T00:00:00-06:00", NOW).at.year == 2020


@given(st.integers(min_value=-720, max_value=840))
def test_every_whole_minute_offset_in_range_is_kept(minutes: int) -> None:
    sign = "+" if minutes >= 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    occurred = parse_occurred_at(f"2026-01-01T00:00:00{sign}{hours:02d}:{rest:02d}", NOW)
    assert occurred.offset_minutes == minutes


def test_an_occurred_at_cannot_be_built_invalid() -> None:
    with pytest.raises(InvalidField):
        OccurredAt(at=datetime(2026, 1, 1), offset_minutes=0)  # noqa: DTZ001 - sin zona a propósito
    with pytest.raises(InvalidField):
        OccurredAt(at=NOW, offset_minutes=900)
