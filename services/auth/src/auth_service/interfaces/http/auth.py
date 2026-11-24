"""Endpoints de cuentas y sesiones. El gateway los publica bajo /auth."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from auth_service.application.use_cases import (
    AuthContext,
    Authenticate,
    ChangePassword,
    LogIn,
    LoginResult,
    LogOut,
    RefreshSession,
    RegisterUser,
)
from auth_service.domain.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidToken,
    TooManyAttempts,
    WeakPassword,
    WrongCurrentPassword,
)
from auth_service.domain.model import MAX_PASSWORD_LENGTH

router = APIRouter(tags=["auth"])

# auto_error=False: si falta el token, respondemos 401 nosotros (FastAPI daría 403).
bearer = HTTPBearer(auto_error=False)


def _without_nul(value: str) -> str:
    # PostgreSQL no admite el carácter nulo en textos: se rechaza aquí con 422 y no con un 500.
    if "\x00" in value:
        raise ValueError("El texto no puede contener el carácter nulo.")
    return value


def _email_limits(value: str) -> str:
    # RFC 5321: parte local de hasta 64 caracteres y correo completo de hasta 254.
    local, _, _ = value.rpartition("@")
    if len(local) > 64 or len(value) > 254:
        raise ValueError("El correo es demasiado largo.")
    return value


Email = Annotated[EmailStr, AfterValidator(_email_limits)]
# Se recortan los espacios de los extremos: «   » queda vacío y se rechaza.
DeviceText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    AfterValidator(_without_nul),
]


class StrictRequest(BaseModel):
    """Base de los cuerpos de entrada: un campo desconocido es un error de quien llama."""

    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictRequest):
    email: Email
    # El mínimo lo valida el dominio; el máximo aquí evita procesar textos enormes.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class LoginRequest(StrictRequest):
    email: Email
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    device_id: DeviceText
    device_name: DeviceText


class RefreshRequest(StrictRequest):
    refresh_token: str = Field(max_length=200)


class ChangePasswordRequest(StrictRequest):
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class TokenResponse(BaseModel):
    token_type: Literal["bearer"] = "bearer"
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    session_id: UUID

    @classmethod
    def from_result(cls, result: LoginResult) -> "TokenResponse":
        return cls(
            access_token=result.access_token,
            access_token_expires_at=result.access_token_expires_at,
            refresh_token=result.refresh_token,
            refresh_token_expires_at=result.refresh_token_expires_at,
            session_id=result.session_id,
        )


class ErrorResponse(BaseModel):
    detail: str


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED, detail, headers={"WWW-Authenticate": "Bearer"}
    )


def current_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> AuthContext:
    """Exige un token de acceso válido cuya sesión siga activa."""
    if credentials is None:
        raise unauthorized("Falta el token de acceso.")
    authenticate: Authenticate = request.app.state.authenticate
    try:
        return authenticate.execute(credentials.credentials)
    except InvalidToken as error:
        raise unauthorized("Token inválido, vencido o de una sesión cerrada.") from error


CurrentSession = Annotated[AuthContext, Depends(current_session)]


def get_register_user(request: Request) -> RegisterUser:
    return request.app.state.register_user


def get_log_in(request: Request) -> LogIn:
    return request.app.state.log_in


def get_refresh_session(request: Request) -> RefreshSession:
    return request.app.state.refresh_session


def get_change_password(request: Request) -> ChangePassword:
    return request.app.state.change_password


def get_log_out(request: Request) -> LogOut:
    return request.app.state.log_out


UNAUTHORIZED = {401: {"model": ErrorResponse}}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    responses={
        409: {"model": ErrorResponse},
        422: {"description": "Correo o contraseña inválidos"},
    },
)
def register(
    body: RegisterRequest, register_user: Annotated[RegisterUser, Depends(get_register_user)]
) -> UserResponse:
    try:
        user = register_user.execute(body.email, body.password)
    except EmailAlreadyRegistered as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "El correo ya está registrado.") from error
    except WeakPassword as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return UserResponse(id=user.id, email=user.email, created_at=user.created_at)


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=TokenResponse,
    responses={**UNAUTHORIZED, 429: {"model": ErrorResponse}},
)
def log_in(body: LoginRequest, use_case: Annotated[LogIn, Depends(get_log_in)]) -> TokenResponse:
    try:
        result = use_case.execute(body.email, body.password, body.device_id, body.device_name)
    except InvalidCredentials as error:
        raise unauthorized("Correo o contraseña incorrectos.") from error
    except TooManyAttempts as error:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(error),
            headers={"Retry-After": str(error.retry_after_seconds)},
        ) from error
    return TokenResponse.from_result(result)


@router.post("/sessions/refresh", response_model=TokenResponse, responses=UNAUTHORIZED)
def refresh(
    body: RefreshRequest, use_case: Annotated[RefreshSession, Depends(get_refresh_session)]
) -> TokenResponse:
    try:
        return TokenResponse.from_result(use_case.execute(body.refresh_token))
    except InvalidToken as error:
        raise unauthorized("Refresh token inválido, vencido o ya usado.") from error


@router.delete("/sessions/current", status_code=status.HTTP_204_NO_CONTENT, responses=UNAUTHORIZED)
def log_out(session: CurrentSession, use_case: Annotated[LogOut, Depends(get_log_out)]) -> Response:
    use_case.execute(session.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **UNAUTHORIZED,
        # 403 y no 401: la app trata un 401 como «sesión cerrada» y borraría el token.
        403: {"model": ErrorResponse},
        422: {"description": "La contraseña nueva no cumple la política"},
    },
)
def change_password(
    body: ChangePasswordRequest,
    session: CurrentSession,
    use_case: Annotated[ChangePassword, Depends(get_change_password)],
) -> Response:
    try:
        use_case.execute(
            session.user_id, session.session_id, body.current_password, body.new_password
        )
    except WrongCurrentPassword as error:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "La contraseña actual no es correcta."
        ) from error
    except WeakPassword as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
