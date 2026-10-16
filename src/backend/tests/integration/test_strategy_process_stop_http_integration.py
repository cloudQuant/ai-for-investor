"""HTTP STOP_PROCESS over a real local owner Host and strategy subprocess."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import importlib
import json
import multiprocessing
import sys
import threading
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytest.importorskip("bt_api_py")
pytest.importorskip("bt_api_execution")
pytest.importorskip("bt_api_monitor")
pytest.importorskip("bt_api_risk")
pytest.importorskip("zmq")
pytest.importorskip("pandas")

from app.api import strategy_process_stop as stop_api  # noqa: E402
from app.db.database import async_session_maker  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.live_trading import manager as manager_module  # noqa: E402
from app.services.live_trading.manager import LiveTradingManager  # noqa: E402
from app.services.live_trading.service_execution_launch import (  # noqa: E402
    SERVICE_EXECUTION_PROFILE_MAP_ENV,
)
from app.services.live_trading.service_gateway_operator_guard import (  # noqa: E402
    register_legacy_gateway_exclusions,
    unregister_legacy_gateway_exclusions,
)
from app.services.workspace import units as workspace_units  # noqa: E402

_ROUTE = "/api/v1/service-strategy-processes/{instance_id}/stop"
_INSTANCE_ID = "afi08-http-stop-instance"


def _load_test_module(module_name: str):
    return importlib.import_module(module_name)


def _start_execution_host(host_fixture, tmp_path: Path, *, account_ref: str, strategy_ref: str):
    """Run the accepted R249 Host source in its owner thread with an exact scope."""

    names = ("_ACCOUNT", "_STRATEGY", "_SCOPE")
    previous = {name: getattr(host_fixture, name) for name in names}
    host_fixture._ACCOUNT = account_ref
    host_fixture._STRATEGY = strategy_ref
    host_fixture._SCOPE = type(previous["_SCOPE"])(
        host_fixture._DOMAIN,
        account_ref=account_ref,
        strategy_ref=strategy_ref,
    )

    endpoint = host_fixture._endpoint()
    server_public, server_secret = host_fixture.zmq.curve_keypair()
    client_public, client_secret = host_fixture.zmq.curve_keypair()
    keys = {
        "server_public": server_public,
        "server_secret": server_secret,
        "client_public": client_public,
        "client_secret": client_secret,
    }
    parent_pipe, child_pipe = multiprocessing.get_context("spawn").Pipe(duplex=True)
    host = {
        "pipe": parent_pipe,
        "thread": threading.Thread(
            target=host_fixture._host_process,
            args=(
                child_pipe,
                host_fixture._service_config(endpoint),
                str(tmp_path / "strategy-stop-registry.sqlite3"),
                str(tmp_path / "strategy-stop-execution.sqlite3"),
                keys,
            ),
            name="afi08-strategy-stop-execution-host",
            daemon=True,
        ),
        "module_globals": previous,
        "fixture": host_fixture,
    }
    host["thread"].start()
    ready = host_fixture._receive(parent_pipe, timeout=20.0)
    if not isinstance(ready, tuple) or not ready or ready[0] != "ready":
        _close_execution_host(host)
        raise AssertionError(f"synthetic strategy ServiceHost failed to start: {ready!r}")
    assert ready[1] == endpoint
    return endpoint, keys, host


def _close_execution_host(host) -> None:
    pipe = host["pipe"]
    thread = host["thread"]
    try:
        if thread.is_alive() and not pipe.closed:
            pipe.send(("close",))
            reply = host["fixture"]._receive(pipe, timeout=20.0)
            assert reply == ("closed", "closed"), reply
        thread.join(20)
        assert not thread.is_alive(), "synthetic strategy ServiceHost did not close"
    finally:
        if not pipe.closed:
            pipe.close()
        for name, value in host["module_globals"].items():
            setattr(host["fixture"], name, value)


def _operator_setting(owner_profile_ref: str, account_ref: str, subject: str, legacy_key: str):
    return {
        "schema_version": 1,
        "operators": [
            {
                "profile_ref": owner_profile_ref,
                "account_ref": account_ref,
                "authorized_subjects": [subject],
                "operations": ["status", "start", "stop"],
                "auto_start": False,
                "legacy_gateway_keys": [legacy_key],
            }
        ],
    }


async def _register_foreign_user(client: AsyncClient) -> dict[str, str]:
    username = f"afi08_foreign_{uuid.uuid4().hex[:12]}"
    registered = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": f"{username}@test.com",
            "password": "Test12345678",
        },
    )
    assert registered.status_code == 200, registered.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "Test12345678"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.asyncio
async def test_http_stop_new_fences_exact_strategy_then_releases_runtime(
    client: AsyncClient,
    auth_user,
    tmp_path: Path,
    monkeypatch,
) -> None:
    live_test = _load_test_module(
        "tests.integration.test_service_strategy_execution_host_integration"
    )
    owner_test = _load_test_module("tests.test_afi08_owner_freeze_control_http")
    host_fixture = live_test._load_r249_host_fixture()
    user_data, owner_headers = auth_user
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.username == user_data["username"]))
        assert user is not None
        subject = str(user.id)

    account_ref = live_test._ACCOUNT_REF
    owner_deployment, owner_thread, owner_stopped, owner_refs = owner_test._start_owner_host(
        tmp_path,
        subject=subject,
        afi_account_id=f"afi08-account-{uuid.uuid4().hex}",
        risk_account_id=account_ref,
        owner_action=owner_test.ControlAction.STOP_NEW,
    )
    owner_scope = owner_refs["wire_scope"]
    endpoint, keys, execution_host = _start_execution_host(
        host_fixture,
        tmp_path,
        account_ref=account_ref,
        strategy_ref=owner_scope.strategy_ref,
    )

    profile_module_name = f"afi_service_strategy_http_{uuid.uuid4().hex}"
    owner_module_name = f"afi_service_owner_http_{uuid.uuid4().hex}"
    plugin_root = tmp_path / "trusted-stop-profiles"
    script_path = tmp_path / "strategy" / "run.py"
    script_path.parent.mkdir()
    script_bytes = live_test._strategy_source().lstrip().encode("utf-8")
    script_path.write_bytes(script_bytes)
    live_test._write_test_profile(
        plugin_root,
        script_sha256=hashlib.sha256(script_bytes).hexdigest(),
        endpoint=endpoint,
        keys=keys,
        profile_module_name=profile_module_name,
        owner_module_name=owner_module_name,
    )
    profile_path = plugin_root / f"{profile_module_name}.py"
    profile_source = profile_path.read_text(encoding="utf-8")
    profile_source = profile_source.replace(
        f'_STRATEGY_REF = "{live_test._STRATEGY_REF}"',
        f"_STRATEGY_REF = {owner_scope.strategy_ref!r}",
    ).replace(
        f'_ACCOUNT_REF = "{live_test._ACCOUNT_REF}"',
        f"_ACCOUNT_REF = {account_ref!r}",
    ).replace(
        "subject.synthetic.afi-service",
        subject,
    )
    profile_path.write_text(profile_source, encoding="utf-8")
    importlib.invalidate_caches()
    sys.path.insert(0, str(plugin_root))

    legacy_key = f"manual:OKX:{account_ref}"
    owner_token = object()
    register_legacy_gateway_exclusions(owner_token, (legacy_key,))
    instance = {
        "strategy_id": live_test._STRATEGY_ID,
        "user_id": subject,
        "runtime_dir": str(script_path.parent),
        "params": {},
        "status": "stopped",
        "pid": None,
    }
    instances = {live_test._INSTANCE_ID: copy.deepcopy(instance)}

    def load_instances():
        return copy.deepcopy(instances)

    def save_instances(updated):
        instances.clear()
        instances.update(copy.deepcopy(updated))

    monkeypatch.setattr(manager_module, "_load_instances", load_instances)
    monkeypatch.setattr(manager_module, "_save_instances", save_instances)
    monkeypatch.setattr(manager_module, "_instance_store_lock", contextlib.nullcontext)

    async def _no_live_handoff(*_args, **_kwargs):
        return None

    async def _no_managed_unit_start(*_args, **_kwargs):
        return None

    async def _no_managed_unit_stop(*_args, **_kwargs):
        return False

    monkeypatch.setattr(
        workspace_units, "get_ai_research_live_handoff_unit_for_instance", _no_live_handoff
    )
    monkeypatch.setattr(
        workspace_units,
        "assert_ai_research_paper_runtime_start_allowed",
        _no_managed_unit_start,
    )
    monkeypatch.setattr(
        workspace_units,
        "assert_ai_research_paper_runtime_stop_allowed",
        _no_managed_unit_stop,
    )

    manager = object.__new__(LiveTradingManager)
    manager._instance_op_lock = asyncio.Lock()
    manager._paper_runtime_capability_lock = threading.RLock()
    manager._pending_attested_paper_instances = {}
    manager._pending_attested_live_handoff_instances = {}
    manager._pending_managed_workspace_instances = set()
    manager._gateway_lock = threading.RLock()
    manager._gateways = {}
    manager._processes = {}
    manager._stopping_instances = set()
    released_legacy = []
    manager._release_gateway_for_instance = released_legacy.append
    original_strategy_launch = manager._service_strategy_launch

    def _bind_to_owner_run(instance_value, strategy_dir):
        launch = original_strategy_launch(instance_value, strategy_dir)
        if launch is None:
            return None
        profile, context, import_roots = launch
        return profile, replace(context, run_id=owner_scope.run_id), import_roots

    manager._service_strategy_launch = _bind_to_owner_run

    operator_raw = json.dumps(
        _operator_setting(
            live_test._OWNER_PROFILE_REF,
            account_ref,
            subject,
            legacy_key,
        ),
        separators=(",", ":"),
    )
    monkeypatch.setenv(
        SERVICE_EXECUTION_PROFILE_MAP_ENV,
        json.dumps(
            {live_test._STRATEGY_ID: live_test._PROFILE_REF}, separators=(",", ":")
        ),
    )
    monkeypatch.setenv("SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON", operator_raw)
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(
            SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON=SimpleNamespace(
                get_secret_value=lambda: operator_raw
            )
        ),
    )
    application = importlib.import_module("app.main").app
    monkeypatch.setitem(
        application.dependency_overrides,
        stop_api.get_service_strategy_manager,
        lambda: manager,
    )
    monkeypatch.setitem(
        application.dependency_overrides,
        stop_api.get_owner_control_deployment,
        lambda: owner_deployment,
    )

    foreign_headers = await _register_foreign_user(client)
    process = None
    try:
        started = await manager.start_instance(
            live_test._INSTANCE_ID,
            user_id=subject,
            execution_mode="live",
        )
        assert started["status"] == "running"
        assert started["_server_service_execution_managed"] is True
        process = manager._processes[live_test._INSTANCE_ID]
        assert getattr(process, "_bt_service_execution", False) is True
        log = live_test._wait_for_log_marker(
            script_path.parent / "logs" / "subprocess.stdout.log",
            live_test._ORDER_QUERY_MARKER,
        )
        assert live_test._ORDER_QUERY_MARKER in log
        assert instances[live_test._INSTANCE_ID]["_server_service_execution_run_id"] == (
            owner_scope.run_id
        )
        assert owner_refs["registry"]._strategy_write_is_stopped(owner_scope) is False

        url = _ROUTE.format(instance_id=live_test._INSTANCE_ID)
        denied = await client.post(
            url,
            headers={**foreign_headers, "Idempotency-Key": "foreign-stop-process-r1"},
        )
        assert denied.status_code == 404
        assert owner_refs["registry"]._strategy_write_is_stopped(owner_scope) is False
        assert process.returncode is None

        response = await client.post(
            url,
            headers={**owner_headers, "Idempotency-Key": "owner-stop-process-r1"},
        )
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt["status"] == "stopped"
        assert receipt["instance_id"] == live_test._INSTANCE_ID
        assert receipt["strategy_ref"] == owner_scope.strategy_ref
        assert receipt["run_id"] == owner_scope.run_id
        assert receipt["stop_new_status"] == "acknowledged"
        assert receipt["stop_new_owner_final"] is True
        assert receipt["stop_new_reconciliation_required"] is False
        assert receipt["stop_new_effect"] == "fenced"
        assert receipt["process_status"] == "stopped"
        assert receipt["process_exit_code"] == 0
        assert receipt["subscription_status"] == "released"
        assert receipt["open_order_policy"] == "leave_open_and_report"
        assert receipt["open_orders_status"] == "left_open_unverified"
        assert receipt["positions_status"] == "unobserved"
        assert process.returncode == 0
        assert live_test._INSTANCE_ID not in manager._processes
        assert instances[live_test._INSTANCE_ID].get(
            "_server_service_execution_managed"
        ) is None
        assert manager._gateways == {}
        assert released_legacy == []
        assert owner_refs["registry"]._strategy_write_is_stopped(owner_scope) is True

        metrics = host_fixture._host_metrics(execution_host)
        assert metrics[0] == "metrics"
        assert metrics[1] == ("bt-cerebro-fill-intent-r1",)
        assert metrics[2] == ()
        assert metrics[6:8] == ("FILLED", 1)
    finally:
        if process is not None and process.returncode is None:
            with contextlib.suppress(Exception):
                await manager.stop_instance(live_test._INSTANCE_ID)
        _close_execution_host(execution_host)
        await owner_test._stop_host(owner_thread, owner_stopped, owner_refs)
        unregister_legacy_gateway_exclusions(owner_token)
        for module_name in (profile_module_name, owner_module_name):
            sys.modules.pop(module_name, None)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(plugin_root))
