"""Pruebas de punta a punta: HTTP → casos de uso → PostgreSQL."""

import hashlib

import jwt
import pytest
from sqlalchemy import text

from ..conftest import JWT_SECRET

PASSWORD = "una contraseña larga"
DEVICE = {"device_id": "pixel-8-abc", "device_name": "Pixel 8"}


def register(client, email="luis@example.com", password=PASSWORD, **names):
    names = {"first_name": "Luis Miguel", "last_name": "Aguilar García"} | names
    return client.post("/register", json={"email": email, "password": password, **names})


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
    assert (body["first_name"], body["last_name"]) == ("Luis Miguel", "Aguilar García")
    assert set(body) == {"id", "email", "first_name", "last_name", "created_at"}
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT password_hash, first_name, last_name FROM auth.users")
        ).one()
    assert stored.password_hash.startswith("$argon2id$")
    assert (stored.first_name, stored.last_name) == ("Luis Miguel", "Aguilar García")


def test_register_trims_spaces_around_the_names(client) -> None:
    body = register(client, first_name="  Luis Miguel ", last_name="\tAguilar García\n").json()

    assert (body["first_name"], body["last_name"]) == ("Luis Miguel", "Aguilar García")


@pytest.mark.parametrize(
    "first_name,last_name",
    [
        ("María José", "Ñúñez de la Fuente"),
        ("Seán", "O'Brien"),
        ("Jean-Luc", "Picard-Dupont"),
        ("山田", "太郎"),
        ("محمد", "العلي"),  # de derecha a izquierda
        ("Zoë", "Smith Jr."),
        ("Luis", "García 2"),  # se aceptan números: los nombres reales son muy variados
        ("👩‍💻", "Programadora"),  # emoji compuesto
        ("Robert'); DROP TABLE auth.users;--", "<img src=x onerror=alert(1)>"),
        ("L", "A"),
        ("x" * 100, "y" * 100),
    ],
)
def test_unusual_names_are_registered_exactly(client, engine, first_name, last_name) -> None:
    body = register(client, first_name=first_name, last_name=last_name).json()

    assert (body["first_name"], body["last_name"]) == (first_name, last_name)
    with engine.connect() as connection:
        stored = connection.execute(text("SELECT first_name, last_name FROM auth.users")).one()
    assert tuple(stored) == (first_name, last_name)


@pytest.mark.parametrize(
    "names",
    [
        pytest.param({"first_name": None}, id="nombre nulo"),
        pytest.param({"last_name": None}, id="apellido nulo"),
        pytest.param({"first_name": ""}, id="nombre vacío"),
        pytest.param({"last_name": "   "}, id="apellido solo espacios"),
        pytest.param({"first_name": "x" * 101}, id="nombre de 101"),
        pytest.param({"last_name": "y" * 101}, id="apellido de 101"),
        pytest.param({"first_name": "Lu\x00is"}, id="carácter nulo"),
        pytest.param({"last_name": "Agui\nlar"}, id="salto de línea en medio"),
        pytest.param({"first_name": 7}, id="número en lugar de texto"),
        pytest.param({"last_name": ["Aguilar"]}, id="lista en lugar de texto"),
    ],
)
def test_register_with_invalid_names_returns_422_and_saves_nothing(client, engine, names) -> None:
    assert register(client, **names).status_code == 422
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM auth.users")).scalar_one() == 0


@pytest.mark.parametrize("missing", ["first_name", "last_name"])
def test_register_without_first_or_last_name_returns_422(client, missing) -> None:
    body = {
        "email": "luis@example.com",
        "password": PASSWORD,
        "first_name": "Luis",
        "last_name": "Aguilar",
    }
    del body[missing]

    response = client.post("/register", json=body)

    assert response.status_code == 422
    assert missing in str(response.json()["detail"])


def test_two_people_can_share_the_same_name(client) -> None:
    assert register(client, email="luis@example.com").status_code == 201
    assert register(client, email="otro.luis@example.com").status_code == 201


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
