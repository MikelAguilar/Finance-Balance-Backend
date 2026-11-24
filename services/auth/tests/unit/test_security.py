from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from auth_service.infrastructure.security import Argon2PasswordHasher, JwtTokenService

SECRET = "s" * 32
# Fecha fija en el pasado: PyJWT rechaza tokens con "iat" en el futuro.
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def test_argon2_usa_la_variante_id_y_verifica() -> None:
    hasher = Argon2PasswordHasher()

    password_hash = hasher.hash("una contraseña larga")

    assert password_hash.startswith("$argon2id$")
    assert hasher.verify(password_hash, "una contraseña larga")
    assert not hasher.verify(password_hash, "otra contraseña")


def test_argon2_da_un_hash_distinto_cada_vez() -> None:
    hasher = Argon2PasswordHasher()

    assert hasher.hash("misma contraseña") != hasher.hash("misma contraseña")


def test_argon2_con_hash_invalido_responde_falso() -> None:
    assert not Argon2PasswordHasher().verify("no-es-un-hash", "lo que sea")


def test_token_de_acceso_lleva_usuario_sesion_y_vence_en_15_minutos() -> None:
    tokens = JwtTokenService(SECRET, access_token_minutes=15)
    user_id, session_id = uuid4(), uuid4()

    token, expires_at = tokens.issue_access_token(user_id, session_id, NOW)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"], options={"verify_exp": False})
    assert claims["sub"] == str(user_id)
    assert claims["sid"] == str(session_id)
    assert claims["type"] == "access"
    assert expires_at == NOW + timedelta(minutes=15)
    assert claims["exp"] == int(expires_at.timestamp())


def test_token_firmado_con_otro_secreto_no_es_valido() -> None:
    token, _ = JwtTokenService(SECRET, 15).issue_access_token(uuid4(), uuid4(), NOW)

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(token, "otro" * 8, algorithms=["HS256"], options={"verify_exp": False})


def test_refresh_token_aleatorio_y_su_hash_es_sha256() -> None:
    tokens = JwtTokenService(SECRET, 15)

    first, second = tokens.new_refresh_token(), tokens.new_refresh_token()

    assert first != second
    assert len(first) >= 43  # 32 bytes en base64 URL
    digest = tokens.hash_refresh_token(first)
    assert len(digest) == 64
    assert digest == tokens.hash_refresh_token(first)
    assert digest != tokens.hash_refresh_token(second)
