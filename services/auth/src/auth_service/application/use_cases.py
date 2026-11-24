from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from auth_service.application.ports import Clock, PasswordHasher, TokenService, UnitOfWork
from auth_service.domain.errors import EmailAlreadyRegistered, InvalidCredentials
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


class LogIn:
    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        hasher: PasswordHasher,
        tokens: TokenService,
        clock: Clock,
        refresh_token_days: int,
    ) -> None:
        self._uow_factory = uow_factory
        self._hasher = hasher
        self._tokens = tokens
        self._clock = clock
        self._refresh_lifetime = timedelta(days=refresh_token_days)
        # Hash de relleno: con un correo inexistente se verifica contra él para que la
        # respuesta tarde lo mismo que con uno registrado.
        self._dummy_hash = hasher.hash("contraseña de relleno para igualar tiempos")

    def execute(self, email: str, password: str, device_id: str, device_name: str) -> LoginResult:
        now = self._clock.now()
        with self._uow_factory() as uow:
            user = uow.users.get_by_email(normalize_email(email))
            password_hash = user.password_hash if user else self._dummy_hash
            if not self._hasher.verify(password_hash, password) or user is None:
                raise InvalidCredentials()

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

        access_token, access_expires_at = self._tokens.issue_access_token(user.id, session.id, now)
        return LoginResult(
            session_id=session.id,
            access_token=access_token,
            access_token_expires_at=access_expires_at,
            refresh_token=refresh_token,
            refresh_token_expires_at=session.expires_at,
        )
