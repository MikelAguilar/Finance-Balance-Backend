"""Renovar, cerrar sesión, cambiar contraseña y límite de intentos, de punta a punta."""

from sqlalchemy import text

PASSWORD = "una contraseña larga"
NEW_PASSWORD = "otra contraseña muy larga"
EMAIL = "luis@example.com"


def register(client):
    body = {"email": EMAIL, "password": PASSWORD, "first_name": "Luis", "last_name": "Aguilar"}
    assert client.post("/register", json=body).status_code == 201


def log_in(client, device_id="pixel-8-abc", password=PASSWORD):
    return client.post(
        "/sessions",
        json={"email": EMAIL, "password": password, "device_id": device_id, "device_name": "Tel"},
    )


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_refresh_rotates_refresh_token(client) -> None:
    register(client)
    first = log_in(client).json()

    response = client.post("/sessions/refresh", json={"refresh_token": first["refresh_token"]})

    assert response.status_code == 200
    renewed = response.json()
    assert renewed["session_id"] == first["session_id"]
    assert renewed["refresh_token"] != first["refresh_token"]


def test_reusing_refresh_token_closes_session(client) -> None:
    register(client)
    first = log_in(client).json()
    renewed = client.post(
        "/sessions/refresh", json={"refresh_token": first["refresh_token"]}
    ).json()

    reused = client.post("/sessions/refresh", json={"refresh_token": first["refresh_token"]})

    assert reused.status_code == 401
    assert (
        client.post(
            "/sessions/refresh", json={"refresh_token": renewed["refresh_token"]}
        ).status_code
        == 401
    )
    assert client.delete("/sessions/current", headers=bearer(renewed)).status_code == 401


def test_unknown_refresh_token_returns_401(client) -> None:
    response = client.post("/sessions/refresh", json={"refresh_token": "no-existe"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_missing_or_invalid_token_returns_401(client) -> None:
    assert client.delete("/sessions/current").status_code == 401
    invalid = client.delete("/sessions/current", headers={"Authorization": "Bearer basura"})
    assert invalid.status_code == 401


def test_logout_invalidates_that_device_tokens(client) -> None:
    register(client)
    phone = log_in(client, "pixel-8-abc").json()
    tablet = log_in(client, "tablet-xyz").json()

    assert client.delete("/sessions/current", headers=bearer(phone)).status_code == 204

    assert client.delete("/sessions/current", headers=bearer(phone)).status_code == 401
    refresh = client.post("/sessions/refresh", json={"refresh_token": phone["refresh_token"]})
    assert refresh.status_code == 401
    # El otro dispositivo sigue activo.
    assert (
        client.post(
            "/sessions/refresh", json={"refresh_token": tablet["refresh_token"]}
        ).status_code
        == 200
    )


def test_change_password_logs_out_other_devices(client) -> None:
    register(client)
    phone = log_in(client, "pixel-8-abc").json()
    tablet = log_in(client, "tablet-xyz").json()

    response = client.put(
        "/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        headers=bearer(phone),
    )

    assert response.status_code == 204
    assert client.delete("/sessions/current", headers=bearer(tablet)).status_code == 401
    assert log_in(client, "laptop", PASSWORD).status_code == 401
    assert log_in(client, "laptop", NEW_PASSWORD).status_code == 201
    # El dispositivo que cambió la contraseña sigue dentro.
    assert client.delete("/sessions/current", headers=bearer(phone)).status_code == 204


def test_wrong_current_password_returns_403_and_keeps_session(client) -> None:
    register(client)
    phone = log_in(client).json()

    response = client.put(
        "/password",
        json={"current_password": "no es la actual", "new_password": NEW_PASSWORD},
        headers=bearer(phone),
    )

    assert response.status_code == 403
    assert client.delete("/sessions/current", headers=bearer(phone)).status_code == 204


def test_short_new_password_returns_422(client) -> None:
    register(client)
    phone = log_in(client).json()

    response = client.put(
        "/password",
        json={"current_password": PASSWORD, "new_password": "corta"},
        headers=bearer(phone),
    )

    assert response.status_code == 422


def test_sixth_failed_attempt_returns_429_with_retry_after(client, engine) -> None:
    register(client)
    for _ in range(5):
        assert log_in(client, password="contraseña equivocada").status_code == 401

    blocked = log_in(client)

    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= 15 * 60
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM auth.login_attempts")).scalar_one()
    assert count == 5


def test_successful_login_clears_attempts(client, engine) -> None:
    register(client)
    log_in(client, password="contraseña equivocada")

    assert log_in(client).status_code == 201

    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM auth.login_attempts")).scalar_one()
    assert count == 0
