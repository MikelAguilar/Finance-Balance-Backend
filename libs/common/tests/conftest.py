from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from service_common.app import create_service_app


@pytest.fixture
def make_client() -> Callable[[str], TestClient]:
    def _make(app_env: str) -> TestClient:
        app = create_service_app(title="Servicio de prueba", production=app_env == "production")
        return TestClient(app)

    return _make
