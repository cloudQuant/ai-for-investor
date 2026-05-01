from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import HTTPException, Request

from app.api.v1 import tools
from app.models.tool import Tool


class FakeScalarResult:
    def __init__(self, value: Any = None, values: list[Any] | None = None) -> None:
        self.value = value
        self.values = values or []

    def scalar_one_or_none(self) -> Any:
        return self.value

    def scalars(self) -> "FakeScalarResult":
        return self

    def all(self) -> list[Any]:
        return self.values


class FakeSession:
    def __init__(self, results: list[FakeScalarResult]) -> None:
        self.results = results

    async def execute(self, statement: Any) -> FakeScalarResult:
        if self.results:
            return self.results.pop(0)
        return FakeScalarResult()


def make_request() -> Request:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/v1/tools/tools",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
            "scheme": "http",
        }
    )
    request.state.request_id = "req-tools"
    return request


def make_tool(slug: str = "backtest-demo", risk_level: str = "medium", run_mode: str = "internal") -> Tool:
    now = datetime.now(timezone.utc)
    return Tool(
        id=1,
        name="Backtest Demo",
        slug=slug,
        description="Educational AI investing backtest demo.",
        risk_level=risk_level,
        run_mode=run_mode,
        source_url="https://github.com/example/backtest-demo",
        license="MIT",
        resource_cost="cpu: low, memory: 512MB",
        usage_limitations="Uses delayed sample data only; no broker or exchange execution.",
        financial_risk_reminder="Educational output only; not investment advice or a return guarantee.",
        execution_risk_reminder="Do not connect to real accounts or execute trades from demo output.",
        is_active=True,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_tool_catalog_is_public_and_distinguishes_run_modes() -> None:
    runnable = make_tool(run_mode="internal")
    document = make_tool(slug="doc-tool", risk_level="high", run_mode="document")
    db = FakeSession([FakeScalarResult(values=[runnable, document])])

    response = await tools.list_tools(make_request(), db)

    assert len(response["data"]) == 2
    assert response["data"][0]["access_type"] == "runnable_demo"
    assert response["data"][1]["access_type"] == "documentation_only"


@pytest.mark.asyncio
async def test_tool_detail_shows_required_public_safety_metadata() -> None:
    tool = make_tool()
    db = FakeSession([FakeScalarResult(tool)])

    response = await tools.get_tool("backtest-demo", make_request(), db)
    data = response["data"]

    assert data["source_url"] == "https://github.com/example/backtest-demo"
    assert data["license"] == "MIT"
    assert data["risk_level"] == "medium"
    assert data["run_mode"] == "internal"
    assert data["resource_cost"] == "cpu: low, memory: 512MB"
    assert data["usage_limitations"] == "Uses delayed sample data only; no broker or exchange execution."
    assert "not investment advice" in data["financial_risk_reminder"].lower()
    assert "execute trades" in data["execution_risk_reminder"].lower()


@pytest.mark.asyncio
async def test_high_risk_tool_cannot_be_exposed_as_internal_runnable_demo() -> None:
    unsafe = make_tool(risk_level="high", run_mode="internal")
    db = FakeSession([FakeScalarResult(unsafe)])

    with pytest.raises(HTTPException) as exc:
        await tools.get_tool("backtest-demo", make_request(), db)

    assert exc.value.status_code == 400
    assert exc.value.detail == "High-risk tools must use document or external mode"


@pytest.mark.asyncio
async def test_inactive_tool_is_not_public() -> None:
    db = FakeSession([FakeScalarResult(None)])

    with pytest.raises(HTTPException) as exc:
        await tools.get_tool("missing", make_request(), db)

    assert exc.value.status_code == 404
