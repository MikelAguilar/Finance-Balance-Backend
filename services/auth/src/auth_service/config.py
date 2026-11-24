from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["development", "production"] = "development"
    database_url: str
    # Firma los tokens de acceso. 32 caracteres como mínimo (256 bits para HS256).
    jwt_secret: SecretStr = Field(min_length=32)
    access_token_minutes: int = Field(default=15, gt=0)
    refresh_token_days: int = Field(default=90, gt=0)
    # Límite de intentos: tras este número de fallos en la ventana, el correo queda bloqueado.
    login_max_attempts: int = Field(default=5, gt=0)
    login_window_minutes: int = Field(default=15, gt=0)
