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
_UNCERTAIN_STOP_TEST_RESOURCE_SETS: list[dict[str, object]] = []
_UNCERTAIN_STOP_TEST_RESOURCE_LOCK = threading.Lock()


def _load_test_module(module_name: str):
    return importlib.import_module(module_name)


def _start_execution_host(
    host_fixture,
    tmp_path: Path,
    *,
    account_ref: str,
    strategy_ref: str,
    setup_resources: dict[str, object] | None = None,
):
    """Run the accepted R249 Host source in its owner thread with an exact scope."""

    names = ("_ACCOUNT", "_STRATEGY", "_SCOPE")
    previous = {name: getattr(host_fixture, name) for name in names}
    parent_pipe = None
    child_pipe = None
    host_thread = None
    try:
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
        host_thread = threading.Thread(
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
        )
    except BaseException:
        for pipe in (parent_pipe, child_pipe):
            if pipe is not None and not pipe.closed:
                with contextlib.suppress(BaseException):
                    pipe.close()
        for name, value in previous.items():
            setattr(host_fixture, name, value)
        raise
    host = {
        "pipe": parent_pipe,
        "child_pipe": child_pipe,
        "thread": host_thread,
        "module_globals": previous,
        "fixture": host_fixture,
        "ready_received": False,
        "startup_reply": None,
        "thread_started": False,
        "close_command_sent": False,
        "module_globals_restored": False,
        "released": False,
        "custody_root": setup_resources,
    }
    if setup_resources is not None:
        # Publish custody before thread startup/readiness can fail.
        setup_resources["execution"] = host
    try:
        host["thread"].start()
        host["thread_started"] = True
        ready = host_fixture._receive(parent_pipe, timeout=20.0)
    except BaseException as error:
        cleanup = _close_execution_host(host, startup_failure=True)
        raise AssertionError(
            "synthetic strategy ServiceHost readiness wait failed: "
            f"{type(error).__name__}; cleanup={_finite_cleanup_projection(cleanup)!r}"
        ) from error
    host["startup_reply"] = ready
    if not isinstance(ready, tuple) or not ready or ready[0] != "ready":
        cleanup = _close_execution_host(host, startup_failure=True)
        raise AssertionError(
            "synthetic strategy ServiceHost failed to start: "
            f"{_finite_reply_projection(ready)!r}; "
            f"cleanup={_finite_cleanup_projection(cleanup)!r}"
        )
    host["ready_received"] = True
    if ready[1] != endpoint:
        cleanup = _close_execution_host(host)
        raise AssertionError(
            "synthetic strategy ServiceHost endpoint changed; "
            f"cleanup={_finite_cleanup_projection(cleanup)!r}"
        )
    return endpoint, keys, host


def _finite_reply_projection(reply: object) -> object:
    if not isinstance(reply, tuple) or not reply:
        return type(reply).__name__
    label = reply[0]
    if type(label) is str and label in {"ready", "host_error", "closed", "metrics"}:
        return (label,)
    return ("unexpected_reply",)


def _finite_cleanup_projection(result: dict[str, object]) -> dict[str, object]:
    return {
        key: result.get(key)
        for key in (
            "thread_started",
            "thread_alive",
            "thread_exited",
            "normal_close",
            "released",
            "startup_error_reported",
            "close_error",
            "resource_errors",
        )
    }


def _retain_uncertain_setup_resources(setup_resources: dict[str, object]) -> None:
    with _UNCERTAIN_STOP_TEST_RESOURCE_LOCK:
        if not any(item is setup_resources for item in _UNCERTAIN_STOP_TEST_RESOURCE_SETS):
            _UNCERTAIN_STOP_TEST_RESOURCE_SETS.append(setup_resources)


def _release_uncertain_setup_resources(setup_resources: dict[str, object]) -> None:
    with _UNCERTAIN_STOP_TEST_RESOURCE_LOCK:
        _UNCERTAIN_STOP_TEST_RESOURCE_SETS[:] = [
            item for item in _UNCERTAIN_STOP_TEST_RESOURCE_SETS if item is not setup_resources
        ]


def _close_execution_host(host, *, startup_failure: bool = False) -> dict[str, object]:
    prior_result = host.get("close_result")
    if host.get("released") and isinstance(prior_result, dict):
        return prior_result
    pipe = host["pipe"]
    child_pipe = host.get("child_pipe")
    thread = host["thread"]
    reply = None
    close_error = None
    resource_errors: list[str] = []
    thread_started = bool(host.get("thread_started") or thread.ident is not None)
    try:
        startup_reply = host.get("startup_reply")
        reported_startup_error = (
            startup_failure
            and isinstance(startup_reply, tuple)
            and bool(startup_reply)
            and startup_reply[0] == "host_error"
        )
        if thread.is_alive() and not pipe.closed and not reported_startup_error:
            if not host.get("close_command_sent"):
                pipe.send(("close",))
                host["close_command_sent"] = True
            reply = host["fixture"]._receive(pipe, timeout=20.0)
            if (
                not host.get("ready_received")
                and isinstance(reply, tuple)
                and reply
                and reply[0] == "ready"
            ):
                host["ready_received"] = True
                reply = host["fixture"]._receive(pipe, timeout=20.0)
        elif reported_startup_error:
            reply = startup_reply
    except BaseException as error:
        close_error = type(error).__name__
    if thread_started and thread.is_alive():
        try:
            thread.join(20)
        except BaseException as error:
            resource_errors.append(f"join:{type(error).__name__}")
    thread_alive = thread.is_alive()
    thread_exited = not thread_alive
    if thread_alive:
        # The worker may still own either endpoint and the fixture globals. Keep all
        # three under test-owned custody; a timeout is not a close receipt.
        host["released"] = False
        custody_root = host.get("custody_root")
        if not isinstance(custody_root, dict):
            custody_root = {"execution": host}
            host["custody_root"] = custody_root
        custody_root.setdefault("execution", host)
        _retain_uncertain_setup_resources(custody_root)
    else:
        for label, endpoint in (("parent_pipe", pipe), ("child_pipe", child_pipe)):
            if endpoint is None or endpoint.closed:
                continue
            try:
                endpoint.close()
            except BaseException as error:
                resource_errors.append(f"{label}:{type(error).__name__}")
        if not host.get("module_globals_restored"):
            try:
                for name, value in host["module_globals"].items():
                    setattr(host["fixture"], name, value)
                host["module_globals_restored"] = True
            except BaseException as error:
                resource_errors.append(f"module_globals:{type(error).__name__}")
        endpoints_closed = (pipe is None or pipe.closed) and (
            child_pipe is None or child_pipe.closed
        )
        host["released"] = (
            endpoints_closed and bool(host.get("module_globals_restored")) and not resource_errors
        )
        if host["released"]:
            custody_root = host.get("custody_root")
            if isinstance(custody_root, dict):
                _release_uncertain_setup_resources(custody_root)
    result = {
        "reply": reply,
        "close_error": close_error,
        "resource_errors": tuple(resource_errors),
        "thread_started": thread_started,
        "thread_alive": thread_alive,
        "thread_exited": thread_exited,
        "normal_close": not thread_alive and reply == ("closed", "closed") and close_error is None,
        "released": bool(host.get("released")),
        "startup_error_reported": (
            isinstance(reply, tuple) and bool(reply) and reply[0] == "host_error"
        ),
    }
    host["close_result"] = result
    return result


def _owner_startup_failed_before_host_creation(result: object) -> bool:
    return (
        type(result) is tuple
        and len(result) == 3
        and result[0] == "error"
        and type(result[1]) is str
        and result[2] == ("not_created", None)
    )


def _cleanup_setup_resources(setup_resources: dict[str, object]) -> dict[str, object]:
    """Attempt independent fixture cleanup and retain anything with uncertain custody."""

    errors: list[str] = []
    actions: dict[str, str] = {}
    process = setup_resources.get("strategy_process")
    process_lookup = setup_resources.get("strategy_process_lookup")
    process_lookup_failed = False
    if callable(process_lookup):
        try:
            looked_up = process_lookup()
            if looked_up is not None:
                process = looked_up
                setup_resources["strategy_process"] = looked_up
        except BaseException as error:
            errors.append(f"strategy_process_lookup:{type(error).__name__}")
            process_lookup_failed = True
    if process_lookup_failed:
        process_state = "unknown"
    elif process is None:
        process_state = "absent"
    else:
        try:
            process_state = "running" if process.returncode is None else "exited"
        except BaseException as error:
            process_state = "unknown"
            errors.append(f"strategy_process_state:{type(error).__name__}")

    if process_state in {"running", "unknown"}:
        actions["hosts"] = "retained_strategy_process_not_confirmed_exited"
    else:
        execution = setup_resources.get("execution")
        if execution is not None:
            try:
                result = _close_execution_host(execution)
            except BaseException as error:
                result = None
                errors.append(f"execution_host_close:{type(error).__name__}")
            if result is not None and result.get("released"):
                setup_resources["execution"] = None
                actions["execution"] = "released"
                if not result.get("normal_close") and not result.get("startup_error_reported"):
                    errors.append("execution_host_non_normal_exit")
            else:
                actions["execution"] = "retained_uncertain"
                if result is not None:
                    errors.append("execution_host_close_unconfirmed")
        else:
            actions["execution"] = "already_released"

        owner = setup_resources.get("owner")
        if owner is not None:
            selected_owner_test, thread, stopped, refs = owner
            try:
                if getattr(thread, "ident", None) is None:
                    stopped.set()
                    setup_resources["owner"] = None
                    actions["owner"] = "host_thread_never_started"
                elif (
                    not thread.is_alive()
                    and refs.get("host") is None
                    and _owner_startup_failed_before_host_creation(
                        refs.get("_owner_startup_result")
                    )
                ):
                    stopped.set()
                    setup_resources["owner"] = None
                    actions["owner"] = "startup_failed_before_host_creation"
                else:
                    selected_owner_test.close_owner_host_thread(thread, stopped, refs)
            except BaseException as error:
                errors.append(f"owner_host_close:{type(error).__name__}")
            if setup_resources.get("owner") is not None:
                owner_result = refs.get("_owner_close_result")
                try:
                    owner_thread_alive = thread.is_alive()
                except BaseException as error:
                    owner_thread_alive = True
                    errors.append(f"owner_thread_state:{type(error).__name__}")
                if not owner_thread_alive and owner_result == ("closed", "closed"):
                    setup_resources["owner"] = None
                    actions["owner"] = "released"
                else:
                    actions["owner"] = "retained_uncertain"
        else:
            actions["owner"] = "already_released"

        # A living owner thread may still use the registered gateway exclusion and
        # imported modules. Keep both until each Host closure is confirmed.
        hosts_released = (
            setup_resources.get("execution") is None and setup_resources.get("owner") is None
        )
        if setup_resources.get("legacy_registered"):
            if hosts_released:
                try:
                    unregister_legacy_gateway_exclusions(setup_resources.get("legacy_token"))
                    setup_resources["legacy_registered"] = False
                    setup_resources["legacy_token"] = None
                    actions["legacy_registration"] = "released"
                except BaseException as error:
                    errors.append(f"legacy_unregister:{type(error).__name__}")
                    actions["legacy_registration"] = "retained_error"
            else:
                actions["legacy_registration"] = "retained_host_not_closed"

        if hosts_released:
            module_names = setup_resources.get("module_names", [])
            remaining_names = []
            for module_name in module_names:
                try:
                    sys.modules.pop(module_name, None)
                except BaseException as error:
                    remaining_names.append(module_name)
                    errors.append(f"module_remove:{type(error).__name__}")
            setup_resources["module_names"] = remaining_names
            plugin_root = setup_resources.get("plugin_root")
            if plugin_root is not None:
                try:
                    try:
                        sys.path.remove(str(plugin_root))
                    except ValueError:
                        pass
                    setup_resources["plugin_root"] = None
                    actions["plugin_path"] = "released"
                except BaseException as error:
                    errors.append(f"plugin_path_remove:{type(error).__name__}")
                    actions["plugin_path"] = "retained_error"
        else:
            actions["imports"] = "retained_host_not_closed"

    manager = setup_resources.get("manager")
    instance_id = setup_resources.get("instance_id")
    manager_refs_clear = True
    if manager is not None and instance_id is not None:
        try:
            manager_refs_clear = (
                instance_id not in manager._processes and instance_id not in manager._gateways
            )
        except BaseException as error:
            manager_refs_clear = False
            errors.append(f"manager_registry_check:{type(error).__name__}")
    process_safe = process_state in {"absent", "exited"}
    resources_clear = (
        process_safe
        and setup_resources.get("execution") is None
        and setup_resources.get("owner") is None
        and not setup_resources.get("legacy_registered")
        and not setup_resources.get("module_names")
        and setup_resources.get("plugin_root") is None
        and manager_refs_clear
    )
    if resources_clear:
        setup_resources["strategy_process"] = None
        setup_resources["strategy_process_lookup"] = None
        setup_resources["manager"] = None
        setup_resources["instance_id"] = None
        _release_uncertain_setup_resources(setup_resources)
    else:
        _retain_uncertain_setup_resources(setup_resources)
    return {
        "released": resources_clear,
        "process_state": process_state,
        "manager_refs_clear": manager_refs_clear,
        "actions": actions,
        "errors": tuple(errors),
    }


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
    request,
) -> None:
    live_test = _load_test_module(
        "tests.integration.test_service_strategy_execution_host_integration"
    )
    owner_test = _load_test_module("tests.test_afi08_owner_freeze_control_http")
    purelib, _ = live_test._assert_installed_package_origins()
    monkeypatch.setenv("AFI_TEST_BACKTRADER_SITE_ROOT", str(purelib))
    host_fixture, helper_root = live_test._load_r249_host_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(manager_module, "_BACKTRADER_DIR", helper_root)
    user_data, owner_headers = auth_user
    async with async_session_maker() as session:
        user = await session.scalar(select(User).where(User.username == user_data["username"]))
        assert user is not None
        subject = str(user.id)

    account_ref = live_test._ACCOUNT_REF
    setup_resources: dict[str, object] = {
        "owner": None,
        "execution": None,
        "legacy_token": None,
        "legacy_registered": False,
        "plugin_root": None,
        "module_names": [],
        "strategy_process": None,
        "strategy_process_lookup": None,
        "manager": None,
        "instance_id": None,
    }

    def cleanup_finalizer() -> None:
        result = _cleanup_setup_resources(setup_resources)
        if not result["released"] or result["errors"]:
            raise AssertionError(f"synthetic STOP fixture cleanup remains uncertain: {result!r}")

    # Install the finalizer before either owner Host or execution thread can start.
    request.addfinalizer(cleanup_finalizer)
    owner_deployment, _owner_thread, _owner_stopped, owner_refs = owner_test._start_owner_host(
        tmp_path,
        subject=subject,
        afi_account_id=f"afi08-account-{uuid.uuid4().hex}",
        risk_account_id=account_ref,
        owner_action=owner_test.ControlAction.STOP_NEW,
        setup_resources=setup_resources,
    )
    owner_scope = owner_refs["wire_scope"]
    endpoint, keys, execution_host = _start_execution_host(
        host_fixture,
        tmp_path,
        account_ref=account_ref,
        strategy_ref=owner_scope.strategy_ref,
        setup_resources=setup_resources,
    )

    profile_module_name = f"afi_service_strategy_http_{uuid.uuid4().hex}"
    owner_module_name = f"afi_service_owner_http_{uuid.uuid4().hex}"
    setup_resources["module_names"].extend((profile_module_name, owner_module_name))
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
    profile_source = (
        profile_source.replace(
            f'_STRATEGY_REF = "{live_test._STRATEGY_REF}"',
            f"_STRATEGY_REF = {owner_scope.strategy_ref!r}",
        )
        .replace(
            f'_ACCOUNT_REF = "{live_test._ACCOUNT_REF}"',
            f"_ACCOUNT_REF = {account_ref!r}",
        )
        .replace(
            "subject.synthetic.afi-service",
            subject,
        )
    )
    profile_path.write_text(profile_source, encoding="utf-8")
    importlib.invalidate_caches()
    sys.path.insert(0, str(plugin_root))
    setup_resources["plugin_root"] = plugin_root

    legacy_key = f"manual:OKX:{account_ref}"
    owner_token = object()
    setup_resources["legacy_token"] = owner_token
    register_legacy_gateway_exclusions(owner_token, (legacy_key,))
    setup_resources["legacy_registered"] = True
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
    setup_resources["manager"] = manager
    setup_resources["instance_id"] = live_test._INSTANCE_ID
    setup_resources["strategy_process_lookup"] = lambda: manager._processes.get(
        live_test._INSTANCE_ID
    )
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
        json.dumps({live_test._STRATEGY_ID: live_test._PROFILE_REF}, separators=(",", ":")),
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
        assert instances[live_test._INSTANCE_ID].get("_server_service_execution_managed") is None
        assert manager._gateways == {}
        assert released_legacy == []
        assert owner_refs["registry"]._strategy_write_is_stopped(owner_scope) is True

        metrics = host_fixture._host_metrics(execution_host)
        assert metrics[0] == "metrics"
        assert metrics[1] == ("bt-cerebro-fill-intent-r1",)
        assert metrics[2] == ()
        assert metrics[6:8] == ("FILLED", 1)
    finally:
        if process is None:
            process = manager._processes.get(live_test._INSTANCE_ID)
        setup_resources["strategy_process"] = process
        stop_error = None
        if process is not None and process.returncode is None:
            try:
                await manager.stop_instance(live_test._INSTANCE_ID)
            except BaseException as error:
                stop_error = type(error).__name__
        cleanup = _cleanup_setup_resources(setup_resources)
        if stop_error is not None or not cleanup["released"] or cleanup["errors"]:
            raise AssertionError(
                "synthetic strategy STOP fixture cleanup is not fully confirmed: "
                f"stop_error={stop_error!r}; cleanup={cleanup!r}"
            )
