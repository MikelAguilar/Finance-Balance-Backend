import pytest
from pydantic import ValidationError

from finance_service.config import Settings


def test_finance_is_built_on_the_common_service_app(make_client) -> None:
    development, production = make_client("development"), make_client("production")

    assert development.get("/openapi.json").json()["info"]["title"].endswith("finanzas")
    assert development.get("/health").json() == {"status": "ok"}
    assert production.get("/docs").status_code == 404
    assert "Strict-Transport-Security" in production.get("/health").headers


def test_unknown_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(app_env="staging")
