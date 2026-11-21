from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

DATABASE_URL = "postgresql+psycopg://test:test@localhost:5432/test"


def build_client(app_env: str) -> TestClient:
    settings = Settings(app_env=app_env, database_url=DATABASE_URL)
    return TestClient(create_app(settings))


def test_health_responde_ok() -> None:
    client = build_client("development")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_disponible_en_desarrollo() -> None:
    client = build_client("development")

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_swagger_desactivado_en_produccion() -> None:
    client = build_client("production")

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
