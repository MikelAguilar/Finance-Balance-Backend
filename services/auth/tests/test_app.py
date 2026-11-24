def test_health_returns_ok(make_client) -> None:
    client = make_client("development")

    response = client.get("/health")

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
