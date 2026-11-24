import hashlib
import secrets
from datetime import datetime, timedelta
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2PasswordHasher:
    """Argon2id con los parámetros por defecto de argon2-cffi (recomendación RFC 9106)."""

    def __init__(self) -> None:
        self._hasher = PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False


class JwtTokenService:
    """Token de acceso JWT (HS256) y refresh token opaco guardado solo como SHA-256."""

    ALGORITHM = "HS256"

    def __init__(self, secret: str, access_token_minutes: int) -> None:
        self._secret = secret
        self._access_lifetime = timedelta(minutes=access_token_minutes)

    def issue_access_token(
        self, user_id: UUID, session_id: UUID, now: datetime
    ) -> tuple[str, datetime]:
        expires_at = now + self._access_lifetime
        claims = {
            "sub": str(user_id),
            "sid": str(session_id),
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        return jwt.encode(claims, self._secret, algorithm=self.ALGORITHM), expires_at

    def new_refresh_token(self) -> str:
        return secrets.token_urlsafe(32)

    def hash_refresh_token(self, token: str) -> str:
        # SHA-256 basta (no hace falta Argon2): el token ya es aleatorio de 256 bits.
        return hashlib.sha256(token.encode()).hexdigest()
