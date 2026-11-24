"""Perfil y lista de dispositivos de punta a punta, con PostgreSQL real."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text

PASSWORD = "una contraseña larga"
EMAIL = "luis@example.com"
OTHER_EMAIL = "ana@example.com"


def register(client, email=EMAIL):
    assert client.post("/register", json={"email": email, "password": PASSWORD}).status_code == 201


def log_in(client, device_id="telefono", email=EMAIL, device_name=None):
    response = client.post(
        "/sessions",
        json={
            "email": email,
            "password": PASSWORD,
            "device_id": device_id,
            "device_name": device_name or device_id.title(),
        },
    )
    assert response.status_code == 201
    return response.json()


def auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ------------------------------------------------------------------ perfil


def test_profile_of_a_new_account(client) -> None:
    register(client, email="  Luis@Example.COM ")
    tokens = log_in(client)

    response = client.get("/me", headers=auth(tokens))

    assert response.status_code == 200
    profile = response.json()
    assert profile["email"] == EMAIL
    assert profile["name"] is None
    assert set(profile) == {"id", "email", "name", "created_at"}


def test_profile_never_exposes_the_password_hash(client) -> None:
    register(client)
    tokens = log_in(client)

    body = client.get("/me", headers=auth(tokens)).text

    assert "argon2" not in body
    assert "password" not in body


def test_update_name_and_read_it_back(client) -> None:
    register(client)
    tokens = log_in(client)

    updated = client.patch("/me", json={"name": "  Luis Miguel  "}, headers=auth(tokens))

    assert updated.status_code == 200
    assert updated.json()["name"] == "Luis Miguel"
    assert client.get("/me", headers=auth(tokens)).json()["name"] == "Luis Miguel"


@pytest.mark.parametrize(
    "name",
    [
        "María José Ñúñez",
        "山田太郎",
        "محمد",  # de derecha a izquierda
        "👩‍💻 Luis",  # emoji compuesto
        "Robert'); DROP TABLE auth.users;--",
        "<img src=x onerror=alert(1)>",
        "x" * 100,
        "L",
    ],
)
def test_unusual_names_are_stored_exactly(client, engine, name) -> None:
    register(client)
    tokens = log_in(client)

    assert client.patch("/me", json={"name": name}, headers=auth(tokens)).json()["name"] == name
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT name FROM auth.users")).scalar_one()
    assert stored == name


def test_null_clears_the_name_and_empty_body_changes_nothing(client) -> None:
    register(client)
    tokens = log_in(client)
    client.patch("/me", json={"name": "Luis"}, headers=auth(tokens))

    unchanged = client.patch("/me", json={}, headers=auth(tokens))
    cleared = client.patch("/me", json={"name": None}, headers=auth(tokens))

    assert unchanged.json()["name"] == "Luis"
    assert cleared.json()["name"] is None


def test_name_is_shared_by_every_device_and_survives_a_new_login(client) -> None:
    register(client)
    phone = log_in(client, "telefono")
    client.patch("/me", json={"name": "Luis"}, headers=auth(phone))

    tablet = log_in(client, "tableta")

    assert client.get("/me", headers=auth(tablet)).json()["name"] == "Luis"


def test_rejected_update_does_not_change_the_name(client) -> None:
    register(client)
    tokens = log_in(client)
    client.patch("/me", json={"name": "Luis"}, headers=auth(tokens))

    response = client.patch(
        "/me", json={"name": "Luis", "email": "x@example.com"}, headers=auth(tokens)
    )

    assert response.status_code == 422
    profile = client.get("/me", headers=auth(tokens)).json()
    assert (profile["name"], profile["email"]) == ("Luis", EMAIL)


def test_profile_stops_working_after_logging_out(client) -> None:
    register(client)
    tokens = log_in(client)
    client.delete("/sessions/current", headers=auth(tokens))

    assert client.get("/me", headers=auth(tokens)).status_code == 401
    assert client.patch("/me", json={"name": "X"}, headers=auth(tokens)).status_code == 401


def test_each_account_only_sees_and_edits_its_own_profile(client) -> None:
    register(client)
    register(client, OTHER_EMAIL)
    luis, ana = log_in(client), log_in(client, email=OTHER_EMAIL)

    client.patch("/me", json={"name": "Ana"}, headers=auth(ana))

    assert client.get("/me", headers=auth(luis)).json()["name"] is None
    assert client.get("/me", headers=auth(ana)).json()["email"] == OTHER_EMAIL


# ------------------------------------------------------------------ lista de dispositivos


def test_device_list_marks_the_current_device(client) -> None:
    register(client)
    phone = log_in(client, "telefono", device_name="Pixel 8")
    log_in(client, "tableta", device_name="Galaxy Tab")

    response = client.get("/sessions", headers=auth(phone))

    assert response.status_code == 200
    devices = {d["device_name"]: d for d in response.json()}
    assert set(devices) == {"Pixel 8", "Galaxy Tab"}
    assert devices["Pixel 8"]["current"] is True
    assert devices["Galaxy Tab"]["current"] is False
    assert devices["Pixel 8"]["id"] == phone["session_id"]


def test_device_list_never_exposes_tokens_or_device_ids(client) -> None:
    register(client)
    tokens = log_in(client, "id-secreto-del-telefono")

    body = client.get("/sessions", headers=auth(tokens))

    assert set(body.json()[0]) == {
        "id",
        "device_name",
        "created_at",
        "last_used_at",
        "expires_at",
        "current",
    }
    assert tokens["refresh_token"] not in body.text
    assert "id-secreto-del-telefono" not in body.text


def test_device_list_is_ordered_by_last_use(client) -> None:
    register(client)
    phone = log_in(client, "telefono")
    tablet = log_in(client, "tableta")
    renewed = client.post("/sessions/refresh", json={"refresh_token": phone["refresh_token"]})

    listed = client.get("/sessions", headers=auth(tablet)).json()

    assert [d["id"] for d in listed] == [phone["session_id"], tablet["session_id"]]
    assert renewed.status_code == 200


def test_device_list_hides_closed_expired_and_other_accounts(client, engine) -> None:
    register(client)
    register(client, OTHER_EMAIL)
    current = log_in(client, "actual")
    closed = log_in(client, "cerrado")
    client.delete("/sessions/current", headers=auth(closed))
    expired = log_in(client, "vencido")
    log_in(client, "de-ana", email=OTHER_EMAIL)
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE auth.sessions SET expires_at = now() - interval '1 second' WHERE id = :id"
            ),
            {"id": expired["session_id"]},
        )

    listed = client.get("/sessions", headers=auth(current)).json()

    assert [d["id"] for d in listed] == [current["session_id"]]


def test_device_list_timestamps_are_consistent(client) -> None:
    register(client)
    tokens = log_in(client)

    (device,) = client.get("/sessions", headers=auth(tokens)).json()

    created = datetime.fromisoformat(device["created_at"])
    last_used = datetime.fromisoformat(device["last_used_at"])
    expires = datetime.fromisoformat(device["expires_at"])
    assert created.tzinfo is not None
    assert created <= last_used < expires
    assert expires - created == timedelta(days=90)
    assert abs(datetime.now(UTC) - created) < timedelta(minutes=1)


# ------------------------------------------------------------------ cerrar otro dispositivo


def test_closing_another_device_logs_it_out_everywhere(client) -> None:
    register(client)
    phone, tablet = log_in(client, "telefono"), log_in(client, "tableta")

    response = client.delete(f"/sessions/{tablet['session_id']}", headers=auth(phone))

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/me", headers=auth(tablet)).status_code == 401
    refresh = client.post("/sessions/refresh", json={"refresh_token": tablet["refresh_token"]})
    assert refresh.status_code == 401
    assert client.get("/me", headers=auth(phone)).status_code == 200
    assert [d["id"] for d in client.get("/sessions", headers=auth(phone)).json()] == [
        phone["session_id"]
    ]


def test_closing_the_current_device_by_id_logs_out(client) -> None:
    register(client)
    phone = log_in(client)

    assert client.delete(f"/sessions/{phone['session_id']}", headers=auth(phone)).status_code == 204
    assert client.get("/sessions", headers=auth(phone)).status_code == 401


def test_closing_the_same_device_twice_returns_204_both_times(client, engine) -> None:
    register(client)
    phone, tablet = log_in(client, "telefono"), log_in(client, "tableta")
    path = f"/sessions/{tablet['session_id']}"

    assert client.delete(path, headers=auth(phone)).status_code == 204
    with engine.connect() as connection:
        query = text("SELECT revoked_at FROM auth.sessions WHERE id = :id")
        first = connection.execute(query, {"id": tablet["session_id"]}).scalar_one()
    assert client.delete(path, headers=auth(phone)).status_code == 204
    with engine.connect() as connection:
        second = connection.execute(query, {"id": tablet["session_id"]}).scalar_one()
    assert first == second


def test_closing_an_expired_device_returns_204(client, engine) -> None:
    register(client)
    phone, tablet = log_in(client, "telefono"), log_in(client, "tableta")
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE auth.sessions SET expires_at = now() - interval '1 day' WHERE id = :id"),
            {"id": tablet["session_id"]},
        )

    assert (
        client.delete(f"/sessions/{tablet['session_id']}", headers=auth(phone)).status_code == 204
    )


def test_another_accounts_session_returns_404_and_stays_open(client) -> None:
    register(client)
    register(client, OTHER_EMAIL)
    luis, ana = log_in(client), log_in(client, email=OTHER_EMAIL)

    response = client.delete(f"/sessions/{ana['session_id']}", headers=auth(luis))

    assert response.status_code == 404
    assert response.json() == {"detail": "La sesión no existe."}
    assert client.get("/me", headers=auth(ana)).status_code == 200


def test_unknown_and_nil_session_ids_return_404(client) -> None:
    register(client)
    tokens = log_in(client)

    for session_id in (uuid4(), "00000000-0000-0000-0000-000000000000"):
        assert client.delete(f"/sessions/{session_id}", headers=auth(tokens)).status_code == 404


def test_uppercase_session_id_is_the_same_session(client) -> None:
    register(client)
    phone, tablet = log_in(client, "telefono"), log_in(client, "tableta")

    path = f"/sessions/{tablet['session_id'].upper()}"

    assert client.delete(path, headers=auth(phone)).status_code == 204
    assert client.get("/me", headers=auth(tablet)).status_code == 401


def test_a_closed_device_can_log_in_again_and_appears_once(client) -> None:
    register(client)
    phone, tablet = log_in(client, "telefono"), log_in(client, "tableta")
    client.delete(f"/sessions/{tablet['session_id']}", headers=auth(phone))

    again = log_in(client, "tableta")

    listed = client.get("/sessions", headers=auth(phone)).json()
    assert sorted(d["id"] for d in listed) == sorted([phone["session_id"], again["session_id"]])


def test_closed_session_cannot_close_others(client) -> None:
    register(client)
    phone, tablet = log_in(client, "telefono"), log_in(client, "tableta")
    client.delete("/sessions/current", headers=auth(tablet))

    response = client.delete(f"/sessions/{phone['session_id']}", headers=auth(tablet))

    assert response.status_code == 401
    assert client.get("/me", headers=auth(phone)).status_code == 200
