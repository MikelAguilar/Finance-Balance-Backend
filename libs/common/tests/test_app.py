from contextlib import asynccontextmanager

from fastapi.testclient import TestClient

from service_common.app import create_service_app


def test_health_returns_ok(make_client) -> None:
    response = make_client("development").get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_available_in_development(make_client) -> None:
    client = make_client("development")

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").json()["info"]["title"] == "Servicio de prueba"


def test_swagger_disabled_in_production(make_client) -> None:
    client = make_client("production")

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_lifespan_runs_on_start_and_stop() -> None:
    events = []

    @asynccontextmanager
    async def lifespan(_):
        events.append("start")
        yield
        events.append("stop")

    with TestClient(create_service_app(title="x", production=True, lifespan=lifespan)):
        assert events == ["start"]
    assert events == ["start", "stop"]
