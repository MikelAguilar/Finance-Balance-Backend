"""Eliminar la cuenta de punta a punta, con PostgreSQL real."""

import pytest
from sqlalchemy import text

from .accounts import PASSWORD, auth, log_in, register


def delete_account(client, tokens, password=PASSWORD):
    return client.request("DELETE", "/me", json={"password": password}, headers=auth(tokens))


def test_delete_account_closes_every_device_and_blocks_login(client) -> None:
    register(client)
    phone = log_in(client, "telefono").json()
    tablet = log_in(client, "tableta").json()

    response = delete_account(client, phone)

    assert response.status_code == 204
    assert response.content == b""
    for tokens in (phone, tablet):
        assert client.get("/me", headers=auth(tokens)).status_code == 401
        refresh = {"refresh_token": tokens["refresh_token"]}
        assert client.post("/sessions/refresh", json=refresh).status_code == 401
    # Igual que una contraseña incorrecta: no revela que la cuenta existió.
    rejected = log_in(client)
    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "Correo o contraseña incorrectos."}


def test_delete_account_is_a_soft_delete(client, engine) -> None:
    user = register(client)
    tokens = log_in(client).json()

    delete_account(client, tokens)

    with engine.connect() as connection:
        deleted_at = connection.execute(
            text("SELECT deleted_at FROM auth.users WHERE id = :id"), {"id": user["id"]}
        ).scalar_one()
        unrevoked = connection.execute(
            text("SELECT count(*) FROM auth.sessions WHERE revoked_at IS NULL")
        ).scalar_one()
    assert deleted_at is not None
    assert unrevoked == 0


def test_wrong_password_is_403_and_the_account_keeps_working(client) -> None:
    register(client)
    tokens = log_in(client).json()

    response = delete_account(client, tokens, password="otra contraseña larga")

    # 403 y no 401: la app trata un 401 como «sesión cerrada» y borraría el token.
    assert response.status_code == 403
    assert response.json() == {"detail": "La contraseña no es correcta."}
    assert client.get("/me", headers=auth(tokens)).status_code == 200


def test_the_same_email_can_register_again_after_deleting(client) -> None:
    old = register(client)
    delete_account(client, log_in(client).json())

    new = register(client)

    assert new["id"] != old["id"]
    tokens = log_in(client).json()
    assert client.get("/me", headers=auth(tokens)).json()["id"] == new["id"]


def test_delete_without_token_is_401(client) -> None:
    response = client.request("DELETE", "/me", json={"password": PASSWORD})

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"password": None},
        {"password": "x" * 129},
        {"password": PASSWORD, "confirm": True},
    ],
    ids=["sin cuerpo", "vacío", "nulo", "demasiado larga", "campo desconocido"],
)
def test_invalid_body_is_422_and_deletes_nothing(client, body) -> None:
    register(client)
    tokens = log_in(client).json()

    response = client.request("DELETE", "/me", json=body, headers=auth(tokens))

    assert response.status_code == 422
    assert client.get("/me", headers=auth(tokens)).status_code == 200
