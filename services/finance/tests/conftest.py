from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from finance_service.config import Settings
from finance_service.main import create_app


@pytest.fixture
def make_client() -> Callable[[str], TestClient]:
    def _make(app_env: str) -> TestClient:
        return TestClient(create_app(Settings(app_env=app_env)))

    return _make
