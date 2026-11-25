"""Cuentas y sesiones de prueba que comparten varias pruebas de integración."""

PASSWORD = "una contraseña larga"
EMAIL = "luis@example.com"


def register(client, email=EMAIL):
    body = {"email": email, "password": PASSWORD, "first_name": "Luis", "last_name": "Aguilar"}
    response = client.post("/register", json=body)
    assert response.status_code == 201
    return response.json()


def log_in(client, device_id="telefono", email=EMAIL):
    body = {"email": email, "password": PASSWORD, "device_id": device_id, "device_name": device_id}
    return client.post("/sessions", json=body)


def auth(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}
