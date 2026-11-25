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

from auth_service.application.use_cases import AuthContext
from auth_service.domain.errors import InvalidToken
from auth_service.interfaces.http.auth import current_session

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


@pytest.fixture
def signed_in(client):
    """Cliente con la sesión ya verificada: la validación del cuerpo se prueba sin base."""
    client.app.dependency_overrides[current_session] = lambda: AuthContext(uuid4(), uuid4())
    return client


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
        "\x1f",  # carácter de control que Pydantic no recorta como espacio
        "Pixel\x1b[31m",  # secuencia de escape de terminal
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
        ("GET", "/me", None),
        ("PATCH", "/me", {"name": "Luis"}),
        ("GET", "/sessions", None),
        ("DELETE", f"/sessions/{uuid4()}", None),
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
        ("POST", "/me"),
        ("PUT", "/me"),
        ("DELETE", "/password"),
        ("PATCH", "/sessions"),
        ("GET", f"/sessions/{uuid4()}"),
    ],
)
def test_wrong_method_returns_405(client, method, path) -> None:
    assert client.request(method, path).status_code == 405


@pytest.mark.parametrize("path", ["/admin", "/sessions/current/extra", "/../etc/passwd", "/%00"])
def test_unknown_paths_return_404(client, path) -> None:
    assert client.get(path).status_code == 404


# ------------------------------------------------------------------ perfil y dispositivos


@pytest.mark.parametrize(
    "name",
    [
        pytest.param("", id="vacío"),
        pytest.param("   ", id="solo espacios"),
        pytest.param("\t\n ", id="tabulador y salto"),
        pytest.param("x" * 101, id="101 caracteres"),
        pytest.param("Lu\x00is", id="carácter nulo"),
        pytest.param("\x1f", id="separador de unidad"),
        pytest.param("Luis\tMiguel", id="tabulador en medio"),
        pytest.param("Luis\x7f", id="DEL"),
        pytest.param("Lu\x85is", id="control C1 en medio"),
        pytest.param(123, id="número"),
        pytest.param(True, id="booleano"),
        pytest.param(["Luis"], id="lista"),
        pytest.param({"first": "Luis"}, id="objeto"),
    ],
)
def test_invalid_profile_names_are_rejected(signed_in, name) -> None:
    assert signed_in.patch("/me", json={"name": name}).status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"email": "otro@example.com"}, id="cambiar correo"),
        pytest.param({"password_hash": "x"}, id="cambiar hash"),
        pytest.param({"id": str(uuid4())}, id="cambiar id"),
        pytest.param({"name": "Luis", "is_admin": True}, id="campo extra"),
        pytest.param(["Luis"], id="lista en vez de objeto"),
        pytest.param("Luis", id="texto en vez de objeto"),
    ],
)
def test_profile_update_only_accepts_the_name(signed_in, body) -> None:
    # El correo y la contraseña tienen sus propios flujos; aquí se rechazan.
    assert signed_in.patch("/me", json=body).status_code == 422


def test_profile_update_rejects_malformed_json(signed_in) -> None:
    response = signed_in.patch(
        "/me", content=b'{"name": ', headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "session_id",
    [
        "no-es-uuid",
        "refresh",
        "123",
        "00000000-0000-0000-0000-00000000000",  # un dígito de menos
        "00000000-0000-0000-0000-0000000000000",  # un dígito de más
        "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
        "%00",
        "' OR '1'='1",
    ],
)
def test_revoking_a_session_with_an_invalid_id_returns_422(signed_in, session_id) -> None:
    assert signed_in.delete(f"/sessions/{session_id}").status_code == 422


def test_session_ids_with_extra_path_segments_return_404(signed_in) -> None:
    assert signed_in.delete(f"/sessions/{uuid4()}/extra").status_code == 404


class _AccountGone:
    """Simula que la cuenta se borró entre la verificación del token y la consulta."""

    def execute(self, *args):
        raise InvalidToken()


@pytest.mark.parametrize("method,body", [("GET", None), ("PATCH", {"name": "Luis"}), ("PATCH", {})])
def test_profile_of_an_account_deleted_mid_request_returns_401(signed_in, method, body) -> None:
    signed_in.app.state.get_profile = _AccountGone()
    signed_in.app.state.update_profile = _AccountGone()

    response = signed_in.request(method, "/me", json=body)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
