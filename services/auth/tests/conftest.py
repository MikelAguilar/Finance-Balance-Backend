import os
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, settings

from auth_service.config import Settings
from auth_service.main import create_app

# Puerto cerrado a propósito: si una prueba sin base llega a conectarse, falla al instante.
DATABASE_URL = "postgresql+psycopg://test:test@127.0.0.1:1/test?connect_timeout=1"
# Repetitivo a propósito: es de pruebas y no debe parecer un secreto real.
JWT_SECRET = "pruebas" * 6

# Hypothesis genera entradas al azar. En local prueba 100 casos por propiedad; en CI, 500.
# Sin límite de tiempo por caso: Argon2 es lento a propósito.
settings.register_profile("default", max_examples=100, deadline=None)
settings.register_profile(
    "ci", max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))


@pytest.fixture
def make_client() -> Callable[[str], TestClient]:
    def _make(app_env: str) -> TestClient:
        settings = Settings(app_env=app_env, database_url=DATABASE_URL, jwt_secret=JWT_SECRET)
        return TestClient(create_app(settings))

    return _make
