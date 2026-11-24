"""Renovar, cerrar sesión, cambiar contraseña y límite de intentos, de punta a punta."""

from sqlalchemy import text

PASSWORD = "una contraseña larga"
NEW_PASSWORD = "otra contraseña muy larga"
EMAIL = "luis@example.com"


def register(client):
    assert client.post("/register", json={"email": EMAIL, "password": PASSWORD}).status_code == 201


def log_in(client, device_id="pixel-8-abc", password=PASSWORD):
    return client.post(
        "/sessions",
        json={"email": EMAIL, "password": password, "device_id": device_id, "device_name": "Tel"},
    )


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def test_renovar_rota_el_refresh_token(client) -> None:
    register(client)
    first = log_in(client).json()

    response = client.post("/sessions/refresh", json={"refresh_token": first["refresh_token"]})

    assert response.status_code == 200
    renewed = response.json()
    assert renewed["session_id"] == first["session_id"]
    assert renewed["refresh_token"] != first["refresh_token"]


def test_reusar_un_refresh_token_cierra_la_sesion(client) -> None:
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


def test_refresh_token_desconocido_responde_401(client) -> None:
    response = client.post("/sessions/refresh", json={"refresh_token": "no-existe"})

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_sin_token_o_con_token_invalido_responde_401(client) -> None:
    assert client.delete("/sessions/current").status_code == 401
    invalid = client.delete("/sessions/current", headers={"Authorization": "Bearer basura"})
    assert invalid.status_code == 401


def test_cerrar_sesion_invalida_el_token_de_ese_dispositivo(client) -> None:
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


def test_cambiar_contrasena_cierra_los_demas_dispositivos(client) -> None:
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


def test_contrasena_actual_incorrecta_responde_403_sin_cerrar_la_sesion(client) -> None:
    register(client)
    phone = log_in(client).json()

    response = client.put(
        "/password",
        json={"current_password": "no es la actual", "new_password": NEW_PASSWORD},
        headers=bearer(phone),
    )

    assert response.status_code == 403
    assert client.delete("/sessions/current", headers=bearer(phone)).status_code == 204


def test_contrasena_nueva_corta_responde_422(client) -> None:
    register(client)
    phone = log_in(client).json()

    response = client.put(
        "/password",
        json={"current_password": PASSWORD, "new_password": "corta"},
        headers=bearer(phone),
    )

    assert response.status_code == 422


def test_el_sexto_intento_fallido_responde_429_con_retry_after(client, engine) -> None:
    register(client)
    for _ in range(5):
        assert log_in(client, password="contraseña equivocada").status_code == 401

    blocked = log_in(client)

    assert blocked.status_code == 429
    assert 0 < int(blocked.headers["Retry-After"]) <= 15 * 60
    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM auth.login_attempts")).scalar_one()
    assert count == 5


def test_un_inicio_correcto_borra_los_intentos(client, engine) -> None:
    register(client)
    log_in(client, password="contraseña equivocada")

    assert log_in(client).status_code == 201

    with engine.connect() as connection:
        count = connection.execute(text("SELECT count(*) FROM auth.login_attempts")).scalar_one()
    assert count == 0
