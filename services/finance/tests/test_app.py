import pytest
from pydantic import ValidationError

from finance_service.config import Settings


def test_finance_is_built_on_the_common_service_app(make_client) -> None:
    development, production = make_client("development"), make_client("production")

    title = development.get("/openapi.json").json()["info"]["title"]
    assert title == "Finance Balance API: finanzas"
    assert development.get("/health").json() == {"status": "ok"}
    assert production.get("/docs").status_code == 404
    assert "Strict-Transport-Security" in production.get("/health").headers


def test_unknown_environment_is_rejected(make_settings) -> None:
    with pytest.raises(ValidationError):
        make_settings(app_env="staging")


def test_database_url_is_required(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError, match="database_url"):
        Settings(_env_file=None)
