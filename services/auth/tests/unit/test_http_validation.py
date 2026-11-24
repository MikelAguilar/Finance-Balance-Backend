"""Entradas malformadas, raras o maliciosas que la API debe rechazar antes de tocar la base.

Todas estas peticiones se resuelven en la capa HTTP: si alguna llegara a la base de datos, la
prueba fallaría al no poder conectarse (en esta prueba no hay PostgreSQL).
"""

import warnings
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from jwt.warnings import InsecureKeyLengthWarning

from ..conftest import JWT_SECRET

VALID_LOGIN = {
    "email": "luis@example.com",
    "password": "una contraseña larga",
    "device_id": "pixel-8-abc",
    "device_name": "Pixel 8",
}


@pytest.fixture
def client(make_client):
    return make_client("production")


# ------------------------------------------------------------------ cuerpo de la petición


@pytest.mark.parametrize("path", ["/register", "/sessions", "/sessions/refresh"])
def test_malformed_json_returns_422(client, path) -> None:
    response = client.post(
        path, content=b'{"email": ', headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/register", "/sessions", "/sessions/refresh"])
def test_empty_body_returns_422(client, path) -> None:
    assert client.post(path).status_code == 422


@pytest.mark.parametrize("path", ["/register", "/sessions", "/sessions/refresh"])
def test_json_that_is_not_an_object_returns_422(client, path) -> None:
    for body in (["lista"], "texto", 42, None):
        assert client.post(path, json=body).status_code == 422


@pytest.mark.parametrize("missing", list(VALID_LOGIN))
def test_login_without_a_required_field_returns_422(client, missing) -> None:
    body = {k: v for k, v in VALID_LOGIN.items() if k != missing}

    assert client.post("/sessions", json=body).status_code == 422


@pytest.mark.parametrize("field", list(VALID_LOGIN))
@pytest.mark.parametrize("wrong", [123, True, ["x"], {"a": 1}, None])
def test_login_with_wrong_types_returns_422(client, field, wrong) -> None:
    assert client.post("/sessions", json=VALID_LOGIN | {field: wrong}).status_code == 422


def test_unknown_fields_are_rejected(client) -> None:
    # Un campo inesperado suele ser un error de quien llama (por ejemplo, "pasword").
    response = client.post("/sessions", json=VALID_LOGIN | {"is_admin": True})

    assert response.status_code == 422


@pytest.mark.parametrize(
    "email",
    [
        "",
        "sin-arroba",
        "dos@@example.com",
        "con espacio@example.com",
        "@example.com",
        "luis@",
        "luis@example",
        "luis@exa\x00mple.com",
        "a" * 65 + "@example.com",  # la parte local admite como máximo 64 caracteres
        "luis@" + "b" * 250 + ".com",  # el correo completo admite como máximo 254
    ],
)
def test_invalid_emails_are_rejected(client, email) -> None:
    assert client.post("/register", json={"email": email, "password": "x" * 12}).status_code == 422


@pytest.mark.parametrize("field", ["device_id", "device_name"])
@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",  # solo espacios
        "\t\n",
        "x" * 101,
        "con\x00nulo",  # PostgreSQL no guarda el carácter nulo: debe rechazarse antes
    ],
)
def test_invalid_device_fields_are_rejected(client, field, value) -> None:
    assert client.post("/sessions", json=VALID_LOGIN | {field: value}).status_code == 422


@pytest.mark.parametrize("path,field", [("/register", "password"), ("/sessions", "password")])
def test_password_longer_than_128_is_rejected_before_hashing(client, path, field) -> None:
    body = VALID_LOGIN | {field: "x" * 129}
    if path == "/register":
        body = {"email": body["email"], "password": body["password"]}

    assert client.post(path, json=body).status_code == 422


def test_huge_refresh_token_is_rejected(client) -> None:
    assert client.post("/sessions/refresh", json={"refresh_token": "x" * 201}).status_code == 422


def test_form_encoded_body_is_rejected(client) -> None:
    response = client.post("/sessions", data=VALID_LOGIN)

    assert response.status_code == 422


# ------------------------------------------------------------------ token de acceso


def make_token(**overrides) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(uuid4()),
        "sid": str(uuid4()),
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=15)).timestamp()),
    } | overrides
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def hs512_token() -> str:
    # Mismo secreto, otro algoritmo: la API solo acepta HS256. PyJWT advierte que la clave es
    # corta para HS512; aquí da igual porque es un token falso.
    claims = {"sub": str(uuid4()), "sid": str(uuid4()), "type": "access", "exp": 9999999999}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", InsecureKeyLengthWarning)
        return jwt.encode(claims, JWT_SECRET, algorithm="HS512")


def expired_token() -> str:
    past = datetime.now(UTC) - timedelta(hours=1)
    return make_token(iat=int(past.timestamp()), exp=int(past.timestamp()))


BAD_AUTHORIZATION = [
    pytest.param(None, id="sin encabezado"),
    pytest.param("", id="vacío"),
    pytest.param("Bearer", id="Bearer sin token"),
    pytest.param("Bearer ", id="Bearer y espacio"),
    pytest.param("Basic dXNlcjpwYXNz", id="esquema Basic"),
    pytest.param("Bearer basura", id="token basura"),
    pytest.param("Bearer a.b.c", id="tres partes inválidas"),
    pytest.param("Token " + "x" * 40, id="esquema desconocido"),
]


@pytest.mark.parametrize("authorization", BAD_AUTHORIZATION)
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("DELETE", "/sessions/current", None),
        ("PUT", "/password", {"current_password": "x" * 12, "new_password": "y" * 12}),
    ],
)
def test_protected_endpoints_reject_bad_authorization(
    client, authorization, method, path, body
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    response = client.request(method, path, json=body, headers=headers)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token_factory",
    [
        pytest.param(expired_token, id="vencido"),
        pytest.param(lambda: make_token(type="refresh"), id="tipo refresh"),
        pytest.param(lambda: make_token(sub="no-es-uuid"), id="sub que no es UUID"),
        pytest.param(lambda: make_token(sid=None), id="sid nulo"),
        pytest.param(
            lambda: jwt.encode({"sub": str(uuid4())}, JWT_SECRET, algorithm="HS256"),
            id="sin sid ni exp",
        ),
        pytest.param(
            lambda: jwt.encode(
                {"sub": str(uuid4()), "sid": str(uuid4()), "type": "access", "exp": 9999999999},
                "otro-secreto-de-al-menos-32-caracteres!",
                algorithm="HS256",
            ),
            id="otro secreto",
        ),
        pytest.param(lambda: hs512_token(), id="algoritmo HS512"),
        pytest.param(
            lambda: jwt.encode(
                {"sub": str(uuid4()), "sid": str(uuid4()), "type": "access", "exp": 9999999999},
                None,
                algorithm="none",
            ),
            id="algoritmo none (sin firma)",
        ),
    ],
)
def test_forged_or_expired_tokens_are_rejected(client, token_factory) -> None:
    response = client.delete(
        "/sessions/current", headers={"Authorization": f"Bearer {token_factory()}"}
    )

    assert response.status_code == 401


# ------------------------------------------------------------------ rutas y métodos


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/register"),
        ("PUT", "/sessions"),
        ("GET", "/sessions/refresh"),
        ("POST", "/password"),
    ],
)
def test_wrong_method_returns_405(client, method, path) -> None:
    assert client.request(method, path).status_code == 405


@pytest.mark.parametrize("path", ["/admin", "/sessions/current/extra", "/../etc/passwd", "/%00"])
def test_unknown_paths_return_404(client, path) -> None:
    assert client.get(path).status_code == 404
