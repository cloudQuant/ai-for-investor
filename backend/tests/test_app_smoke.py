import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app, global_exception_handler


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(include_lifespan=False))


def test_app_uses_configured_metadata() -> None:
    app = create_app(include_lifespan=False)

    assert app.title == settings.APP_NAME
    assert app.version == settings.APP_VERSION


def test_health_check_returns_service_metadata(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


def test_health_check_includes_request_id_header(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["X-Request-ID"]
    assert len(response.headers["X-Request-ID"]) == 8


def test_openapi_document_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert payload["info"]["title"] == settings.APP_NAME
    assert payload["info"]["version"] == settings.APP_VERSION
    assert "/health" in payload["paths"]


def test_api_routes_use_v1_prefix() -> None:
    app = create_app(include_lifespan=False)
    api_paths = [route.path for route in app.routes if route.path.startswith("/api/")]

    assert api_paths
    assert all(path.startswith("/api/v1/") for path in api_paths)


@pytest.mark.asyncio
async def test_global_exception_handler_returns_structured_error() -> None:
    app = FastAPI()
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/boom",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "scheme": "http",
            "app": app,
        }
    )
    request.state.request_id = "abc12345"

    response = await global_exception_handler(request, RuntimeError("boom"))

    assert response.status_code == 500
    assert response.body
    assert b"INTERNAL_SERVER_ERROR" in response.body
    assert b"abc12345" in response.body
