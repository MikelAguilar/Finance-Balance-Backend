"""Verificación de sesión para el gateway (GET /verify), con PostgreSQL real.

El gateway la consulta antes de pasar cada petición a /finance/*: con 204 deja pasar y entrega el
usuario en X-User-Id; con cualquier otra respuesta, esa respuesta es la que recibe la app.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
import pytest

from ..conftest import JWT_SECRET

PASSWORD = "una contraseña larga"
EMAIL = "luis@example.com"


def register(client, email=EMAIL):
    body = {"email": email, "password": PASSWORD, "first_name": "Luis", "last_name": "Aguilar"}
    response = client.post("/register", json=body)
    assert response.status_code == 201
    return response.json()


def log_in(client, device_id="telefono", email=EMAIL):
    body = {"email": email, "password": PASSWORD, "device_id": device_id, "device_name": device_id}
    response = client.post("/sessions", json=body)
    assert response.status_code == 201
    return response.json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def verify(client, headers=None):
    return client.get("/verify", headers=headers or {})


def test_valid_session_passes_and_names_the_user(client) -> None:
    user = register(client)
    tokens = log_in(client)

    response = verify(client, bearer(tokens["access_token"]))

    assert response.status_code == 204
    assert response.content == b""
    assert UUID(response.headers["X-User-Id"]) == UUID(user["id"])


def test_each_account_gets_its_own_user_id(client) -> None:
    luis = register(client)
    ana = register(client, "ana@example.com")
    luis_tokens = log_in(client)
    ana_tokens = log_in(client, email="ana@example.com")

    assert verify(client, bearer(luis_tokens["access_token"])).headers["X-User-Id"] == luis["id"]
    assert verify(client, bearer(ana_tokens["access_token"])).headers["X-User-Id"] == ana["id"]


def test_missing_token_is_rejected(client) -> None:
    response = verify(client)

    assert response.status_code == 401
    assert "X-User-Id" not in response.headers


def test_closed_session_is_rejected(client) -> None:
    register(client)
    tokens = log_in(client)
    client.delete("/sessions/current", headers=bearer(tokens["access_token"]))

    response = verify(client, bearer(tokens["access_token"]))

    assert response.status_code == 401
    assert "X-User-Id" not in response.headers


def test_session_closed_from_another_device_is_rejected(client) -> None:
    register(client)
    phone = log_in(client, "telefono")
    tablet = log_in(client, "tableta")
    client.delete(f"/sessions/{tablet['session_id']}", headers=bearer(phone["access_token"]))

    assert verify(client, bearer(tablet["access_token"])).status_code == 401
    assert verify(client, bearer(phone["access_token"])).status_code == 204


def test_deleted_account_is_rejected(client) -> None:
    register(client)
    tokens = log_in(client)
    client.request(
        "DELETE", "/me", json={"password": PASSWORD}, headers=bearer(tokens["access_token"])
    )

    assert verify(client, bearer(tokens["access_token"])).status_code == 401


def _forged(secret, *, token_type="access", minutes=15, sid=None):
    now = datetime.now(UTC)
    claims = {
        "sub": "00000000-0000-0000-0000-000000000001",
        "sid": sid or "00000000-0000-0000-0000-000000000002",
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(claims, secret, algorithm="HS256")


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(_forged("otra firma secreta" * 3), id="otra-firma"),
        pytest.param(_forged(JWT_SECRET, minutes=-1), id="vencido"),
        pytest.param(_forged(JWT_SECRET, token_type="refresh"), id="tipo-incorrecto"),
        pytest.param(_forged(JWT_SECRET), id="sesion-inexistente"),
        pytest.param("no-es-un-token", id="basura"),
    ],
)
def test_invalid_tokens_are_rejected(client, token) -> None:
    response = verify(client, bearer(token))

    assert response.status_code == 401
    assert "X-User-Id" not in response.headers


def test_expired_token_of_a_live_session_is_rejected(client) -> None:
    register(client)
    tokens = log_in(client)
    session_id = tokens["session_id"]

    expired = _forged(JWT_SECRET, minutes=-1, sid=session_id)

    assert verify(client, bearer(expired)).status_code == 401


def test_a_spoofed_user_header_is_not_echoed(client) -> None:
    user = register(client)
    tokens = log_in(client)
    headers = bearer(tokens["access_token"]) | {"X-User-Id": "00000000-0000-0000-0000-000000000009"}

    response = verify(client, headers)

    assert response.headers["X-User-Id"] == user["id"]
