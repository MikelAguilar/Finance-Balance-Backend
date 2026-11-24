"""Pruebas de punta a punta: HTTP → casos de uso → PostgreSQL."""

import hashlib

import jwt
from sqlalchemy import text

from ..conftest import JWT_SECRET

PASSWORD = "una contraseña larga"
DEVICE = {"device_id": "pixel-8-abc", "device_name": "Pixel 8"}


def register(client, email="luis@example.com", password=PASSWORD):
    return client.post("/register", json={"email": email, "password": password})


def log_in(client, email="luis@example.com", password=PASSWORD, device=DEVICE):
    return client.post("/sessions", json={"email": email, "password": password, **device})


def sessions_in_db(engine):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT device_id, refresh_token_hash, revoked_at "
                "FROM auth.sessions ORDER BY created_at"
            )
        ).all()


def test_register_creates_account(client, engine) -> None:
    response = register(client, email="Luis@Example.com")

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "luis@example.com"
    assert set(body) == {"id", "email", "created_at"}
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT password_hash FROM auth.users")).scalar_one()
    assert stored.startswith("$argon2id$")


def test_register_duplicate_email_returns_409(client) -> None:
    register(client)

    response = register(client, email="LUIS@example.com")

    assert response.status_code == 409


def test_register_invalid_email_returns_422(client) -> None:
    assert register(client, email="no-es-un-correo").status_code == 422


def test_register_short_password_returns_422_with_reason(client) -> None:
    response = register(client, password="corta")

    assert response.status_code == 422
    assert "12" in response.json()["detail"]


def test_login_returns_tokens_and_stores_only_the_hash(client, engine) -> None:
    user_id = register(client).json()["id"]

    response = log_in(client)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    claims = jwt.decode(body["access_token"], JWT_SECRET, algorithms=["HS256"])
    assert claims["sub"] == user_id
    assert claims["sid"] == body["session_id"]
    [(device_id, stored_hash, revoked_at)] = sessions_in_db(engine)
    assert device_id == "pixel-8-abc"
    assert stored_hash == hashlib.sha256(body["refresh_token"].encode()).hexdigest()
    assert body["refresh_token"] not in stored_hash
    assert revoked_at is None


def test_invalid_credentials_do_not_reveal_registered_emails(client) -> None:
    register(client)

    wrong_password = log_in(client, password="otra contraseña larga")
    unknown_email = log_in(client, email="nadie@example.com")

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert wrong_password.headers["WWW-Authenticate"] == "Bearer"


def test_new_login_on_same_device_revokes_previous_session(client, engine) -> None:
    register(client)
    log_in(client)

    assert log_in(client).status_code == 201

    first, second = sessions_in_db(engine)
    assert first.revoked_at is not None
    assert second.revoked_at is None


def test_login_on_another_device_keeps_both_sessions(client, engine) -> None:
    register(client)
    log_in(client)

    log_in(client, device={"device_id": "galaxy-s24-xyz", "device_name": "Galaxy S24"})

    assert [row.revoked_at for row in sessions_in_db(engine)] == [None, None]
