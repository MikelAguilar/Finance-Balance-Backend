from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from auth_service.domain.errors import WeakPassword

# NIST SP 800-63B: la longitud protege más que las reglas de símbolos. El máximo evita que
# alguien envíe textos enormes para gastar CPU en Argon2.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 128


def normalize_email(email: str) -> str:
    return email.strip().lower()


def check_password_policy(password: str) -> None:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        raise WeakPassword(
            f"La contraseña debe tener entre {MIN_PASSWORD_LENGTH} y {MAX_PASSWORD_LENGTH} "
            "caracteres."
        )


@dataclass
class User:
    id: UUID
    email: str
    password_hash: str
    created_at: datetime
    # Obligatorios desde el registro. last_name guarda todos los apellidos («Aguilar García»).
    first_name: str
    last_name: str
    # Borrado lógico: la cuenta eliminada se conserva en la base, pero no inicia sesión ni
    # aparece al buscar por correo o por id.
    deleted_at: datetime | None = None


@dataclass
class Session:
    """Sesión de un dispositivo. El refresh token solo se guarda como hash."""

    id: UUID
    user_id: UUID
    device_id: str
    device_name: str
    refresh_token_hash: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    # Hash del refresh token anterior: si alguien lo vuelve a usar, el token fue copiado.
    previous_refresh_token_hash: str | None = None

    def is_active(self, now: datetime) -> bool:
        return self.revoked_at is None and now < self.expires_at

    def rotate(self, new_refresh_token_hash: str, now: datetime, lifetime: timedelta) -> None:
        """Cambia el refresh token y extiende la sesión desde este uso."""
        self.previous_refresh_token_hash = self.refresh_token_hash
        self.refresh_token_hash = new_refresh_token_hash
        self.last_used_at = now
        self.expires_at = now + lifetime

    def revoke(self, now: datetime) -> None:
        if self.revoked_at is None:
            self.revoked_at = now
