"""AFI live-strategy client lifecycle against the accepted local ServiceHost.

The ServiceHost, CURVE transport, execution journal, and strategy client are
real local components. Only the provider observation and profile credentials
are synthetic. This does not establish venue, account, or formal acceptance.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import importlib
import json
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("zmq")
pytest.importorskip("pandas")

from app.services.live_trading import manager as manager_module  # noqa: E402
from app.services.live_trading.manager import LiveTradingManager  # noqa: E402
from app.services.live_trading.service_execution_launch import (  # noqa: E402
    SERVICE_EXECUTION_PROFILE_MAP_ENV,
)
from app.services.live_trading.service_gateway_operator_guard import (  # noqa: E402
    register_legacy_gateway_exclusions,
    unregister_legacy_gateway_exclusions,
)
from app.services.live_trading.strategy_process_stop import (  # noqa: E402
    stop_service_strategy_process,
)
from app.services.workspace import units as workspace_units  # noqa: E402

_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
_BACKTRADER_ROOT = _REPOSITORY_ROOT.parent / "backtrader"
_BT_FIXTURE_MODULE = "test_btapi_strategy_execution_callbacks_local_process"
_PROFILE_REF = "afi-test-profile"
_OWNER_PROFILE_REF = "afi-test-owner"
_STRATEGY_ID = "strategy.synthetic.afi-service"
_SUBJECT_REF = "subject.synthetic.afi-service"
_INSTANCE_ID = "afi-service-strategy-instance"
_ACCOUNT_REF = "account.synthetic.callbacks"
_SERVICE_ID = "bt-callback-service"
_SERVICE_INSTANCE_ID = "bt-callback-execution-owner"
_STRATEGY_REF = "strategy.synthetic.callbacks"
_PRINCIPAL_REF = "bt-callback-strategy-principal"
_DOMAIN = "paper:bt-cerebro-execution-callbacks"
_SERVICE_PRINCIPAL = "bt-callback-service-principal"
_TRANSPORT_REF = "bt-callback-connect-v1"
_ORDER_SCOPE_REF = "bt-callback-orders-v1"
_QUERY_SCOPE_REF = "bt-callback-query-v1"
_SERVICE_SCOPE_REF = "bt-callback-root-v1"
_SERVER_SECURITY_REF = "bt-callback-server-curve-v1"
_CLIENT_SECURITY_REF = "bt-callback-client-curve-v1"
_LISTENER_REF = "bt-callback-listener-v1"
_LEGACY_KEY = "manual:OKX:account.synthetic.callbacks"
_INTENT_CONTRACT_REF = "bt-cerebro-fill-metadata-r1"
_ORDER_QUERY_MARKER = "AFI_SERVICE_ORDER_QUERY_OK:FILLED"


def _load_r249_host_fixture():
    if not (_BACKTRADER_ROOT / "tests" / "integration" / f"{_BT_FIXTURE_MODULE}.py").is_file():
        pytest.skip("the accepted Backtrader local ServiceHost fixture is unavailable")

    for candidate in reversed(
        (
            _BACKTRADER_ROOT,
            _BACKTRADER_ROOT / "tests" / "integration",
        )
    ):
        text = str(candidate)
        with contextlib.suppress(ValueError):
            sys.path.remove(text)
        sys.path.insert(0, text)

    saved_test_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "tests" or name.startswith("tests.")
    }
    for name in saved_test_modules:
        sys.modules.pop(name, None)
    try:
        return importlib.import_module(_BT_FIXTURE_MODULE)
    finally:
        for name in tuple(sys.modules):
            if name == "tests" or name.startswith("tests."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_test_modules)


def _strategy_source() -> str:
    return '''
import datetime as dt
import time

import backtrader as bt
import pandas as pd
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store

AFI_SERVICE_INTENT_CONTRACT_REF = "bt-cerebro-fill-metadata-r1"
_SYMBOL = "PAPER:SIM:BTC-USDT"
_INTENT_ID = "bt-cerebro-fill-intent-r1"


class _AfiServiceStrategy(bt.Strategy):
    def start(self):
        self._order = None

    def next(self):
        if self._order is None:
            self._order = self.buy(
                data=self.data,
                size=1.0,
                price=100.25,
                exectype=bt.Order.Limit,
                managed_order_type="LIMIT",
                managed_intent_id=_INTENT_ID,
                managed_signal_id="bt-cerebro-fill-signal-r1",
                managed_instrument=_SYMBOL,
                managed_position_effect="OPEN",
                managed_metadata_version="bt-cerebro-fill-metadata-r1",
                managed_instrument_metadata_digest="a" * 64,
                offset="open",
                reduce_only=False,
            )
        time.sleep(0.02)

    def notify_order(self, order):
        if order.status != order.Completed:
            return
        live_order = self.broker.orders[order.ref]
        projection = self.broker.store.refresh_managed_order_projection(live_order)
        print(
            "AFI_SERVICE_ORDER_QUERY_OK:{}".format(
                projection.get("service_execution_state")
            ),
            flush=True,
        )


_dates = [dt.datetime(2026, 10, 16) + dt.timedelta(days=index) for index in range(10000)]
_closes = [100.5 + index / 1000 for index in range(len(_dates))]
_frame = pd.DataFrame(
    {
        "open": _closes,
        "high": [price + 0.5 for price in _closes],
        "low": [price - 0.5 for price in _closes],
        "close": _closes,
        "volume": [10.0] * len(_closes),
        "openinterest": [0.0] * len(_closes),
    },
    index=_dates,
)
_store = make_store(
    api=FakeBtApiClient(balance={"cash": 1000.0}, positions=[], open_orders=[]),
    provider="btapi",
)
_broker = _store.getbroker(
    validation_enabled=False,
    cash_check_enabled=False,
    account_refresh_interval=3600.0,
    positions_refresh_interval=3600.0,
    open_orders_refresh_interval=3600.0,
)
_cerebro = bt.Cerebro(stdstats=False, runonce=False, preload=False)
_cerebro.setbroker(_broker)
_cerebro.adddata(bt.feeds.PandasData(dataname=_frame), name=_SYMBOL)
_cerebro.addstrategy(_AfiServiceStrategy)
_cerebro.run()
'''


def _write_test_profile(
    plugin_root: Path,
    *,
    script_sha256: str,
    endpoint: str,
    keys,
    profile_module_name: str,
    owner_module_name: str,
) -> None:
    plugin_root.mkdir(parents=True, exist_ok=True)
    distribution = plugin_root / "afi_service_strategy_test-1.0.dist-info"
    distribution.mkdir()
    (distribution / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: afi-service-strategy-test\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (distribution / "entry_points.txt").write_text(
        "[ai_for_investor.service_strategy_profiles]\n"
        f"{_PROFILE_REF} = {profile_module_name}:make_profile\n\n"
        "[bt_api_py.gateway_operator_profiles]\n"
        f"{_OWNER_PROFILE_REF} = {owner_module_name}:profile\n",
        encoding="utf-8",
    )
    fixture = {
        "endpoint": endpoint,
        "keys": {
            name: value.decode("ascii") if isinstance(value, bytes) else value
            for name, value in keys.items()
        },
    }
    (plugin_root / "fixture.json").write_text(
        json.dumps(fixture, sort_keys=True), encoding="utf-8"
    )
    profile_source = '''
import json
from pathlib import Path

from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_py.gateway_operator_application import GatewayOperatorProfile
from bt_api_py.service_config import parse_client_config
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory

from app.services.live_trading.service_execution_launch import TrustedServiceStrategyProfile

_FIXTURE = json.loads(Path(__file__).with_name("fixture.json").read_text(encoding="utf-8"))
_DOMAIN = "paper:bt-cerebro-execution-callbacks"
_SERVICE_ID = "bt-callback-service"
_SERVICE_PRINCIPAL = "bt-callback-service-principal"
_STRATEGY_REF = "strategy.synthetic.callbacks"
_PRINCIPAL_REF = "bt-callback-strategy-principal"
_ACCOUNT_REF = "account.synthetic.callbacks"
_SERVICE_INSTANCE_ID = "bt-callback-execution-owner"
_ORDER_SCOPE_REF = "bt-callback-orders-v1"
_QUERY_SCOPE_REF = "bt-callback-query-v1"
_SERVER_SECURITY_REF = "bt-callback-server-curve-v1"
_CLIENT_SECURITY_REF = "bt-callback-client-curve-v1"
_TRANSPORT_REF = "bt-callback-connect-v1"


def _client_config(_context):
    return {
        "client_config_schema_version": 1,
        "process_role": "strategy_client",
        "registration": {"strategy_ref": _STRATEGY_REF},
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "broker.orders",
                            "service_id": _SERVICE_ID,
                            "instance_id": _SERVICE_INSTANCE_ID,
                            "scope_ref": _ORDER_SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "account_ref": _ACCOUNT_REF,
                        },
                        {
                            "mount": "broker.order_query",
                            "service_id": _SERVICE_ID,
                            "instance_id": _SERVICE_INSTANCE_ID,
                            "scope_ref": _QUERY_SCOPE_REF,
                            "transport_ref": _TRANSPORT_REF,
                            "account_ref": _ACCOUNT_REF,
                        },
                    ],
                    "options": {"request_timeout_ms": 2000},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                _TRANSPORT_REF: {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": _FIXTURE["endpoint"]},
                    "security_profile_ref": _CLIENT_SECURITY_REF,
                    "options": {
                        "request_timeout_ms": 2000,
                        "high_water_mark": 32,
                        "max_message_bytes": 65536,
                    },
                }
            },
        },
    }


def _runtime(config, context):
    keys = {
        name: value.encode("ascii")
        for name, value in _FIXTURE["keys"].items()
    }
    return ServiceClientRuntime(
        config,
        identity=WireIdentity(WireRole.STRATEGY_CLIENT, _PRINCIPAL_REF, _STRATEGY_REF),
        run_id=context.run_id,
        scope_resolver=lambda _scope_ref: WireScope(
            _DOMAIN, account_ref=_ACCOUNT_REF, strategy_ref=_STRATEGY_REF
        ),
        peer_resolver=lambda _service_id: WireIdentity(
            WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID
        ),
        transport_factory=ZmqTransportFactory(
            {
                _CLIENT_SECURITY_REF: ClientCurveKeys(
                    keys["server_public"], keys["client_public"], keys["client_secret"]
                )
            }
        ),
        requested_operations={
            "broker.orders": frozenset({"orders.submit", "orders.cancel"}),
            "broker.order_query": frozenset({"orders.query"}),
        },
    )


def make_profile():
    return TrustedServiceStrategyProfile(
        profile_ref="afi-test-profile",
        strategy_id="strategy.synthetic.afi-service",
        script_sha256="@@SCRIPT_SHA256@@",
        strategy_ref=_STRATEGY_REF,
        account_ref=_ACCOUNT_REF,
        principal_ref=_PRINCIPAL_REF,
        owner_profile_ref="afi-test-owner",
        intent_contract_ref="@@INTENT_CONTRACT_REF@@",
        service_id=_SERVICE_ID,
        service_instance_id=_SERVICE_INSTANCE_ID,
        transport_ref=_TRANSPORT_REF,
        orders_scope_ref=_ORDER_SCOPE_REF,
        order_query_scope_ref=_QUERY_SCOPE_REF,
        authorized_subjects=frozenset({"subject.synthetic.afi-service"}),
        legacy_gateway_keys=("manual:OKX:account.synthetic.callbacks",),
        orders_operations=frozenset({"orders.submit", "orders.cancel"}),
        order_query_operations=frozenset({"orders.query"}),
        client_config_factory=_client_config,
        runtime_factory=_runtime,
    )
'''.replace("@@SCRIPT_SHA256@@", script_sha256).replace(
        "@@INTENT_CONTRACT_REF@@", _INTENT_CONTRACT_REF
    )
    (plugin_root / f"{profile_module_name}.py").write_text(profile_source, encoding="utf-8")
    (plugin_root / f"{owner_module_name}.py").write_text(
        "from bt_api_py.gateway_operator_application import GatewayOperatorProfile\n"
        f"profile = GatewayOperatorProfile({_OWNER_PROFILE_REF!r}, "
        "'account_session_worker', lambda: None)\n",
        encoding="utf-8",
    )


def _wait_for_log_marker(path: Path, marker: str, timeout_seconds: float = 20.0) -> str:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if marker in text:
            return text
        if "AFI_SERVICE_EXECUTION_ERROR:" in text:
            raise AssertionError(text[-2000:])
        time.sleep(0.05)
    raise TimeoutError(f"strategy child missed expected service query marker: {marker}")


def test_live_manager_runs_service_strategy_order_query_and_graceful_stop(
    tmp_path, monkeypatch, request
):
    host_fixture = _load_r249_host_fixture()
    endpoint, keys, host = host_fixture._start_host(tmp_path)
    owner_token = object()
    owner_registered = False
    host_cleanup = None
    plugin_root = tmp_path / "trusted-profiles"
    profile_module_name = f"afi_service_strategy_{uuid.uuid4().hex}"
    owner_module_name = f"afi_service_owner_{uuid.uuid4().hex}"

    def cleanup_host_and_owner():
        nonlocal host_cleanup, owner_registered
        if owner_registered:
            unregister_legacy_gateway_exclusions(owner_token)
            owner_registered = False
        if host_cleanup is None:
            host_cleanup = host_fixture._close_host(host)
        for module_name in (profile_module_name, owner_module_name):
            sys.modules.pop(module_name, None)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(plugin_root))
        return host_cleanup

    request.addfinalizer(cleanup_host_and_owner)
    script_path = tmp_path / "strategy" / "run.py"
    script_path.parent.mkdir()
    script_source = _strategy_source().lstrip()
    script_bytes = script_source.encode("utf-8")
    script_path.write_bytes(script_bytes)
    plugin_root = tmp_path / "trusted-profiles"
    _write_test_profile(
        plugin_root,
        script_sha256=hashlib.sha256(script_bytes).hexdigest(),
        endpoint=endpoint,
        keys=keys,
        profile_module_name=profile_module_name,
        owner_module_name=owner_module_name,
    )
    importlib.invalidate_caches()
    sys.path.insert(0, str(plugin_root))
    monkeypatch.setenv(
        SERVICE_EXECUTION_PROFILE_MAP_ENV,
        json.dumps({_STRATEGY_ID: _PROFILE_REF}, separators=(",", ":")),
    )
    monkeypatch.setenv(
        "SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON",
        json.dumps(
            {
                "schema_version": 1,
                "operators": [
                    {
                        "profile_ref": _OWNER_PROFILE_REF,
                        "account_ref": _ACCOUNT_REF,
                        "authorized_subjects": [_SUBJECT_REF],
                        "operations": ["status", "start", "stop"],
                        "auto_start": False,
                        "legacy_gateway_keys": [_LEGACY_KEY],
                    }
                ],
            },
            separators=(",", ":"),
        ),
    )
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(
            SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON=SimpleNamespace(
                get_secret_value=lambda: json.dumps(
                    {
                        "schema_version": 1,
                        "operators": [
                            {
                                "profile_ref": _OWNER_PROFILE_REF,
                                "account_ref": _ACCOUNT_REF,
                                "authorized_subjects": [_SUBJECT_REF],
                                "operations": ["status", "start", "stop"],
                                "auto_start": False,
                                "legacy_gateway_keys": [_LEGACY_KEY],
                            }
                        ],
                    },
                    separators=(",", ":"),
                )
            )
        ),
    )

    register_legacy_gateway_exclusions(owner_token, (_LEGACY_KEY,))
    owner_registered = True
    instance = {
        "strategy_id": _STRATEGY_ID,
        "user_id": _SUBJECT_REF,
        "runtime_dir": str(script_path.parent),
        "params": {},
        "status": "stopped",
        "pid": None,
    }
    instances = {_INSTANCE_ID: copy.deepcopy(instance)}

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

    process = None
    try:
        async def exercise_manager_lifecycle():
            nonlocal process
            started = await manager.start_instance(_INSTANCE_ID, user_id=_SUBJECT_REF)
            assert started["status"] == "running"
            assert started["_server_service_execution_managed"] is True
            assert started["_server_service_execution_profile_ref"] == _PROFILE_REF
            process = manager._processes[_INSTANCE_ID]
            assert getattr(process, "_bt_service_execution", False) is True
            text = _wait_for_log_marker(
                script_path.parent / "logs" / "subprocess.stdout.log", _ORDER_QUERY_MARKER
            )
            assert _ORDER_QUERY_MARKER in text
            run_id = instances[_INSTANCE_ID]["_server_service_execution_run_id"]
            stop_calls = []
            binding = SimpleNamespace(
                config=SimpleNamespace(
                    subject=_SUBJECT_REF,
                    allowed_actions=["STOP_NEW"],
                    wire_account_ref=_ACCOUNT_REF,
                ),
                wire_scope=SimpleNamespace(
                    account_ref=_ACCOUNT_REF,
                    strategy_ref=_STRATEGY_REF,
                    run_id=run_id,
                ),
            )

            class _OwnerControlDeployment:
                def submit_control(self, selected_binding, **kwargs):
                    assert selected_binding is binding
                    assert kwargs["action"] == "STOP_NEW"
                    assert kwargs["subject"] == _SUBJECT_REF
                    assert process.returncode is None
                    stop_calls.append("stop_new")
                    return {
                        "action": "stop_new",
                        "deployment_version": "owner-profile-test-v1",
                        "command_id": "afi-monitor-stop-new-v1-" + "a" * 32,
                        "status": "acknowledged",
                        "outcome": "applied",
                        "effect_ref": "strategy-stop-new-v1:" + "b" * 64,
                        "effect_result": {"action": "stop_new", "result": "fenced"},
                        "request_recorded": True,
                        "owner_final": True,
                        "reconciliation_required": False,
                    }

            owner_control = _OwnerControlDeployment()
            owner_control.bindings = (binding,)

            graceful_stop = manager._gracefully_stop_service_execution

            async def observe_process_stop(instance_id, stopped_process):
                stop_calls.append("process_stop")
                await graceful_stop(instance_id, stopped_process)

            manager._gracefully_stop_service_execution = observe_process_stop
            receipt = await stop_service_strategy_process(
                manager,
                owner_control,
                subject=_SUBJECT_REF,
                instance_id=_INSTANCE_ID,
                binding=binding,
                idempotency_key="afi08-stop-r1-test-key",
                open_order_policy="leave_open_and_report",
            )
            assert receipt.status == "stopped"
            assert receipt.stop_new_effect == "fenced"
            assert receipt.process_status == "stopped"
            assert receipt.process_exit_code == 0
            assert receipt.subscription_status == "released"
            assert receipt.open_orders_status == "left_open_unverified"
            assert receipt.positions_status == "unobserved"
            assert stop_calls == ["stop_new", "process_stop"]
            assert instances[_INSTANCE_ID].get("_server_service_execution_managed") is None
            assert process.returncode == 0

        asyncio.run(exercise_manager_lifecycle())
        assert _INSTANCE_ID not in manager._processes
        assert manager._gateways == {}
        assert released_legacy == []

        metrics = host_fixture._host_metrics(host)
        assert metrics[0] == "metrics"
        assert metrics[1] == ("bt-cerebro-fill-intent-r1",)
        assert metrics[2] == ()
        assert metrics[3] == ("bt-cerebro-fill-intent-r1",)
        assert metrics[4] == ("bt-cerebro-fill-intent-r1",)
        assert metrics[5] == ("bt-cerebro-fill-intent-r1",)
        assert metrics[6:8] == ("FILLED", 1)
    finally:
        if process is not None and process.returncode is None:
            with contextlib.suppress(Exception):
                asyncio.run(manager.stop_instance(_INSTANCE_ID))
        cleanup = cleanup_host_and_owner()

    assert cleanup["normal_close"] is True
    assert cleanup["forced_cleanup"] is False
