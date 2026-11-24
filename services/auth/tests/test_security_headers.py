import pytest

ALWAYS_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}

PRODUCTION_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_basic_headers_in_every_environment(make_client, app_env) -> None:
    response = make_client(app_env).get("/health")

    for name, value in ALWAYS_HEADERS.items():
        assert response.headers[name] == value


def test_hsts_and_csp_only_in_production(make_client) -> None:
    response = make_client("production").get("/health")

    for name, value in PRODUCTION_HEADERS.items():
        assert response.headers[name] == value


def test_development_does_not_force_https_or_block_swagger(make_client) -> None:
    response = make_client("development").get("/docs")

    assert response.status_code == 200
    for name in PRODUCTION_HEADERS:
        assert name not in response.headers


def test_headers_are_added_to_error_responses(make_client) -> None:
    response = make_client("production").get("/no-existe")

    assert response.status_code == 404
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_no_cors_even_with_origin_header(make_client) -> None:
    client = make_client("production")

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
