from datetime import UTC, datetime, timedelta
from uuid import uuid4

from finance_service.domain.sync import Current, Outcome, corrected_time, decide

T = datetime(2026, 11, 26, 12, tzinfo=UTC)
CHANGE = uuid4()


def current(
    version: int = 3, updated_at: datetime = T, last_change_id=None, deleted: bool = False
) -> Current:
    return Current(version, updated_at, last_change_id, deleted)


# --- El reloj del teléfono -----------------------------------------------------------------------


def test_the_phone_time_is_moved_by_the_difference_between_the_clocks() -> None:
    # El teléfono va 10 minutos atrasado: su hora se corrige 10 minutos hacia adelante.
    sent_at, now = T, T + timedelta(minutes=10)
    assert corrected_time(T - timedelta(hours=1), sent_at, now) == T - timedelta(minutes=50)


def test_an_edit_after_the_send_is_a_clock_moved_back_and_counts_as_the_send() -> None:
    sent_at, now = T, T + timedelta(minutes=10)
    assert corrected_time(T + timedelta(days=3), sent_at, now) == now


# --- La decisión ---------------------------------------------------------------------------------


def test_a_change_already_applied_is_not_applied_again() -> None:
    # Aunque la versión ya no coincida y su hora sea vieja: es un reintento, no un choque.
    old = T - timedelta(days=1)
    assert (
        decide(CHANGE, 1, old, current(last_change_id=CHANGE), deleting=False)
        is Outcome.ALREADY_APPLIED
    )


def test_an_edit_on_the_current_version_is_applied_whatever_the_clocks() -> None:
    old = T - timedelta(days=1)
    assert decide(CHANGE, 3, old, current(version=3), deleting=False) is Outcome.APPLY


def test_in_a_clash_the_most_recent_edit_wins() -> None:
    later, earlier = T + timedelta(seconds=1), T - timedelta(seconds=1)
    assert decide(CHANGE, 2, later, current(version=3), deleting=False) is Outcome.APPLY
    assert decide(CHANGE, 2, earlier, current(version=3), deleting=False) is Outcome.LOST


def test_in_a_tie_what_reached_the_server_first_stays() -> None:
    assert decide(CHANGE, 2, T, current(version=3), deleting=False) is Outcome.LOST


def test_a_new_record_whose_key_already_exists_is_a_clash() -> None:
    # Se creó, la respuesta se perdió y se volvió a editar sin red: no sabe sobre qué versión.
    assert (
        decide(CHANGE, None, T + timedelta(seconds=1), current(), deleting=False) is Outcome.APPLY
    )
    assert decide(CHANGE, None, T - timedelta(seconds=1), current(), deleting=False) is Outcome.LOST


# --- Borrados ------------------------------------------------------------------------------------


def test_a_deletion_wins_even_a_clash_it_would_lose_by_time() -> None:
    earlier = T - timedelta(days=1)
    assert decide(CHANGE, 2, earlier, current(version=3), deleting=True) is Outcome.APPLY


def test_an_edit_of_a_deleted_record_is_lost_even_on_its_version_and_later() -> None:
    later = T + timedelta(days=1)
    gone = current(version=3, deleted=True)
    assert decide(CHANGE, 3, later, gone, deleting=False) is Outcome.LOST


def test_deleting_a_deleted_record_is_already_done() -> None:
    gone = current(version=3, deleted=True)
    assert decide(CHANGE, 2, T, gone, deleting=True) is Outcome.ALREADY_APPLIED


def test_a_retried_edit_of_a_record_deleted_since_stays_applied() -> None:
    # La edición se aplicó, la respuesta se perdió y otro teléfono borró después: el reintento no
    # se vuelve perdido (sigue siendo la misma edición), y el registro baja borrado.
    gone = current(version=4, deleted=True, last_change_id=CHANGE)
    assert decide(CHANGE, 3, T, gone, deleting=False) is Outcome.ALREADY_APPLIED
