"""Regression tests for Iteration 206 security & tenant isolation fixes (OCR-11, OCR-12)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.db.database import create_default_admin
from app.services.live_trading.manager import LiveTradingManager
from tests.conftest import register_and_login


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    await create_default_admin()
    settings = get_settings()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
    )
    assert resp.status_code == 200
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_risk_control_and_auto_trading_config_require_admin_and_bound_order_size(
    client: AsyncClient,
) -> None:
    _, user_headers = await register_and_login(client, username="ordinary_risk_user")
    admin_hdrs = await _admin_headers(client)

    payload = {
        "max_position_pct": 25.0,
        "max_total_position_pct": 75.0,
        "max_daily_loss_pct": 4.0,
        "max_drawdown_pct": 15.0,
        "stop_loss_pct": 3.0,
        "take_profit_pct": 15.0,
        "max_daily_trades": 40,
        "max_order_size": 50000.0,
        "enable_stop_loss": True,
        "enable_take_profit": True,
        "enable_position_limit": True,
    }

    assert (
        await client.put("/api/v1/risk-control/config", headers=user_headers, json=payload)
    ).status_code == 403
    assert (
        await client.post("/api/v1/risk-control/reset-daily", headers=user_headers)
    ).status_code == 403
    assert (
        await client.delete("/api/v1/risk-control/alerts", headers=user_headers)
    ).status_code == 403
    assert (
        await client.delete(
            "/api/v1/risk-control/alerts?instance_id=other-users-instance",
            headers=user_headers,
        )
    ).status_code == 403
    assert (
        await client.put(
            "/api/v1/auto-trading/config",
            headers=user_headers,
            json={"enabled": True},
        )
    ).status_code == 403

    # Admin updates succeed, and unbounded max_order_size is rejected with 422
    ok_risk = await client.put("/api/v1/risk-control/config", headers=admin_hdrs, json=payload)
    assert ok_risk.status_code == 200
    assert ok_risk.json()["max_order_size"] == 50000.0

    bad_payload = {**payload, "max_order_size": 10**12}
    too_large = await client.put(
        "/api/v1/risk-control/config", headers=admin_hdrs, json=bad_payload
    )
    assert too_large.status_code == 422

    ok_auto = await client.put(
        "/api/v1/auto-trading/config",
        headers=admin_hdrs,
        json={"enabled": True},
    )
    assert ok_auto.status_code == 200
    assert (
        await client.post("/api/v1/risk-control/reset-daily", headers=admin_hdrs)
    ).status_code == 200


@pytest.mark.asyncio
async def test_simulation_isolates_instance_config_and_logs_from_other_users_and_templates(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import app.api.simulation as sim_api
    import app.services.live_trading.manager as live_manager_mod

    template_root = tmp_path / "strategies"
    tpl_dir = template_root / "simulate" / "demo_strat"
    (tpl_dir / "logs" / "20261120").mkdir(parents=True)
    (tpl_dir / "run.py").write_text("print('run')\n", encoding="utf-8")
    (tpl_dir / "config.yaml").write_text("params:\n  shared: true\n", encoding="utf-8")
    (tpl_dir / "logs" / "20261120" / "value.log").write_text("shared-log\n", encoding="utf-8")

    monkeypatch.setattr(sim_api, "STRATEGIES_DIR", template_root)
    monkeypatch.setattr(sim_api, "_SIMULATION_RUNTIMES_ROOT", tmp_path / "sim_runtimes")
    monkeypatch.setattr(
        sim_api,
        "get_strategy_dir",
        lambda sid: (template_root / sid).resolve(),
    )

    store: dict[str, dict] = {}
    instances_file = tmp_path / "instances.json"
    monkeypatch.setattr(live_manager_mod, "_INSTANCES_FILE", instances_file)
    monkeypatch.setattr(live_manager_mod, "_load_instances", lambda: store)
    monkeypatch.setattr(live_manager_mod, "_save_instances", lambda data: store.update(data))
    mgr = LiveTradingManager()
    monkeypatch.setattr(sim_api, "_get_manager", lambda: mgr)

    from app.main import app as fastapi_app

    fastapi_app.dependency_overrides[sim_api._get_manager] = lambda: mgr
    try:
        _user_a, headers_a = await register_and_login(client, username="sim_user_a")
        _, headers_b = await register_and_login(client, username="sim_user_b")

        create_a = await client.post(
            "/api/v1/simulation/",
            headers=headers_a,
            json={"strategy_id": "simulate/demo_strat"},
        )
        create_b = await client.post(
            "/api/v1/simulation/",
            headers=headers_b,
            json={"strategy_id": "simulate/demo_strat"},
        )
        assert create_a.status_code == 200, create_a.text
        assert create_b.status_code == 200, create_b.text
        id_a = create_a.json()["id"]
        id_b = create_b.json()["id"]

        runtime_a = Path(store[id_a]["runtime_dir"])
        runtime_b = Path(store[id_b]["runtime_dir"])
        assert runtime_a != runtime_b
        assert not runtime_a.is_relative_to(template_root)
        assert (runtime_a / "config.yaml").is_file()

        # Put a log file inside A and B's isolated log directories
        (runtime_a / "logs" / "20261120").mkdir(parents=True, exist_ok=True)
        (runtime_b / "logs" / "20261120").mkdir(parents=True, exist_ok=True)
        (runtime_a / "logs" / "20261120" / "value.log").write_text("log-a\n", encoding="utf-8")
        (runtime_b / "logs" / "20261120" / "value.log").write_text("log-b\n", encoding="utf-8")

        # User A edits config and clears logs -> only affects A's isolated runtime_dir
        upd = await client.put(
            f"/api/v1/simulation/{id_a}/config",
            headers=headers_a,
            json={"raw": "params:\n  shared: false\n"},
        )
        assert upd.status_code == 200, upd.text
        clr = await client.delete(f"/api/v1/simulation/{id_a}/logs", headers=headers_a)
        assert clr.status_code == 200, clr.text

        assert (runtime_a / "logs" / "20261120" / "value.log").read_text(encoding="utf-8") == ""
        assert (runtime_b / "config.yaml").read_text(
            encoding="utf-8"
        ) == "params:\n  shared: true\n"
        assert (runtime_b / "logs" / "20261120" / "value.log").read_text(
            encoding="utf-8"
        ) == "log-b\n"
        assert (tpl_dir / "config.yaml").read_text(encoding="utf-8") == "params:\n  shared: true\n"
        assert (tpl_dir / "logs" / "20261120" / "value.log").read_text(
            encoding="utf-8"
        ) == "shared-log\n"

        # Legacy shared-dir instance without runtime_dir must reject non-admin template mutation
        store["legacy-shared"] = {
            "id": "legacy-shared",
            "strategy_id": "simulate/demo_strat",
            "user_id": store[id_a]["user_id"],
            "status": "stopped",
        }
        forbid_cfg = await client.put(
            "/api/v1/simulation/legacy-shared/config",
            headers=headers_a,
            json={"raw": "params:\n  hacked: true\n"},
        )
        forbid_log = await client.delete(
            "/api/v1/simulation/legacy-shared/logs",
            headers=headers_a,
        )
        assert forbid_cfg.status_code == 403
        assert forbid_log.status_code == 403
    finally:
        fastapi_app.dependency_overrides.pop(sim_api._get_manager, None)


@pytest.mark.asyncio
async def test_internal_endpoints_and_template_config_access_controls(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.strategy import templates as tpl_mod

    _, user_headers = await register_and_login(client, username="ordinary_info_user")
    admin_hdrs = await _admin_headers(client)

    # Metrics and Postman docs require admin privileges
    assert (await client.get("/api/v1/metrics")).status_code == 401
    assert (await client.get("/api/v1/metrics", headers=user_headers)).status_code == 403
    assert (await client.get("/api/v1/metrics/status")).status_code == 401
    assert (await client.get("/api/v1/metrics/status", headers=user_headers)).status_code == 403
    assert (await client.get("/api/v1/docs/postman")).status_code == 401
    assert (await client.get("/api/v1/docs/postman", headers=user_headers)).status_code == 403

    # /ready omits internal AI provider base_url/model details and cache internals
    ready_resp = await client.get("/ready")
    assert ready_resp.status_code == 200
    ready_json = ready_resp.json()
    assert "providers" not in ready_json["ai_providers"]
    assert "base_url" not in ready_resp.text
    assert "details" not in ready_json["cache"]

    # /metrics 500 error output does not expose exception details
    from app.api import metrics as metrics_api

    monkeypatch.setattr(metrics_api, "is_metrics_available", lambda: True)
    monkeypatch.setattr(
        metrics_api,
        "get_metrics_output",
        lambda: (_ for _ in ()).throw(RuntimeError("sensitive-internal-dsn")),
    )
    metrics_err = await client.get("/api/v1/metrics", headers=admin_hdrs)
    assert metrics_err.status_code == 500
    assert "sensitive-internal-dsn" not in metrics_err.text

    # /info requires admin in production mode
    from app import config as config_mod

    prod_settings = config_mod.Settings(
        APP_ENV="production",
        DEBUG=False,
        SECRET_KEY="a" * 32,
        JWT_SECRET_KEY="b" * 32,
        ADMIN_PASSWORD="SecurePass@123!",
        CORS_ORIGINS="https://app.example.test",
        IB_VERIFY_SSL=True,
        IB_WEB_VERIFY_SSL=True,
        IB_PAPER_VERIFY_SSL=True,
        IB_LIVE_VERIFY_SSL=True,
    )
    monkeypatch.setattr(config_mod, "get_settings", lambda: prod_settings)
    assert (await client.get("/info")).status_code == 401
    assert (await client.get("/info", headers=user_headers)).status_code == 403
    assert (await client.get("/info", headers=admin_hdrs)).status_code == 200

    # /strategy/templates/{uuid}/config rejects user strategies outside built-in templates
    fake_user_id = "11111111-2222-3333-4444-555555555555"
    private_dir = tpl_mod.STRATEGIES_DIR / fake_user_id
    private_dir.mkdir(parents=True, exist_ok=True)
    try:
        (private_dir / "config.yaml").write_text("strategy:\n  name: SecretUserStrategy\n")
        cfg_resp = await client.get(f"/api/v1/strategy/templates/{fake_user_id}/config")
        assert cfg_resp.status_code == 404
    finally:
        import shutil

        shutil.rmtree(private_dir, ignore_errors=True)
