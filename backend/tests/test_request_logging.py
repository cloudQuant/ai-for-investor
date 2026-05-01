import asyncio
import json
import logging

import pytest
from fastapi import FastAPI, Request, Response
from fastapi.testclient import TestClient

from app.main import add_request_id, configure_logging, create_app, global_exception_handler


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(include_lifespan=False))


def json_log_messages(caplog: pytest.LogCaptureFixture) -> list[dict]:
    messages = []
    for record in caplog.records:
        try:
            messages.append(json.loads(record.getMessage()))
        except json.JSONDecodeError:
            continue
    return messages


def test_request_logs_include_request_id_for_successful_request(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        response = client.get("/health")

    request_id = response.headers["X-Request-ID"]
    logs = json_log_messages(caplog)
    started = [log for log in logs if log.get("event") == "request_started"]
    completed = [log for log in logs if log.get("event") == "request_completed"]

    assert response.status_code == 200
    assert started
    assert completed
    assert started[-1]["request_id"] == request_id
    assert started[-1]["method"] == "GET"
    assert started[-1]["path"] == "/health"
    assert completed[-1]["request_id"] == request_id
    assert completed[-1]["status_code"] == 200


@pytest.mark.asyncio
async def test_request_failure_log_includes_path_error_and_request_id(caplog: pytest.LogCaptureFixture) -> None:
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

    async def failing_call_next(_: Request) -> Response:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError):
            await add_request_id(request, failing_call_next)

    logs = json_log_messages(caplog)
    failed = [log for log in logs if log.get("event") == "request_failed"]

    assert failed
    assert failed[-1]["path"] == "/boom"
    assert failed[-1]["error"] == "boom"
    assert failed[-1]["request_id"] == request.state.request_id


@pytest.mark.asyncio
async def test_global_exception_log_and_response_are_safe(caplog: pytest.LogCaptureFixture) -> None:
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

    with caplog.at_level(logging.ERROR):
        response = await global_exception_handler(request, RuntimeError("boom"))

    body = json.loads(response.body)
    logs = json_log_messages(caplog)
    exception_logs = [log for log in logs if log.get("event") == "unhandled_exception"]

    assert response.status_code == 500
    assert body == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected error occurred",
        },
        "request_id": "abc12345",
    }
    assert "RuntimeError" not in response.body.decode()
    assert exception_logs
    assert exception_logs[-1]["path"] == "/boom"
    assert exception_logs[-1]["error"] == "boom"
    assert exception_logs[-1]["request_id"] == "abc12345"


def test_configure_logging_applies_environment_log_level() -> None:
    configure_logging("ERROR")

    assert logging.getLogger().getEffectiveLevel() == logging.ERROR

    configure_logging("INFO")
