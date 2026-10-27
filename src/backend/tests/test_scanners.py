import pytest
import sqlalchemy as sa
from httpx import AsyncClient, Response
from sqlalchemy import text

from tests.conftest import register_and_login


def _assert_scanner_data_unavailable(response: Response, expected_path: str) -> None:
    assert response.status_code == 503
    payload = response.json()
    assert set(payload) == {"error", "message", "request_id", "path"}
    assert payload["error"] == "HTTP_503"
    assert payload["message"] == "scanner_data_contract_unavailable"
    assert isinstance(payload["request_id"], str) and payload["request_id"]
    assert payload["path"] == expected_path


def _assert_scanner_schedule_validation_error(response: Response, expected_path: str) -> None:
    assert response.status_code == 400
    payload = response.json()
    assert set(payload) == {"error", "message", "request_id", "path"}
    assert payload["error"] == "HTTP_400"
    assert payload["message"] == "scanner_plan_schedule_enabled_must_be_boolean"
    assert isinstance(payload["request_id"], str) and payload["request_id"]
    assert payload["path"] == expected_path


def _scanner_plan_payload(
    name: str,
    *,
    include_schedule_enabled: bool = False,
    schedule_enabled: object = False,
) -> dict:
    payload = {
        "name": name,
        "universe_pool_id": "hs300",
        "indicator_rules": [],
        "condition": "indicator >= 0.6",
        "lookback_days": 20,
        "timeframe": "1d",
    }
    if include_schedule_enabled:
        payload["schedule_enabled"] = schedule_enabled
    return payload


def test_legacy_metric_snapshots_are_neither_exposed_as_current_nor_reused(tmp_path):
    import json

    from app.services.scanner_universe import ScannerUniverseService

    storage_path = tmp_path / "scanner_universe_pools.json"
    payload = {
        "built_in": {},
        "custom": {},
        "metric_snapshots": {
            "alice:hs300:20:1d": {
                "user_id": "alice",
                "pool_id": "hs300",
                "lookback_days": 20,
                "timeframe": "1d",
                "computed_at": "2026-06-19T04:00:00+00:00",
                "total": 1,
                "items": [
                    {
                        "symbol": "000001.SZ",
                        "price": 12.36,
                        "indicator": 0.91,
                        "provider": "seed_fallback",
                    }
                ],
            }
        },
    }
    storage_path.write_text(json.dumps(payload), encoding="utf-8")
    original = storage_path.read_bytes()
    service = ScannerUniverseService(
        storage_path=storage_path,
        market_client=FakeScannerMarketClient(),
    )

    pools = service.list_pools("alice")
    hs300 = next(item for item in pools["items"] if item["id"] == "hs300")

    assert hs300["metric_snapshot"] == {"data_status": "legacy_unverified"}
    assert service._get_metric_snapshot(
        user_id="alice",
        pool_id="hs300",
        lookback_days=20,
        timeframe="1d",
    ) is None
    assert storage_path.read_bytes() == original

    service.refresh_pool("hs300", "alice")
    persisted = json.loads(storage_path.read_text("utf-8"))
    assert persisted["metric_snapshots"]["alice:hs300:20:1d"] == payload["metric_snapshots"][
        "alice:hs300:20:1d"
    ]


class FakeScannerMarketClient:
    def __init__(self) -> None:
        self.context_calls = 0

    def fetch_pool_constituents(self, pool_id: str) -> list[dict]:
        assert pool_id == "hs300"
        return [
            {
                "symbol": "000001.SZ",
                "name": "平安银行",
                "asset_type": "equity",
                "exchange": "SZSE",
                "source": "akshare_fake",
            },
            {
                "symbol": "600519.SH",
                "name": "贵州茅台",
                "asset_type": "equity",
                "exchange": "SSE",
                "source": "akshare_fake",
            },
        ]

    def build_symbol_contexts(
        self,
        instruments: list[dict],
        *,
        lookback_days: int,
        timeframe: str,
    ) -> list[dict]:
        self.context_calls += 1
        rows = []
        for index, instrument in enumerate(instruments):
            rows.append(
                {
                    **instrument,
                    "price": 10.5 + index,
                    "volume": 1000000 + index * 10000,
                    "change_pct": 0.018 - index * 0.003,
                    "indicator": 0.72 - index * 0.04,
                    "factor": 0.67 - index * 0.03,
                    "news_sentiment": 0.55,
                    "portfolio_exposure": 0.0,
                    "provider": "akshare_fake",
                    "updated_at": "2026-06-19T04:00:00+00:00",
                    "lookback_days": lookback_days,
                    "timeframe": timeframe,
                }
            )
        return rows


def test_scanner_service_blocks_poolless_seed_contexts_and_marks_old_tasks_legacy(tmp_path):
    from app.services.scanner_service import ScannerService
    from app.services.scanner_universe import ScannerUniverseService

    market_client = FakeScannerMarketClient()
    service = ScannerService(
        universe_service=ScannerUniverseService(
            storage_path=tmp_path / "scanner_universe_pools.json",
            market_client=market_client,
        )
    )

    with pytest.raises(ValueError, match="scanner_data_contract_unavailable"):
        service.run(["RB2510", "IF2510"], "indicator > 0.5")

    assert market_client.context_calls == 0
    assert service._tasks == {}

    service._tasks["legacy-task"] = {
        "status": "completed",
        "matches": [{"symbol": "RB2510", "indicator": 0.77}],
    }
    task = service.get_task("legacy-task")
    assert task is not None
    assert task["status"] == "legacy_unverified"
    assert task["data_status"] == "legacy_unverified"
    assert task["matches"][0]["symbol"] == "RB2510"


@pytest.mark.asyncio
async def test_scanner_run_fails_closed_before_creating_a_task(client: AsyncClient):
    _, headers = await register_and_login(client, username="scanner_user")

    response = await client.post(
        "/api/v1/scanners/run",
        headers=headers,
        json={
            "universe": ["RB2510", "IF2510"],
            "condition": (
                "indicator > 0.6 and news_sentiment > 0.5 "
                "and lookback_days >= 20 and timeframe == '1d'"
            ),
            "lookback_days": 20,
            "timeframe": "1d",
        },
    )
    _assert_scanner_data_unavailable(response, "/api/v1/scanners/run")


@pytest.mark.asyncio
async def test_scanner_rejects_unsafe_expression(client: AsyncClient):
    _, headers = await register_and_login(client, username="scanner_unsafe")

    response = await client.post(
        "/api/v1/scanners/run",
        headers=headers,
        json={"universe": ["RB2510"], "condition": "__import__('os').system('x')"},
    )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_scanner_universe_pool_management_does_not_enable_execution(
    client: AsyncClient, tmp_path, monkeypatch
):
    from app.api import scanners as scanners_api
    from app.services.scanner_service import ScannerService
    from app.services.scanner_universe import ScannerUniverseService

    service = ScannerService(
        universe_service=ScannerUniverseService(
            storage_path=tmp_path / "scanner_universe_pools.json",
            market_client=FakeScannerMarketClient(),
        )
    )
    monkeypatch.setattr(scanners_api, "get_scanner_service", lambda: service)

    _, headers = await register_and_login(client, username="scanner_universe_user")

    pools = await client.get("/api/v1/scanners/universe-pools", headers=headers)
    assert pools.status_code == 200
    assert any(item["id"] == "hs300" for item in pools.json()["items"])

    refreshed = await client.post(
        "/api/v1/scanners/universe-pools/hs300/refresh",
        headers=headers,
    )
    assert refreshed.status_code == 200
    refreshed_body = refreshed.json()
    assert refreshed_body["id"] == "hs300"
    assert refreshed_body["instrument_count"] == 2
    assert refreshed_body["instruments"][0]["symbol"] == "000001.SZ"
    assert refreshed_body["last_refresh_status"] == "ok"

    custom = await client.post(
        "/api/v1/scanners/universe-pools/custom",
        headers=headers,
        json={
            "name": "我的观察池",
            "description": "用户手动维护的标的池",
            "instruments": [
                {"symbol": "300750.SZ", "name": "宁德时代", "asset_type": "equity"},
                {"symbol": "110000.SH", "name": "测试转债", "asset_type": "convertible_bond"},
            ],
        },
    )
    assert custom.status_code == 200
    custom_body = custom.json()
    assert custom_body["is_custom"] is True
    assert custom_body["instrument_count"] == 2

    response = await client.post(
        "/api/v1/scanners/run",
        headers=headers,
        json={
            "universe_pool_id": custom_body["id"],
            "condition": "price > 0 and indicator >= 0.6",
            "lookback_days": 30,
            "timeframe": "1d",
        },
    )

    _assert_scanner_data_unavailable(response, "/api/v1/scanners/run")
    assert service._tasks == {}
    assert service.universe_service.market_client.context_calls == 0


@pytest.mark.asyncio
async def test_scanner_precompute_and_run_do_not_call_provider_or_write_cache(
    client: AsyncClient, tmp_path, monkeypatch
):
    from app.api import scanners as scanners_api
    from app.services.scanner_service import ScannerService
    from app.services.scanner_universe import ScannerUniverseService

    fake_market_client = FakeScannerMarketClient()
    service = ScannerService(
        universe_service=ScannerUniverseService(
            storage_path=tmp_path / "scanner_universe_pools.json",
            market_client=fake_market_client,
        )
    )
    monkeypatch.setattr(scanners_api, "get_scanner_service", lambda: service)

    _, headers = await register_and_login(client, username="scanner_precompute_user")

    refreshed = await client.post(
        "/api/v1/scanners/universe-pools/hs300/refresh",
        headers=headers,
    )
    assert refreshed.status_code == 200

    precomputed = await client.post(
        "/api/v1/scanners/universe-pools/hs300/precompute",
        headers=headers,
        json={"lookback_days": 20, "timeframe": "1d"},
    )
    _assert_scanner_data_unavailable(
        precomputed,
        "/api/v1/scanners/universe-pools/hs300/precompute",
    )
    assert fake_market_client.context_calls == 0

    response = await client.post(
        "/api/v1/scanners/run",
        headers=headers,
        json={
            "universe_pool_id": "hs300",
            "condition": "price > 0 and indicator >= 0.6",
            "lookback_days": 20,
            "timeframe": "1d",
        },
    )

    _assert_scanner_data_unavailable(response, "/api/v1/scanners/run")
    assert fake_market_client.context_calls == 0

    state = (tmp_path / "scanner_universe_pools.json").read_text("utf-8")
    assert '"metric_snapshots": {}' in state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("include_schedule_enabled", "schedule_enabled", "expected"),
    [(False, False, False), (True, True, True), (True, False, False)],
)
async def test_scanner_plan_create_schedule_enabled_defaults_off_and_keeps_explicit_value(
    client: AsyncClient,
    include_schedule_enabled: bool,
    schedule_enabled: bool,
    expected: bool,
):
    _, headers = await register_and_login(client, username="scanner_schedule_create_user")
    payload = _scanner_plan_payload(
        "schedule-create",
        include_schedule_enabled=include_schedule_enabled,
        schedule_enabled=schedule_enabled,
    )

    response = await client.post("/api/v1/scanners/plans", headers=headers, json=payload)

    assert response.status_code == 200
    assert response.json()["schedule_enabled"] is expected


@pytest.mark.asyncio
async def test_scanner_plan_save_without_schedule_enabled_preserves_existing_explicit_true(
    client: AsyncClient,
):
    _, headers = await register_and_login(client, username="scanner_schedule_resave_user")
    created = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json=_scanner_plan_payload(
            "schedule-resave",
            include_schedule_enabled=True,
            schedule_enabled=True,
        ),
    )
    assert created.status_code == 200

    response = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json=_scanner_plan_payload("schedule-resave"),
    )

    assert response.status_code == 200
    assert response.json()["id"] == created.json()["id"]
    assert response.json()["schedule_enabled"] is True


def test_scanner_plan_model_client_default_is_disabled():
    from app.models.scanner_plan import ScannerPlanModel

    column = ScannerPlanModel.__table__.c.schedule_enabled

    assert column.default is not None
    assert column.default.arg is False
    assert column.server_default is None


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_value", [True, False])
async def test_scanner_plan_patch_without_schedule_enabled_preserves_existing_value(
    client: AsyncClient, initial_value: bool
):
    _, headers = await register_and_login(client, username="scanner_schedule_patch_user")
    created = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json=_scanner_plan_payload(
            "schedule-patch-preserve",
            include_schedule_enabled=True,
            schedule_enabled=initial_value,
        ),
    )
    assert created.status_code == 200

    response = await client.patch(
        f"/api/v1/scanners/plans/{created.json()['id']}",
        headers=headers,
        json=_scanner_plan_payload("schedule-patch-preserve-updated"),
    )

    assert response.status_code == 200
    assert response.json()["schedule_enabled"] is initial_value


@pytest.mark.asyncio
@pytest.mark.parametrize("schedule_enabled", [True, False])
async def test_scanner_plan_patch_accepts_explicit_json_boolean(
    client: AsyncClient, schedule_enabled: bool
):
    _, headers = await register_and_login(client, username="scanner_schedule_patch_bool_user")
    created = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json=_scanner_plan_payload("schedule-patch-explicit"),
    )
    assert created.status_code == 200

    response = await client.patch(
        f"/api/v1/scanners/plans/{created.json()['id']}",
        headers=headers,
        json=_scanner_plan_payload(
            "schedule-patch-explicit-updated",
            include_schedule_enabled=True,
            schedule_enabled=schedule_enabled,
        ),
    )

    assert response.status_code == 200
    assert response.json()["schedule_enabled"] is schedule_enabled


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_value", [None, "false", 0, 1])
async def test_scanner_plan_schedule_enabled_rejects_non_boolean_without_mutating_plan(
    client: AsyncClient, invalid_value: object
):
    _, headers = await register_and_login(client, username="scanner_schedule_invalid_user")

    invalid_create_payload = _scanner_plan_payload(
        "invalid-schedule-create",
        include_schedule_enabled=True,
        schedule_enabled=invalid_value,
    )
    invalid_create = await client.post(
        "/api/v1/scanners/plans", headers=headers, json=invalid_create_payload
    )
    _assert_scanner_schedule_validation_error(
        invalid_create,
        "/api/v1/scanners/plans",
    )

    created = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json=_scanner_plan_payload(
            "valid-schedule-plan",
            include_schedule_enabled=True,
            schedule_enabled=True,
        ),
    )
    assert created.status_code == 200

    invalid_update_payload = _scanner_plan_payload(
        "should-not-be-saved",
        include_schedule_enabled=True,
        schedule_enabled=invalid_value,
    )
    invalid_update = await client.patch(
        f"/api/v1/scanners/plans/{created.json()['id']}",
        headers=headers,
        json=invalid_update_payload,
    )
    _assert_scanner_schedule_validation_error(
        invalid_update,
        f"/api/v1/scanners/plans/{created.json()['id']}",
    )

    plans = await client.get("/api/v1/scanners/plans", headers=headers)
    plan = next(item for item in plans.json()["items"] if item["id"] == created.json()["id"])
    assert plan["name"] == "valid-schedule-plan"
    assert plan["schedule_enabled"] is True


@pytest.mark.asyncio
async def test_scanner_plan_runs_stay_unavailable_and_preserve_legacy_results(
    client: AsyncClient, tmp_path, monkeypatch
):
    from app.api import scanners as scanners_api
    from app.db import database as db_module
    from app.models.scanner_plan import ScannerPlanModel, ScannerPlanRunModel
    from app.services.scanner_service import ScannerService
    from app.services.scanner_universe import ScannerUniverseService

    fake_market_client = FakeScannerMarketClient()
    service = ScannerService(
        universe_service=ScannerUniverseService(
            storage_path=tmp_path / "scanner_universe_pools.json",
            market_client=fake_market_client,
        )
    )
    monkeypatch.setattr(scanners_api, "get_scanner_service", lambda: service)

    _, headers = await register_and_login(client, username="scanner_plan_user")
    refreshed = await client.post(
        "/api/v1/scanners/universe-pools/hs300/refresh",
        headers=headers,
    )
    assert refreshed.status_code == 200

    created = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json={
            "name": "沪深300动量日报",
            "universe_pool_id": "hs300",
            "indicator_rules": [
                {"metric": "indicator", "operator": ">=", "value": 0.6, "enabled": True},
                {"metric": "news_sentiment", "operator": ">=", "value": 0.5, "enabled": True},
            ],
            "condition": "indicator >= 0.6 and news_sentiment >= 0.5",
            "lookback_days": 20,
            "timeframe": "1d",
            "schedule_enabled": True,
            "schedule_frequency": "daily",
        },
    )
    assert created.status_code == 200
    plan = created.json()
    assert plan["id"]
    assert plan["name"] == "沪深300动量日报"
    assert plan["schedule_enabled"] is True

    result_table_plan = await client.post(
        f"/api/v1/scanners/plans/{plan['id']}/result-table",
        headers=headers,
    )
    assert result_table_plan.status_code == 200
    table_name = result_table_plan.json()["result_table_name"]
    assert result_table_plan.json()["result_table_data_status"] == "legacy_unverified"

    async with db_module.async_session_maker() as db:
        plan_row = await db.get(ScannerPlanModel, plan["id"])
        assert plan_row is not None
        db.add(
            ScannerPlanRunModel(
                owner_id=plan_row.owner_id,
                plan_id=plan["id"],
                run_date="2026-06-19",
                status="completed",
                universe_pool_id="hs300",
                condition="indicator >= 0.6 and news_sentiment >= 0.5",
                lookback_days=20,
                timeframe="1d",
                universe_count=2,
                match_count=1,
                matches=[{"symbol": "000001.SZ", "indicator": 0.91}],
                metrics={"factor_cache_status": "hit"},
            )
        )
        await db.commit()

    async with db_module.engine.begin() as conn:
        insert_result = text(
            f'INSERT INTO "{table_name}" '
            "(id, plan_id, run_id, run_date, symbol, payload_json, created_at) "
            "VALUES (:id, :plan_id, :run_id, :run_date, :symbol, :payload_json, :created_at)"
        )
        await conn.execute(
            insert_result,
            {
                "id": "legacy-result-row",
                "plan_id": plan["id"],
                "run_id": "legacy-run",
                "run_date": "2026-06-19",
                "symbol": "000001.SZ",
                "payload_json": '{"symbol":"000001.SZ","indicator":0.91}',
                "created_at": "2026-06-19T04:00:00",
            },
        )

    daily = await client.post(
        "/api/v1/scanners/plans/daily-runs",
        headers=headers,
        json={"run_date": "2026-06-19"},
    )
    assert daily.status_code == 200
    daily_body = daily.json()
    assert daily_body["run_date"] == "2026-06-19"
    assert daily_body["total"] == 1
    run = daily_body["items"][0]
    assert run["plan_id"] == plan["id"]
    assert run["status"] == "unavailable"
    assert run["data_status"] == "unavailable"
    assert run["error"] == "scanner_data_contract_unavailable"
    assert run["match_count"] == 0
    assert run["matches"] == []
    assert fake_market_client.context_calls == 0

    history = await client.get(
        f"/api/v1/scanners/plans/{plan['id']}/runs",
        headers=headers,
    )
    assert history.status_code == 200
    history_body = history.json()
    assert history_body["total"] == 1
    assert history_body["items"][0]["run_date"] == "2026-06-19"
    assert history_body["items"][0]["status"] == "legacy_unverified"
    assert history_body["items"][0]["legacy_status"] == "completed"
    assert history_body["items"][0]["data_status"] == "legacy_unverified"
    assert history_body["items"][0]["matches"][0]["symbol"] == "000001.SZ"

    duplicate = await client.post(
        "/api/v1/scanners/plans/daily-runs",
        headers=headers,
        json={"run_date": "2026-06-19"},
    )
    assert duplicate.status_code == 200
    duplicate_run = duplicate.json()["items"][0]
    assert duplicate_run["status"] == "unavailable"
    assert duplicate_run["cache_status"] == "skipped"
    assert fake_market_client.context_calls == 0

    forced = await client.post(
        f"/api/v1/scanners/plans/{plan['id']}/runs",
        headers=headers,
        json={"run_date": "2026-06-19", "force": True},
    )
    assert forced.status_code == 200
    assert forced.json()["status"] == "unavailable"
    history_after_force = await client.get(
        f"/api/v1/scanners/plans/{plan['id']}/runs",
        headers=headers,
    )
    assert history_after_force.json()["total"] == 1
    assert history_after_force.json()["items"][0]["matches"][0]["symbol"] == "000001.SZ"

    async with db_module.engine.begin() as conn:
        preserved = await conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
    assert preserved.scalar_one() == 1


@pytest.mark.asyncio
async def test_scanner_plan_can_be_updated_deleted_and_manage_result_table(
    client: AsyncClient, tmp_path, monkeypatch
):
    from app.api import scanners as scanners_api
    from app.db import database as db_module
    from app.services.scanner_service import ScannerService
    from app.services.scanner_universe import ScannerUniverseService

    service = ScannerService(
        universe_service=ScannerUniverseService(
            storage_path=tmp_path / "scanner_universe_pools.json",
            market_client=FakeScannerMarketClient(),
        )
    )
    monkeypatch.setattr(scanners_api, "get_scanner_service", lambda: service)

    _, headers = await register_and_login(client, username="scanner_plan_crud_user")
    refreshed = await client.post(
        "/api/v1/scanners/universe-pools/hs300/refresh",
        headers=headers,
    )
    assert refreshed.status_code == 200

    created = await client.post(
        "/api/v1/scanners/plans",
        headers=headers,
        json={
            "name": "沪深300动量日报",
            "universe_pool_id": "hs300",
            "indicator_rules": [
                {"metric": "indicator", "operator": ">=", "value": 0.6, "enabled": True},
            ],
            "condition": "indicator >= 0.6",
            "lookback_days": 20,
            "timeframe": "1d",
            "schedule_enabled": True,
            "schedule_frequency": "daily",
        },
    )
    assert created.status_code == 200
    plan = created.json()

    updated = await client.patch(
        f"/api/v1/scanners/plans/{plan['id']}",
        headers=headers,
        json={
            "name": "沪深300质量动量",
            "universe_pool_id": "hs300",
            "indicator_rules": [
                {"metric": "factor", "operator": ">=", "value": 0.65, "enabled": True},
                {"metric": "portfolio_exposure", "operator": "<=", "value": 0.2, "enabled": True},
            ],
            "condition": "factor >= 0.65 and portfolio_exposure <= 0.2",
            "lookback_days": 60,
            "timeframe": "4h",
            "schedule_enabled": False,
            "schedule_frequency": "daily",
            "status": "active",
        },
    )
    assert updated.status_code == 200
    updated_body = updated.json()
    assert updated_body["id"] == plan["id"]
    assert updated_body["name"] == "沪深300质量动量"
    assert updated_body["lookback_days"] == 60
    assert updated_body["timeframe"] == "4h"
    assert updated_body["schedule_enabled"] is False

    created_table = await client.post(
        f"/api/v1/scanners/plans/{plan['id']}/result-table",
        headers=headers,
    )
    assert created_table.status_code == 200
    table_body = created_table.json()
    assert table_body["result_table_status"] == "ready"
    assert table_body["result_table_name"].startswith("scanner_plan_result_")

    async with db_module.engine.begin() as conn:
        table_exists = await conn.run_sync(
            lambda sync_conn: sa.inspect(sync_conn).has_table(table_body["result_table_name"])
        )
    assert table_exists is True

    dropped_table = await client.delete(
        f"/api/v1/scanners/plans/{plan['id']}/result-table",
        headers=headers,
    )
    assert dropped_table.status_code == 200
    assert dropped_table.json()["result_table_status"] == "dropped"

    async with db_module.engine.begin() as conn:
        table_exists = await conn.run_sync(
            lambda sync_conn: sa.inspect(sync_conn).has_table(table_body["result_table_name"])
        )
    assert table_exists is False

    deleted = await client.delete(
        f"/api/v1/scanners/plans/{plan['id']}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": True}

    listed = await client.get("/api/v1/scanners/plans", headers=headers)
    assert listed.status_code == 200
    assert all(item["id"] != plan["id"] for item in listed.json()["items"])
