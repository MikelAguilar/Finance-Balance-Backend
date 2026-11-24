import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from auth_service.application.ports import Clock, PasswordHasher, TokenService, UnitOfWork
from auth_service.domain.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidToken,
    SessionNotFound,
    TooManyAttempts,
    WrongCurrentPassword,
)
from auth_service.domain.model import Session, User, check_password_policy, normalize_email


class RegisterUser:
    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], hasher: PasswordHasher, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._clock = clock

    def execute(self, email: str, password: str) -> User:
        check_password_policy(password)
        email = normalize_email(email)
        with self._uow_factory() as uow:
            if uow.users.get_by_email(email) is not None:
                raise EmailAlreadyRegistered(email)
            user = User(
                id=uuid4(),
                email=email,
                password_hash=self._hasher.hash(password),
                created_at=self._clock.now(),
            )
            uow.users.add(user)
            uow.commit()
        return user


@dataclass(frozen=True)
class LoginResult:
    session_id: UUID
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime


def _login_result(
    tokens: TokenService, user_id: UUID, session: Session, refresh_token: str, now: datetime
) -> LoginResult:
    access_token, access_expires_at = tokens.issue_access_token(user_id, session.id, now)
    return LoginResult(
        session_id=session.id,
        access_token=access_token,
        access_token_expires_at=access_expires_at,
        refresh_token=refresh_token,
        refresh_token_expires_at=session.expires_at,
    )


class LogIn:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        tokens: TokenService,
        clock: Clock,
        refresh_token_days: int,
        max_attempts: int,
        window_minutes: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock
        self._refresh_lifetime = timedelta(days=refresh_token_days)
        self._max_attempts = max_attempts
        self._window = timedelta(minutes=window_minutes)
        # Hash de relleno: con un correo inexistente se verifica contra él para que la
        # respuesta tarde lo mismo que con uno registrado.
        self._dummy_hash = hasher.hash("contraseña de relleno para igualar tiempos")

    def execute(self, email: str, password: str, device_id: str, device_name: str) -> LoginResult:
        now = self._clock.now()
        email = normalize_email(email)
        with self._uow_factory() as uow:
            # Se cuenta por correo, exista o no la cuenta: así el límite tampoco revela cuentas.
            failures = uow.login_attempts.list_failures_since(email, now - self._window)
            if len(failures) >= self._max_attempts:
                retry_after = failures[0] + self._window - now
                raise TooManyAttempts(math.ceil(retry_after.total_seconds()))

            # Bloquea la cuenta: dos inicios simultáneos en el mismo dispositivo no deben crear
            # dos sesiones activas (el índice único parcial lo rechazaría con un error).
            user = uow.users.get_by_email(email, for_update=True)
            password_hash = user.password_hash if user else self._dummy_hash
            if not self._hasher.verify(password_hash, password) or user is None:
                uow.login_attempts.add_failure(email, now)
                uow.commit()
                raise InvalidCredentials()
            uow.login_attempts.clear(email)

            # Una sola sesión por dispositivo: la anterior se revoca para no duplicar
            # filas en la pantalla "Dispositivos".
            for previous in uow.sessions.list_unrevoked_for_device(user.id, device_id):
                previous.revoke(now)

            refresh_token = self._tokens.new_refresh_token()
            session = Session(
                id=uuid4(),
                user_id=user.id,
                device_id=device_id,
                device_name=device_name,
                refresh_token_hash=self._tokens.hash_refresh_token(refresh_token),
                created_at=now,
                last_used_at=now,
                expires_at=now + self._refresh_lifetime,
            )
            uow.sessions.add(session)
            uow.commit()
        return _login_result(self._tokens, user.id, session, refresh_token, now)


class RefreshSession:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        tokens: TokenService,
        clock: Clock,
        refresh_token_days: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = tokens
        self._clock = clock
        self._refresh_lifetime = timedelta(days=refresh_token_days)

    def execute(self, refresh_token: str) -> LoginResult:
        now = self._clock.now()
        token_hash = self._tokens.hash_refresh_token(refresh_token)
        with self._uow_factory() as uow:
            # Bloquea la sesión: si el mismo token llega dos veces a la vez, solo una gana.
            session = uow.sessions.get_by_refresh_hash(token_hash, for_update=True)
            if session is None:
                # Si es un refresh token que ya se cambió, alguien lo copió: se cierra la sesión
                # para el ladrón y para el dueño, que deberá iniciar sesión otra vez.
                reused = uow.sessions.get_by_previous_refresh_hash(token_hash)
                if reused is not None and reused.revoked_at is None:
                    reused.revoke(now)
                    uow.commit()
                raise InvalidToken()
            if not session.is_active(now):
                raise InvalidToken()

            new_refresh_token = self._tokens.new_refresh_token()
            new_hash = self._tokens.hash_refresh_token(new_refresh_token)
            session.rotate(new_hash, now, self._refresh_lifetime)
            uow.commit()
        return _login_result(self._tokens, session.user_id, session, new_refresh_token, now)


@dataclass(frozen=True)
class AuthContext:
    user_id: UUID
    session_id: UUID


class Authenticate:
    """Verifica el token de acceso y que su sesión siga activa (revocación inmediata)."""

    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], tokens: TokenService, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._tokens = tokens
        self._clock = clock

    def execute(self, access_token: str) -> AuthContext:
        now = self._clock.now()
        user_id, session_id = self._tokens.decode_access_token(access_token, now)
        with self._uow_factory() as uow:
            session = uow.sessions.get(session_id)
        if session is None or session.user_id != user_id or not session.is_active(now):
            raise InvalidToken()
        return AuthContext(user_id=user_id, session_id=session_id)


class ChangePassword:
    def __init__(
        self, uow_factory: Callable[[], UnitOfWork], hasher: PasswordHasher, clock: Clock
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._clock = clock

    def execute(
        self, user_id: UUID, current_session_id: UUID, current_password: str, new_password: str
    ) -> None:
        check_password_policy(new_password)
        now = self._clock.now()
        with self._uow_factory() as uow:
            user = uow.users.get(user_id, for_update=True)
            if user is None or not self._hasher.verify(user.password_hash, current_password):
                raise WrongCurrentPassword()
            user.password_hash = self._hasher.hash(new_password)
            # Decisión del diseño: cambiar la contraseña cierra los demás dispositivos.
            for session in uow.sessions.list_unrevoked_for_user(user_id):
                if session.id != current_session_id:
                    session.revoke(now)
            uow.commit()


class LogOut:
    def __init__(self, uow_factory: Callable[[], UnitOfWork], clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def execute(self, session_id: UUID) -> None:
        with self._uow_factory() as uow:
            session = uow.sessions.get(session_id, for_update=True)
            if session is not None:
                session.revoke(self._clock.now())
                uow.commit()


class GetProfile:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def execute(self, user_id: UUID) -> User:
        with self._uow_factory() as uow:
            user = uow.users.get(user_id)
        # La cuenta pudo borrarse entre la verificación del token y esta consulta.
        if user is None:
            raise InvalidToken()
        return user


class UpdateProfile:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def execute(self, user_id: UUID, name: str | None) -> User:
        """`name=None` borra el nombre."""
        with self._uow_factory() as uow:
            user = uow.users.get(user_id, for_update=True)
            if user is None:
                raise InvalidToken()
            user.name = name
            uow.commit()
        return user


class ListSessions:
    """Dispositivos con sesión activa, del uso más reciente al más antiguo."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def execute(self, user_id: UUID) -> list[Session]:
        now = self._clock.now()
        with self._uow_factory() as uow:
            sessions = uow.sessions.list_unrevoked_for_user(user_id)
        active = [session for session in sessions if session.is_active(now)]
        # El id desempata para que el orden sea el mismo en cada consulta.
        return sorted(active, key=lambda s: (s.last_used_at, s.created_at, str(s.id)), reverse=True)


class RevokeSession:
    """Cierra la sesión de un dispositivo del mismo usuario."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork], clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def execute(self, user_id: UUID, session_id: UUID) -> None:
        with self._uow_factory() as uow:
            session = uow.sessions.get(session_id, for_update=True)
            # Una sesión ajena responde igual que una inexistente: no revela que existe.
            if session is None or session.user_id != user_id:
                raise SessionNotFound()
            # Cerrar una sesión ya cerrada o vencida no es un error: el resultado es el mismo.
            if session.revoked_at is None:
                session.revoke(self._clock.now())
                uow.commit()
