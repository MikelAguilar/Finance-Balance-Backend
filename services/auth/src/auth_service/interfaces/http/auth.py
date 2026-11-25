"""Endpoints de cuentas y sesiones. El gateway los publica bajo /auth."""

import unicodedata
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    field_validator,
)

from auth_service.application.use_cases import (
    AuthContext,
    Authenticate,
    ChangePassword,
    DeleteAccount,
    GetProfile,
    ListSessions,
    LogIn,
    LoginResult,
    LogOut,
    RefreshSession,
    RegisterUser,
    RevokeSession,
    UpdateProfile,
)
from auth_service.domain.errors import (
    EmailAlreadyRegistered,
    InvalidCredentials,
    InvalidToken,
    SessionNotFound,
    TooManyAttempts,
    WeakPassword,
    WrongCurrentPassword,
)
from auth_service.domain.model import MAX_PASSWORD_LENGTH, Session, User

router = APIRouter(tags=["auth"])

# auto_error=False: si falta el token, respondemos 401 nosotros (FastAPI daría 403).
bearer = HTTPBearer(auto_error=False)


def _without_control_characters(value: str) -> str:
    # Caracteres de control (nulo, tabulador, \x1f…): no se ven en pantalla y PostgreSQL no
    # admite el nulo (sería un error 500). Se rechazan aquí con 422.
    if any(unicodedata.category(character) == "Cc" for character in value):
        raise ValueError("El texto no puede contener caracteres de control.")
    return value


def _email_limits(value: str) -> str:
    # RFC 5321: parte local de hasta 64 caracteres y correo completo de hasta 254.
    local, _, _ = value.rpartition("@")
    if len(local) > 64 or len(value) > 254:
        raise ValueError("El correo es demasiado largo.")
    return value


Email = Annotated[EmailStr, AfterValidator(_email_limits)]
# Se recortan los espacios de los extremos: «   » queda vacío y se rechaza. Sirve para nombres,
# apellidos y dispositivos: se aceptan acentos, ñ, guiones, apóstrofos y espacios en medio.
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
    AfterValidator(_without_control_characters),
]


class StrictRequest(BaseModel):
    """Base de los cuerpos de entrada: un campo desconocido es un error de quien llama."""

    model_config = ConfigDict(extra="forbid")


class RegisterRequest(StrictRequest):
    email: Email
    # El mínimo lo valida el dominio; el máximo aquí evita procesar textos enormes.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    first_name: ShortText
    # Todos los apellidos en un solo campo: «Aguilar García», o uno solo si la persona tiene uno.
    last_name: ShortText


class UserResponse(BaseModel):
    id: UUID
    email: str
    first_name: str
    last_name: str
    created_at: datetime

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            first_name=user.first_name,
            last_name=user.last_name,
            created_at=user.created_at,
        )


class LoginRequest(StrictRequest):
    email: Email
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    device_id: ShortText
    device_name: ShortText


class RefreshRequest(StrictRequest):
    refresh_token: str = Field(max_length=200)


class ChangePasswordRequest(StrictRequest):
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class DeleteAccountRequest(StrictRequest):
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


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


class UpdateProfileRequest(StrictRequest):
    """Solo cambia lo que se envía; un campo ausente queda como está."""

    first_name: ShortText | None = None
    last_name: ShortText | None = None

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _cannot_be_cleared(cls, value: object) -> object:
        # Solo corre si el campo viene en el cuerpo: el valor por defecto no se valida.
        if value is None:
            raise ValueError("El nombre y el apellido son obligatorios: no se pueden borrar.")
        return value


class SessionResponse(BaseModel):
    id: UUID
    device_name: str
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    # Para que la app marque «Este dispositivo» y no ofrezca cerrarlo desde la lista.
    current: bool

    @classmethod
    def from_session(cls, session: Session, current_session_id: UUID) -> "SessionResponse":
        return cls(
            id=session.id,
            device_name=session.device_name,
            created_at=session.created_at,
            last_used_at=session.last_used_at,
            expires_at=session.expires_at,
            current=session.id == current_session_id,
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


def get_get_profile(request: Request) -> GetProfile:
    return request.app.state.get_profile


def get_update_profile(request: Request) -> UpdateProfile:
    return request.app.state.update_profile


def get_list_sessions(request: Request) -> ListSessions:
    return request.app.state.list_sessions


def get_revoke_session(request: Request) -> RevokeSession:
    return request.app.state.revoke_session


def get_delete_account(request: Request) -> DeleteAccount:
    return request.app.state.delete_account


UNAUTHORIZED = {401: {"model": ErrorResponse}}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
    responses={
        409: {"model": ErrorResponse},
        422: {"description": "Correo, contraseña, nombre o apellido inválidos"},
    },
)
def register(
    body: RegisterRequest, register_user: Annotated[RegisterUser, Depends(get_register_user)]
) -> UserResponse:
    try:
        user = register_user.execute(body.email, body.password, body.first_name, body.last_name)
    except EmailAlreadyRegistered as error:
        raise HTTPException(status.HTTP_409_CONFLICT, "El correo ya está registrado.") from error
    except WeakPassword as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from error
    return UserResponse.from_user(user)


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


@router.get("/sessions", response_model=list[SessionResponse], responses=UNAUTHORIZED)
def list_sessions(
    session: CurrentSession, use_case: Annotated[ListSessions, Depends(get_list_sessions)]
) -> list[SessionResponse]:
    return [
        SessionResponse.from_session(item, session.session_id)
        for item in use_case.execute(session.user_id)
    ]


# Va antes de /sessions/{session_id}: FastAPI prueba las rutas en orden.
@router.delete("/sessions/current", status_code=status.HTTP_204_NO_CONTENT, responses=UNAUTHORIZED)
def log_out(session: CurrentSession, use_case: Annotated[LogOut, Depends(get_log_out)]) -> Response:
    use_case.execute(session.session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**UNAUTHORIZED, 404: {"model": ErrorResponse}},
)
def revoke_session(
    session_id: UUID,
    session: CurrentSession,
    use_case: Annotated[RevokeSession, Depends(get_revoke_session)],
) -> Response:
    try:
        use_case.execute(session.user_id, session_id)
    except SessionNotFound as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "La sesión no existe.") from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserResponse, responses=UNAUTHORIZED)
def get_profile(
    session: CurrentSession, use_case: Annotated[GetProfile, Depends(get_get_profile)]
) -> UserResponse:
    try:
        return UserResponse.from_user(use_case.execute(session.user_id))
    except InvalidToken as error:
        raise unauthorized("La cuenta ya no existe.") from error


@router.patch("/me", response_model=UserResponse, responses=UNAUTHORIZED)
def update_profile(
    body: UpdateProfileRequest,
    session: CurrentSession,
    get_use_case: Annotated[GetProfile, Depends(get_get_profile)],
    update_use_case: Annotated[UpdateProfile, Depends(get_update_profile)],
) -> UserResponse:
    try:
        # Un cuerpo vacío ({}) no cambia nada: se devuelve el perfil tal como está.
        if body.model_fields_set:
            user = update_use_case.execute(
                session.user_id, first_name=body.first_name, last_name=body.last_name
            )
        else:
            user = get_use_case.execute(session.user_id)
    except InvalidToken as error:
        raise unauthorized("La cuenta ya no existe.") from error
    return UserResponse.from_user(user)


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        **UNAUTHORIZED,
        # 403 y no 401, igual que en /password: un 401 haría que la app cerrara la sesión.
        403: {"model": ErrorResponse},
    },
)
def delete_account(
    body: DeleteAccountRequest,
    session: CurrentSession,
    use_case: Annotated[DeleteAccount, Depends(get_delete_account)],
) -> Response:
    # Borrado lógico: la cuenta se conserva en la base, se cierran todas las sesiones y el correo
    # queda libre para un registro nuevo.
    try:
        use_case.execute(session.user_id, body.password)
    except WrongCurrentPassword as error:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "La contraseña no es correcta.") from error
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
