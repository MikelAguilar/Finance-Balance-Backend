"""Endpoints de cuentas y sesiones. El gateway los publica bajo /auth."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field

from auth_service.application.use_cases import LogIn, RegisterUser
from auth_service.domain.errors import EmailAlreadyRegistered, InvalidCredentials, WeakPassword
from auth_service.domain.model import MAX_PASSWORD_LENGTH

router = APIRouter(tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    # El mínimo lo valida el dominio; el máximo aquí evita procesar textos enormes.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    id: UUID
    email: str
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    device_id: str = Field(min_length=1, max_length=100)
    device_name: str = Field(min_length=1, max_length=100)


class TokenResponse(BaseModel):
    token_type: Literal["bearer"] = "bearer"
    access_token: str
    access_token_expires_at: datetime
    refresh_token: str
    refresh_token_expires_at: datetime
    session_id: UUID


class ErrorResponse(BaseModel):
    detail: str


def get_register_user(request: Request) -> RegisterUser:
    return request.app.state.register_user


def get_log_in(request: Request) -> LogIn:
    return request.app.state.log_in


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
    responses={401: {"model": ErrorResponse}},
)
def log_in(body: LoginRequest, use_case: Annotated[LogIn, Depends(get_log_in)]) -> TokenResponse:
    try:
        result = use_case.execute(body.email, body.password, body.device_id, body.device_name)
    except InvalidCredentials as error:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Correo o contraseña incorrectos.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from error
    return TokenResponse(
        access_token=result.access_token,
        access_token_expires_at=result.access_token_expires_at,
        refresh_token=result.refresh_token,
        refresh_token_expires_at=result.refresh_token_expires_at,
        session_id=result.session_id,
    )
