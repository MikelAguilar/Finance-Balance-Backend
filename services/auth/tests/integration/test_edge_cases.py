"""Casos raros de punta a punta: textos extraños, límites exactos y datos que cambian por fuera."""

from datetime import datetime

import pytest
from sqlalchemy import text

PASSWORD = "una contraseña larga"


def register(client, email="luis@example.com", password=PASSWORD):
    return client.post("/register", json={"email": email, "password": password})


def log_in(client, email="luis@example.com", password=PASSWORD, device_id="d1", device_name="D"):
    return client.post(
        "/sessions",
        json={
            "email": email,
            "password": password,
            "device_id": device_id,
            "device_name": device_name,
        },
    )


@pytest.mark.parametrize(
    "device_name",
    [
        "Teléfono de María José",
        "📱 Pixel 8 Pro 🔒",
        "日本語のデバイス",
        "Robert'); DROP TABLE auth.users;--",
        "<script>alert(1)</script>",
        "x" * 100,
        "  con espacios alrededor  ",
    ],
)
def test_unusual_device_names_are_stored_exactly_and_safely(client, engine, device_name) -> None:
    register(client)

    assert log_in(client, device_name=device_name).status_code == 201

    with engine.connect() as connection:
        stored = connection.execute(text("SELECT device_name FROM auth.sessions")).scalar_one()
        users = connection.execute(text("SELECT count(*) FROM auth.users")).scalar_one()
    assert stored == device_name.strip()
    assert users == 1  # la tabla sigue ahí: el texto se guardó como dato, no como SQL


@pytest.mark.parametrize(
    "password",
    [
        "x" * 12,
        "x" * 128,
        "🔐" * 12,  # 12 caracteres, 48 bytes
        "contraseña con ñ y acentos",
        "' OR '1'='1' -- ",
        "    doce espacios   ",
    ],
)
def test_unusual_passwords_work_for_register_and_login(client, password) -> None:
    assert register(client, password=password).status_code == 201
    assert log_in(client, password=password).status_code == 201
    wrong = password[:-1] + ("y" if password[-1] != "y" else "z")  # misma longitud, otro texto
    assert log_in(client, password=wrong).status_code == 401


def test_the_longest_valid_email_works(client) -> None:
    # 64 caracteres de parte local + @ + dominio hasta completar 254.
    domain = ".".join(["a" * 63, "b" * 63, "c" * 57]) + ".com"
    email = "l" * 64 + "@" + domain
    assert len(email) == 254

    assert register(client, email=email).status_code == 201
    assert log_in(client, email=email.upper()).status_code == 201


def test_email_with_plus_and_dots_is_a_different_account(client) -> None:
    assert register(client, email="luis@example.com").status_code == 201
    assert register(client, email="luis+finanzas@example.com").status_code == 201
    assert register(client, email="l.u.i.s@example.com").status_code == 201


def test_timestamps_in_responses_carry_a_timezone(client) -> None:
    created = register(client).json()["created_at"]
    tokens = log_in(client).json()

    for value in (created, tokens["access_token_expires_at"], tokens["refresh_token_expires_at"]):
        assert datetime.fromisoformat(value).tzinfo is not None


def test_a_token_stops_working_if_the_user_is_deleted_directly_in_the_database(
    client, engine
) -> None:
    register(client)
    tokens = log_in(client).json()
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth.users"))  # las sesiones se borran en cascada

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.delete("/sessions/current", headers=headers).status_code == 401
    refresh = client.post("/sessions/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refresh.status_code == 401


def test_a_token_stops_working_if_its_session_is_revoked_directly(client, engine) -> None:
    register(client)
    tokens = log_in(client).json()
    with engine.begin() as connection:
        connection.execute(text("UPDATE auth.sessions SET revoked_at = now()"))

    headers = {"Authorization": f"Bearer {tokens['access_token']}"}
    assert client.delete("/sessions/current", headers=headers).status_code == 401


def test_an_empty_refresh_token_is_simply_invalid(client) -> None:
    assert client.post("/sessions/refresh", json={"refresh_token": ""}).status_code == 401


def test_many_devices_for_one_account(client, engine) -> None:
    register(client)
    for i in range(30):
        assert log_in(client, device_id=f"dispositivo-{i}").status_code == 201

    with engine.connect() as connection:
        active = connection.execute(
            text("SELECT count(*) FROM auth.sessions WHERE revoked_at IS NULL")
        ).scalar_one()
    assert active == 30


def test_device_id_is_case_sensitive(client, engine) -> None:
    # Android entrega identificadores exactos: «ABC» y «abc» son dispositivos distintos.
    register(client)
    log_in(client, device_id="ABC")
    log_in(client, device_id="abc")

    with engine.connect() as connection:
        active = connection.execute(
            text("SELECT count(*) FROM auth.sessions WHERE revoked_at IS NULL")
        ).scalar_one()
    assert active == 2
