from datetime import UTC, datetime, timedelta
from uuid import uuid4

from finance_service.domain.sync import Current, Outcome, corrected_time, decide

T = datetime(2026, 11, 26, 12, tzinfo=UTC)
CHANGE = uuid4()


def current(version: int = 3, updated_at: datetime = T, last_change_id=None) -> Current:
    return Current(version=version, updated_at=updated_at, last_change_id=last_change_id)


# --- El reloj del teléfono -----------------------------------------------------------------------


def test_the_phone_time_is_moved_by_the_difference_between_the_clocks() -> None:
    # El teléfono va 10 minutos atrasado: su hora se corrige 10 minutos hacia adelante.
    sent_at, now = T, T + timedelta(minutes=10)
    assert corrected_time(T - timedelta(hours=1), sent_at, now) == T - timedelta(minutes=50)


def test_an_edit_after_the_send_is_a_clock_moved_back_and_counts_as_the_send() -> None:
    sent_at, now = T, T + timedelta(minutes=10)
    assert corrected_time(T + timedelta(days=3), sent_at, now) == now


# --- La decisión ---------------------------------------------------------------------------------


def test_a_record_the_server_does_not_have_is_created() -> None:
    assert decide(CHANGE, None, T, None) is Outcome.CREATE


def test_a_change_already_applied_is_not_applied_again() -> None:
    # Aunque la versión ya no coincida y su hora sea vieja: es un reintento, no un choque.
    old = T - timedelta(days=1)
    assert decide(CHANGE, 1, old, current(last_change_id=CHANGE)) is Outcome.ALREADY_APPLIED


def test_an_edit_on_the_current_version_is_applied_whatever_the_clocks() -> None:
    old = T - timedelta(days=1)
    assert decide(CHANGE, 3, old, current(version=3)) is Outcome.APPLY


def test_in_a_clash_the_most_recent_edit_wins() -> None:
    later, earlier = T + timedelta(seconds=1), T - timedelta(seconds=1)
    assert decide(CHANGE, 2, later, current(version=3)) is Outcome.APPLY
    assert decide(CHANGE, 2, earlier, current(version=3)) is Outcome.LOST


def test_in_a_tie_what_reached_the_server_first_stays() -> None:
    assert decide(CHANGE, 2, T, current(version=3)) is Outcome.LOST


def test_a_new_record_whose_key_already_exists_is_a_clash() -> None:
    # Se creó, la respuesta se perdió y se volvió a editar sin red: no sabe sobre qué versión.
    assert decide(CHANGE, None, T + timedelta(seconds=1), current()) is Outcome.APPLY
    assert decide(CHANGE, None, T - timedelta(seconds=1), current()) is Outcome.LOST
