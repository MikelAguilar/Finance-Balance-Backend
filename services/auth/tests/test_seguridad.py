import pytest

CABECERAS_SIEMPRE = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

CABECERAS_PRODUCCION = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_cabeceras_basicas_en_todos_los_entornos(crear_cliente, app_env) -> None:
    response = crear_cliente(app_env).get("/health")

    for nombre, valor in CABECERAS_SIEMPRE.items():
        assert response.headers[nombre] == valor


def test_https_y_csp_solo_en_produccion(crear_cliente) -> None:
    response = crear_cliente("production").get("/health")

    for nombre, valor in CABECERAS_PRODUCCION.items():
        assert response.headers[nombre] == valor


def test_desarrollo_no_fuerza_https_ni_bloquea_swagger(crear_cliente) -> None:
    response = crear_cliente("development").get("/docs")

    assert response.status_code == 200
    for nombre in CABECERAS_PRODUCCION:
        assert nombre not in response.headers


def test_cabeceras_tambien_en_errores(crear_cliente) -> None:
    response = crear_cliente("production").get("/no-existe")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_sin_cors_aunque_llegue_origin(crear_cliente) -> None:
    client = crear_cliente("production")

    simple = client.get("/health", headers={"Origin": "https://sitio-ajeno.example"})
    preflight = client.options(
        "/health",
        headers={
            "Origin": "https://sitio-ajeno.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    for response in (simple, preflight):
        assert "access-control-allow-origin" not in response.headers
