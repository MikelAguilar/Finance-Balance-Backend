def test_health_responde_ok(crear_cliente) -> None:
    client = crear_cliente("development")

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_swagger_disponible_en_desarrollo(crear_cliente) -> None:
    client = crear_cliente("development")

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_swagger_desactivado_en_produccion(crear_cliente) -> None:
    client = crear_cliente("production")

    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
