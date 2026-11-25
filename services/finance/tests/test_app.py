import pytest


def test_health_returns_ok(make_client) -> None:
    response = make_client("development").get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_available_in_development(make_client) -> None:
    client = make_client("development")

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_swagger_disabled_in_production(make_client) -> None:
    client = make_client("production")

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_security_headers_on_every_response(make_client, app_env) -> None:
    response = make_client(app_env).get("/no-existe")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_hsts_only_in_production(make_client) -> None:
    assert "Strict-Transport-Security" in make_client("production").get("/health").headers
    assert "Strict-Transport-Security" not in make_client("development").get("/health").headers


def test_unknown_environment_is_rejected() -> None:
    from pydantic import ValidationError

    from finance_service.config import Settings

    with pytest.raises(ValidationError):
        Settings(app_env="staging")
