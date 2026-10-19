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
import os
import re
import subprocess
import sys
import sysconfig
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
_BT_SOURCE_COMMIT = "4f3e6a1ca3c41c1e5a726d11cce162faec25b140"
_BT_FIXTURE_SOURCE = (
    "tests/integration/test_btapi_strategy_execution_callbacks_local_process.py",
    28_459,
    "4cf0f713aceeaa7b1b7d4ac2820aa1dd4b6eb3a9b2ecfd5504a25ff846e70ea0",
)
_BT_FAKE_CLIENT_SOURCE = (
    "tests/fixtures/fake_btapi.py",
    7_619,
    "2668398f779b51196c7c4c249fc502a2d2eb7a81c5fe1c8d56b5572c3770f14b",
)
_BT_FIXTURE_TRANSFORMED_SIZE = 29_805
_BT_FIXTURE_TRANSFORMED_SHA256 = (
    "ea906a96c9735d8d4602daf0d3605c1474a27d5337954bd5fde9c7a167fc5616"
)
_BT_FIXTURE_ORIGIN_EXTENSION = (
    b"\n\n# AFI's isolated-wheel acceptance adds an exact Backtrader origin assertion.\n"
    b"_afi_original_loaded_source_origins = _loaded_source_origins\n"
    b"_afi_original_assert_source_origins = _assert_source_origins\n\n"
    b"def _loaded_source_origins():\n"
    b"    origins = _afi_original_loaded_source_origins()\n"
    b"    origins['backtrader'] = {'package': str(Path(bt.__file__).resolve())}\n"
    b"    return origins\n\n"
    b"def _assert_source_origins(origins):\n"
    b"    expected = os.environ.get('AFI_TEST_BACKTRADER_SITE_ROOT')\n"
    b"    actual = origins.get('backtrader', {}).get('package')\n"
    b"    if not expected or not actual:\n"
    b"        raise AssertionError('the isolated Backtrader site-packages root is unavailable')\n"
    b"    if not Path(actual).resolve().is_relative_to(Path(expected).resolve()):\n"
    b"        raise AssertionError('the ServiceHost child imported Backtrader "
    b"outside site-packages')\n"
    b"    inherited = {name: value for name, value in origins.items() if name != 'backtrader'}\n"
    b"    for package, modules in inherited.items():\n"
    b"        for name, source_path in modules.items():\n"
    b"            if not Path(source_path).resolve().is_relative_to(Path(expected).resolve()):\n"
    b"                raise AssertionError(f'{package}.{name} did not load from site-packages')\n"
    b"    _afi_original_assert_source_origins(inherited)\n"
    b"    return origins\n"
)
_BT_ORIGIN_MARKER = "AFI_INSTALLED_PACKAGE_ORIGINS:"
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
_SAFE_ERROR_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


def _finite_error_projection(error):
    error_type = type(error).__name__
    code = getattr(error, "code", None)
    if not (type(code) is str and _SAFE_ERROR_CODE_RE.fullmatch(code)):
        code = None
        if type(error) is RuntimeError:
            message = str(error)
            if _SAFE_ERROR_CODE_RE.fullmatch(message):
                code = message
    return {"type": error_type, "code": code}


async def _cleanup_service_process_after_stop_new(
    manager,
    *,
    subject,
    instance_id,
    profile_ref,
    run_id,
    process,
    stop_receipt,
):
    """Retry only the exact graceful stop after the owner fence was final."""

    if (
        getattr(stop_receipt, "stop_new_status", None) != "acknowledged"
        or getattr(stop_receipt, "stop_new_owner_final", None) is not True
        or getattr(stop_receipt, "stop_new_reconciliation_required", None) is not False
        or getattr(stop_receipt, "stop_new_effect", None) not in {"fenced", "already_fenced"}
    ):
        return {"status": "unknown", "error_code": "STOP_NEW_NOT_CONFIRMED"}
    if getattr(process, "returncode", None) is not None:
        if type(process.returncode) is int and process.returncode == 0:
            return {"status": "already_exited", "error_code": None}
        return {"status": "unknown", "error_code": "PROCESS_EXIT_UNCONFIRMED"}
    processes = getattr(manager, "_processes", None)
    if not isinstance(processes, dict) or processes.get(instance_id) is not process:
        return {"status": "unknown", "error_code": "SERVICE_EXECUTION_RUN_IDENTITY_CHANGED"}
    try:
        result = await manager.stop_instance(
            instance_id,
            user_id=subject,
            expected_service_execution_profile_ref=profile_ref,
            expected_service_execution_run_id=run_id,
            expected_service_execution_process=process,
        )
    except BaseException as error:
        projected = _finite_error_projection(error)
        return {
            "status": "unknown",
            "error_type": projected["type"],
            "error_code": projected["code"],
        }
    if (
        not isinstance(result, dict)
        or result.get("status") != "stopped"
        or type(getattr(process, "returncode", None)) is not int
        or process.returncode != 0
        or processes.get(instance_id) is process
    ):
        return {"status": "unknown", "error_code": "PROCESS_EXIT_UNCONFIRMED"}
    return {"status": "stopped", "error_code": None}


def _stop_receipt_cleanup_facts(receipt):
    return {
        "status": getattr(receipt, "status", "unknown"),
        "error_code": getattr(receipt, "error_code", None),
        "stop_new_status": getattr(receipt, "stop_new_status", None),
        "stop_new_owner_final": getattr(receipt, "stop_new_owner_final", None),
        "stop_new_reconciliation_required": getattr(
            receipt, "stop_new_reconciliation_required", None
        ),
        "stop_new_effect": getattr(receipt, "stop_new_effect", None),
    }


async def _cleanup_started_service_strategy(
    manager,
    owner_control,
    *,
    subject,
    instance_id,
    binding,
    profile_ref,
    run_id,
    process,
    stop_attempted,
    stop_receipt,
    idempotency_key,
):
    """Safely finish one exact started run in the caller's existing loop."""

    if process is None:
        return {"status": "not_started", "error_code": None}
    if stop_receipt is not None and getattr(stop_receipt, "status", None) == "stopped":
        return _stop_receipt_cleanup_facts(stop_receipt)
    if stop_attempted:
        if stop_receipt is None:
            return {"status": "unknown", "error_code": "STOP_RECEIPT_UNAVAILABLE"}
        result = _stop_receipt_cleanup_facts(stop_receipt)
        if (
            getattr(stop_receipt, "stop_new_status", None) != "acknowledged"
            or getattr(stop_receipt, "stop_new_owner_final", None) is not True
            or getattr(stop_receipt, "stop_new_reconciliation_required", None) is not False
            or getattr(stop_receipt, "stop_new_effect", None)
            not in {"fenced", "already_fenced"}
        ):
            return result
    else:
        if (
            owner_control is None
            or binding is None
            or type(profile_ref) is not str
            or not profile_ref
            or type(run_id) is not str
            or not run_id
        ):
            return {"status": "unknown", "error_code": "SERVICE_STRATEGY_SCOPE_UNAVAILABLE"}
        try:
            stop_receipt = await stop_service_strategy_process(
                manager,
                owner_control,
                subject=subject,
                instance_id=instance_id,
                binding=binding,
                idempotency_key=idempotency_key,
                open_order_policy="leave_open_and_report",
            )
        except BaseException as error:
            projected = _finite_error_projection(error)
            return {
                "status": "unknown",
                "error_type": projected["type"],
                "error_code": projected["code"],
                "stop_new_status": None,
                "stop_new_owner_final": None,
                "stop_new_reconciliation_required": None,
                "stop_new_effect": None,
            }
        result = _stop_receipt_cleanup_facts(stop_receipt)
        if getattr(stop_receipt, "status", None) == "stopped":
            return result
        if (
            getattr(stop_receipt, "stop_new_status", None) != "acknowledged"
            or getattr(stop_receipt, "stop_new_owner_final", None) is not True
            or getattr(stop_receipt, "stop_new_reconciliation_required", None) is not False
            or getattr(stop_receipt, "stop_new_effect", None)
            not in {"fenced", "already_fenced"}
        ):
            return result

    try:
        retry = await _cleanup_service_process_after_stop_new(
            manager,
            subject=subject,
            instance_id=instance_id,
            profile_ref=profile_ref,
            run_id=run_id,
            process=process,
            stop_receipt=stop_receipt,
        )
    except BaseException as error:
        projected = _finite_error_projection(error)
        return {
            **result,
            "status": "unknown",
            "error_type": projected["type"],
            "error_code": projected["code"],
        }
    return {**result, **retry}


def test_service_process_failure_cleanup_is_same_loop_and_run_bound(monkeypatch):
    instance_id = "cleanup-instance"
    subject = "cleanup-subject"
    profile_ref = "cleanup-profile"
    run_id = "cleanup-run"
    process = SimpleNamespace(pid=733019, returncode=None, _bt_service_execution=True)
    manager = SimpleNamespace(_processes={instance_id: process})
    stop_receipt = SimpleNamespace(
        status="unknown",
        error_code="SERVICE_EXECUTION_CLOSE_UNCERTAIN",
        stop_new_status="acknowledged",
        stop_new_owner_final=True,
        stop_new_reconciliation_required=False,
        stop_new_effect="fenced",
    )

    async def exercise_cleanup():
        loop = asyncio.get_running_loop()
        calls = []

        async def stop_instance(
            selected_instance,
            *,
            user_id,
            expected_service_execution_profile_ref,
            expected_service_execution_run_id,
            expected_service_execution_process,
        ):
            calls.append(
                (
                    asyncio.get_running_loop(),
                    selected_instance,
                    user_id,
                    expected_service_execution_profile_ref,
                    expected_service_execution_run_id,
                    expected_service_execution_process,
                )
            )
            if len(calls) == 1:
                raise RuntimeError("SERVICE_EXECUTION_CLOSE_UNCERTAIN")
            assert expected_service_execution_process is process
            process.returncode = 0
            manager._processes.pop(instance_id)
            return {"status": "stopped"}

        manager.stop_instance = stop_instance
        try:
            await manager.stop_instance(
                instance_id,
                user_id=subject,
                expected_service_execution_profile_ref=profile_ref,
                expected_service_execution_run_id=run_id,
                expected_service_execution_process=process,
            )
        except RuntimeError as primary_error:
            assert _finite_error_projection(primary_error) == {
                "type": "RuntimeError",
                "code": "SERVICE_EXECUTION_CLOSE_UNCERTAIN",
            }
        else:
            raise AssertionError("the primary stop error was not exercised")

        cleanup = await _cleanup_started_service_strategy(
            manager,
            SimpleNamespace(),
            subject=subject,
            instance_id=instance_id,
            binding=object(),
            profile_ref=profile_ref,
            run_id=run_id,
            process=process,
            stop_attempted=True,
            stop_receipt=stop_receipt,
            idempotency_key="cleanup-test-key",
        )
        assert cleanup["status"] == "stopped"
        assert cleanup["stop_new_status"] == "acknowledged"
        assert cleanup["stop_new_effect"] == "fenced"
        assert len(calls) == 2
        assert all(call[0] is loop for call in calls)
        assert all(
            call[1:] == (instance_id, subject, profile_ref, run_id, process)
            for call in calls
        )

        completed_receipt = SimpleNamespace(
            status="stopped",
            error_code=None,
            stop_new_status="acknowledged",
            stop_new_owner_final=True,
            stop_new_reconciliation_required=False,
            stop_new_effect="fenced",
        )
        duplicate = await _cleanup_started_service_strategy(
            manager,
            SimpleNamespace(),
            subject=subject,
            instance_id=instance_id,
            binding=object(),
            profile_ref=profile_ref,
            run_id=run_id,
            process=process,
            stop_attempted=True,
            stop_receipt=completed_receipt,
            idempotency_key="cleanup-test-key",
        )
        assert duplicate["status"] == "stopped"
        assert len(calls) == 2

        active_process = SimpleNamespace(pid=733020, returncode=None, _bt_service_execution=True)
        replacement_process = SimpleNamespace(
            pid=733021, returncode=None, _bt_service_execution=True
        )
        manager._processes[instance_id] = replacement_process
        mismatch = await _cleanup_started_service_strategy(
            manager,
            SimpleNamespace(),
            subject=subject,
            instance_id=instance_id,
            binding=object(),
            profile_ref=profile_ref,
            run_id=run_id,
            process=active_process,
            stop_attempted=True,
            stop_receipt=stop_receipt,
            idempotency_key="cleanup-test-key",
        )
        assert mismatch["status"] == "unknown"
        assert mismatch["error_code"] == "SERVICE_EXECUTION_RUN_IDENTITY_CHANGED"
        assert len(calls) == 2

        not_fenced = SimpleNamespace(
            stop_new_status="unknown",
            stop_new_owner_final=False,
            stop_new_reconciliation_required=True,
            stop_new_effect=None,
        )
        unconfirmed = await _cleanup_started_service_strategy(
            manager,
            SimpleNamespace(),
            subject=subject,
            instance_id=instance_id,
            binding=object(),
            profile_ref=profile_ref,
            run_id=run_id,
            process=active_process,
            stop_attempted=True,
            stop_receipt=not_fenced,
            idempotency_key="cleanup-test-key",
        )
        assert unconfirmed["status"] == "unknown"
        assert unconfirmed["stop_new_status"] == "unknown"
        assert len(calls) == 2

        untrusted = await _cleanup_started_service_strategy(
            manager,
            None,
            subject=subject,
            instance_id=instance_id,
            binding=None,
            profile_ref=None,
            run_id=None,
            process=active_process,
            stop_attempted=False,
            stop_receipt=None,
            idempotency_key="cleanup-test-key",
        )
        assert untrusted == {
            "status": "unknown",
            "error_code": "SERVICE_STRATEGY_SCOPE_UNAVAILABLE",
        }
        assert len(calls) == 2

        cleanup_process = SimpleNamespace(
            pid=733022, returncode=None, _bt_service_execution=True
        )
        cleanup_manager = SimpleNamespace(_processes={instance_id: cleanup_process})
        owner_calls = []
        expected_binding = object()
        cleanup_receipt = SimpleNamespace(
            status="stopped",
            error_code=None,
            stop_new_status="acknowledged",
            stop_new_owner_final=True,
            stop_new_reconciliation_required=False,
            stop_new_effect="fenced",
        )

        async def issue_stop_new_and_stop(
            selected_manager,
            selected_owner,
            *,
            subject,
            instance_id,
            binding,
            idempotency_key,
            open_order_policy,
        ):
            owner_calls.append(
                (
                    asyncio.get_running_loop(),
                    selected_manager,
                    selected_owner,
                    subject,
                    instance_id,
                    binding,
                    idempotency_key,
                    open_order_policy,
                )
            )
            assert selected_manager is cleanup_manager
            assert selected_owner is owner_control
            assert binding is expected_binding
            cleanup_process.returncode = 0
            selected_manager._processes.pop(instance_id)
            return cleanup_receipt

        owner_control = object()
        monkeypatch.setattr(
            sys.modules[__name__], "stop_service_strategy_process", issue_stop_new_and_stop
        )
        owner_cleanup = await _cleanup_started_service_strategy(
            cleanup_manager,
            owner_control,
            subject=subject,
            instance_id=instance_id,
            binding=expected_binding,
            profile_ref=profile_ref,
            run_id=run_id,
            process=cleanup_process,
            stop_attempted=False,
            stop_receipt=None,
            idempotency_key="cleanup-test-owner-fence",
        )
        assert owner_cleanup["status"] == "stopped"
        assert owner_cleanup["stop_new_status"] == "acknowledged"
        assert len(owner_calls) == 1
        assert owner_calls[0][0] is loop
        assert owner_calls[0][3:] == (
            subject,
            instance_id,
            expected_binding,
            "cleanup-test-owner-fence",
            "leave_open_and_report",
        )

    asyncio.run(exercise_cleanup())


def _pinned_bt_test_source(relative_path: str, size: int, sha256: str) -> bytes:
    source_path = _BACKTRADER_ROOT / Path(relative_path)
    if not source_path.is_file():
        raise AssertionError(f"pinned Backtrader test helper is unavailable: {relative_path}")
    source = source_path.read_bytes().replace(b"\r\n", b"\n")
    if b"\r" in source or len(source) != size or hashlib.sha256(source).hexdigest() != sha256:
        raise AssertionError(f"pinned Backtrader test helper changed: {relative_path}")
    return source


def _load_r249_host_fixture(tmp_path, monkeypatch):
    helper_root = tmp_path / "bt-test-helpers"
    helper_tests = helper_root / "tests"
    fixture_dir = helper_tests / "fixtures"
    integration_dir = helper_tests / "integration"
    fixture_dir.mkdir(parents=True)
    integration_dir.mkdir(parents=True)
    (helper_tests / "__init__.py").write_text("", encoding="utf-8")
    (fixture_dir / "__init__.py").write_text("", encoding="utf-8")
    (integration_dir / "__init__.py").write_text("", encoding="utf-8")

    fixture_relative, fixture_size, fixture_sha256 = _BT_FIXTURE_SOURCE
    fixture_source = (
        f"# AFI test-only copy from Backtrader {_BT_SOURCE_COMMIT}\n".encode("ascii")
        + _pinned_bt_test_source(fixture_relative, fixture_size, fixture_sha256)
        + _BT_FIXTURE_ORIGIN_EXTENSION
    )
    if (
        len(fixture_source) != _BT_FIXTURE_TRANSFORMED_SIZE
        or hashlib.sha256(fixture_source).hexdigest() != _BT_FIXTURE_TRANSFORMED_SHA256
    ):
        raise AssertionError("the pinned Backtrader host-helper transformation changed")
    fake_relative, fake_size, fake_sha256 = _BT_FAKE_CLIENT_SOURCE
    fake_source = _pinned_bt_test_source(fake_relative, fake_size, fake_sha256)
    (integration_dir / f"{_BT_FIXTURE_MODULE}.py").write_bytes(fixture_source)
    (fixture_dir / "fake_btapi.py").write_bytes(fake_source)
    if (helper_root / "backtrader").exists():
        raise AssertionError("the test-only helper root must not contain production Backtrader")

    monkeypatch.syspath_prepend(str(integration_dir))
    monkeypatch.syspath_prepend(str(helper_root))
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    saved_test_modules = {
        name: module
        for name, module in tuple(sys.modules.items())
        if name == "tests" or name.startswith("tests.")
    }
    for name in saved_test_modules:
        sys.modules.pop(name, None)
    sys.modules.pop(_BT_FIXTURE_MODULE, None)
    try:
        fixture = importlib.import_module(_BT_FIXTURE_MODULE)
        if not Path(fixture.__file__).resolve().is_relative_to(integration_dir.resolve()):
            raise AssertionError("the Backtrader host helper did not load from its test-only root")
        return fixture, helper_root
    finally:
        for name in tuple(sys.modules):
            if name == "tests" or name.startswith("tests."):
                sys.modules.pop(name, None)
        sys.modules.update(saved_test_modules)


def _assert_installed_package_origins():
    purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
    module_names = (
        "app.services.live_trading.manager",
        "app.services.live_trading.service_execution_launch",
        "app.services.live_trading.service_execution_runner",
        "app.services.service_gateway_operator",
        "backtrader.stores.service_execution_session",
        "bt_api_base.service_protocol",
        "bt_api_execution.service_order_entry",
        "bt_api_py.gateway_operator_application",
        "bt_api_py.gateway_operator",
        "bt_api_py.service_host",
        "bt_api_py.service_runtime",
        "bt_api_transport_zmq.service_v2",
    )
    origins = {}
    for name in module_names:
        module = importlib.import_module(name)
        origin = Path(module.__file__).resolve()
        if not origin.is_relative_to(purelib):
            raise AssertionError(f"{name} did not load from the isolated environment")
        origins[name] = str(origin)
    return purelib, origins


def _strategy_source() -> str:
    return '''
import datetime as dt
import importlib
import json
import sys
import sysconfig
import time
from pathlib import Path

import backtrader as bt
import pandas as pd
from tests.fixtures.fake_btapi import FakeBtApiClient, make_store

_purelib = Path(sysconfig.get_paths()["purelib"]).resolve()
_origin_modules = {
    "app.service_execution_launch": importlib.import_module(
        "app.services.live_trading.service_execution_launch"
    ),
    "app.service_execution_runner": importlib.import_module(
        "app.services.live_trading.service_execution_runner"
    ),
    "backtrader.service_execution_session": importlib.import_module(
        "backtrader.stores.service_execution_session"
    ),
    "bt_api_base.service_protocol": importlib.import_module(
        "bt_api_base.service_protocol"
    ),
    "bt_api_execution.service_order_entry": importlib.import_module(
        "bt_api_execution.service_order_entry"
    ),
    "bt_api_py.gateway_operator_application": importlib.import_module(
        "bt_api_py.gateway_operator_application"
    ),
    "bt_api_py.service_runtime": importlib.import_module("bt_api_py.service_runtime"),
    "bt_api_transport_zmq.service_v2": importlib.import_module(
        "bt_api_transport_zmq.service_v2"
    ),
}
_origin_paths = {
    name: str(Path(module.__file__).resolve()) for name, module in _origin_modules.items()
}
_origin_paths["backtrader"] = str(Path(bt.__file__).resolve())
_origin_paths["app.service_execution_runner.__main__"] = str(
    Path(sys.modules["__main__"].__file__).resolve()
)
if any(not Path(value).is_relative_to(_purelib) for value in _origin_paths.values()):
    raise RuntimeError("AFI_SERVICE_DEPENDENCY_NOT_INSTALLED")
print("AFI_INSTALLED_PACKAGE_ORIGINS:" + json.dumps(_origin_paths, sort_keys=True), flush=True)

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


def test_r249_fixture_relocation_uses_installed_packages_only(tmp_path, monkeypatch):
    purelib, origins = _assert_installed_package_origins()
    monkeypatch.setenv("AFI_TEST_BACKTRADER_SITE_ROOT", str(purelib))
    fixture, helper_root = _load_r249_host_fixture(tmp_path, monkeypatch)
    try:
        assert not (helper_root / "backtrader").exists()
        copied_paths = {
            str(path.relative_to(helper_root)).replace("\\", "/")
            for path in helper_root.rglob("*")
            if path.is_file() and path.suffix == ".py"
        }
        assert copied_paths == {
            "tests/__init__.py",
            "tests/fixtures/__init__.py",
            "tests/fixtures/fake_btapi.py",
            "tests/integration/__init__.py",
            f"tests/integration/{_BT_FIXTURE_MODULE}.py",
        }
        copied_fixture = (
            helper_root / "tests" / "integration" / f"{_BT_FIXTURE_MODULE}.py"
        ).read_bytes()
        assert len(copied_fixture) == _BT_FIXTURE_TRANSFORMED_SIZE
        assert hashlib.sha256(copied_fixture).hexdigest() == _BT_FIXTURE_TRANSFORMED_SHA256
        copied_fake = (helper_root / "tests" / "fixtures" / "fake_btapi.py").read_bytes()
        assert hashlib.sha256(copied_fake).hexdigest() == _BT_FAKE_CLIENT_SOURCE[2]
        assert Path(fixture.__file__).resolve().is_relative_to(
            (helper_root / "tests" / "integration").resolve()
        )
        host_origins = fixture._assert_source_origins(fixture._loaded_source_origins())
        bt_origin = Path(host_origins["backtrader"]["package"]).resolve()
        assert bt_origin.is_relative_to(purelib)
        assert origins["app.services.live_trading.manager"].startswith(str(purelib))
    finally:
        sys.modules.pop(_BT_FIXTURE_MODULE, None)


def test_service_strategy_child_import_prefix_uses_installed_packages_without_host(
    tmp_path, monkeypatch
):
    purelib, _ = _assert_installed_package_origins()
    fixture, helper_root = _load_r249_host_fixture(tmp_path, monkeypatch)
    del fixture
    script_dir = tmp_path / "strategy"
    script_dir.mkdir()
    strategy_path = script_dir / "run.py"
    source = _strategy_source().lstrip()
    strategy_path.write_text(source, encoding="utf-8")
    runner_path = purelib / "app" / "services" / "live_trading" / "service_execution_runner.py"
    preflight_path = tmp_path / "child-import-preflight.py"
    preflight_path.write_text(
        "\n".join(
            (
                "import sys",
                "from pathlib import Path",
                f"script_path = Path({str(strategy_path)!r})",
                f"runner_path = Path({str(runner_path)!r})",
                "source = script_path.read_text(encoding='utf-8')",
                "marker = 'AFI_SERVICE_INTENT_CONTRACT_REF ='",
                "prefix, remainder = source.split(marker, 1)",
                "sys.modules['__main__'].__file__ = str(runner_path)",
                "sys.path.insert(0, str(script_path.parent))",
                "namespace = {'__name__': '__main__', '__file__': str(runner_path), '__builtins__': __builtins__}",
                "exec(compile(prefix, str(script_path), 'exec'), namespace, namespace)",
                "print('AFI_NOHOST_CHILD_IMPORT_PREFIX:PASS', flush=True)",
                "import backtrader as bt",
                "original_run = bt.Cerebro.run",
                "bt.Cerebro.run = lambda self, *args, **kwargs: None",
                "try:",
                "    exec(compile(marker + remainder, str(script_path), 'exec'), namespace, namespace)",
                "finally:",
                "    bt.Cerebro.run = original_run",
                "assert namespace['_store']._api.connected is False",
                "assert namespace['_cerebro'].datas",
                "print('AFI_NOHOST_FAKE_STORE_CEREBRO_CONSTRUCTION:PASS', flush=True)",
                "",
            )
        ),
        encoding="utf-8",
    )
    child_env = {
        name: os.environ[name]
        for name in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONUTF8")
        if name in os.environ
    }
    child_env["PYTHONPATH"] = os.pathsep.join((str(helper_root), str(purelib)))
    completed = subprocess.run(
        [sys.executable, str(preflight_path)],
        cwd=script_dir,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert "AFI_NOHOST_CHILD_IMPORT_PREFIX:PASS" in completed.stdout
    assert "AFI_NOHOST_FAKE_STORE_CEREBRO_CONSTRUCTION:PASS" in completed.stdout
    origin_line = next(
        line for line in completed.stdout.splitlines() if _BT_ORIGIN_MARKER in line
    )
    child_origins = json.loads(origin_line.split(_BT_ORIGIN_MARKER, 1)[1])
    assert all(Path(origin).resolve().is_relative_to(purelib) for origin in child_origins.values())


def test_live_manager_runs_service_strategy_order_query_and_graceful_stop(
    tmp_path, monkeypatch, request
):
    purelib, _ = _assert_installed_package_origins()
    monkeypatch.setenv("AFI_TEST_BACKTRADER_SITE_ROOT", str(purelib))
    host_fixture, helper_root = _load_r249_host_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(manager_module, "_BACKTRADER_DIR", helper_root)
    endpoint, keys, host = host_fixture._start_host(tmp_path)
    owner_token = object()
    owner_registered = False
    host_cleanup = None
    host_pid_before_cleanup = None
    host_alive_before_cleanup = None
    phase = "host_started"
    cleanup_receipt_path = tmp_path / "service-host-cleanup.json"
    process = None
    manager = None
    stop_receipt = None
    strategy_cleanup_result = None
    instances = {}
    plugin_root = tmp_path / "trusted-profiles"
    profile_module_name = f"afi_service_strategy_{uuid.uuid4().hex}"
    owner_module_name = f"afi_service_owner_{uuid.uuid4().hex}"

    def cleanup_host_and_owner(
        *,
        phase_name: str = "pytest_finalizer",
        primary_error=None,
        strategy_cleanup_result=None,
    ):
        nonlocal host_cleanup, owner_registered, host_pid_before_cleanup, host_alive_before_cleanup
        if primary_error is None and cleanup_receipt_path.is_file():
            try:
                previous_facts = json.loads(
                    cleanup_receipt_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                previous_facts = None
            if (
                isinstance(previous_facts, dict)
                and previous_facts.get("phase") != "pytest_finalizer"
            ):
                return previous_facts
        cleanup_error_types = []
        if owner_registered:
            try:
                unregister_legacy_gateway_exclusions(owner_token)
                owner_registered = False
            except BaseException as error:
                cleanup_error_types.append(type(error).__name__)
        if host_cleanup is None:
            host_process = host.get("process")
            host_pid_before_cleanup = getattr(host_process, "pid", None)
            try:
                host_alive_before_cleanup = bool(host_process.is_alive())
            except BaseException as error:
                host_alive_before_cleanup = None
                cleanup_error_types.append(type(error).__name__)
            try:
                host_cleanup = host_fixture._close_host(host)
            except BaseException as error:
                host_cleanup = {
                    "close_reply": None,
                    "close_error": type(error).__name__,
                    "exitcode": None,
                    "forced_cleanup": None,
                    "normal_close": False,
                }
                cleanup_error_types.append(type(error).__name__)
        for module_name in (profile_module_name, owner_module_name):
            try:
                sys.modules.pop(module_name, None)
            except BaseException as error:
                cleanup_error_types.append(type(error).__name__)
        try:
            sys.modules.pop(_BT_FIXTURE_MODULE, None)
        except BaseException as error:
            cleanup_error_types.append(type(error).__name__)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(plugin_root))

        owned_process = process
        if owned_process is None and manager is not None:
            owned_process = manager._processes.get(_INSTANCE_ID)
        process_pid = getattr(owned_process, "pid", None)
        process_returncode = getattr(owned_process, "returncode", None)
        raw_instance_pid = instances.get(_INSTANCE_ID, {}).get("pid")
        instance_pid = raw_instance_pid if type(raw_instance_pid) is int else None
        primary_error_projection = (
            _finite_error_projection(primary_error) if primary_error is not None else None
        )
        if isinstance(strategy_cleanup_result, dict):
            strategy_cleanup_status = strategy_cleanup_result.get("status")
            strategy_stop_error_type = strategy_cleanup_result.get("error_type")
            strategy_stop_error_code = strategy_cleanup_result.get("error_code")
        elif owned_process is None:
            strategy_cleanup_status = "not_started"
            strategy_stop_error_type = None
            strategy_stop_error_code = None
        elif type(process_returncode) is int and process_returncode == 0:
            strategy_cleanup_status = "stopped"
            strategy_stop_error_type = None
            strategy_stop_error_code = None
        else:
            strategy_cleanup_status = "unknown"
            strategy_stop_error_type = None
            strategy_stop_error_code = "PROCESS_EXIT_UNCONFIRMED"
        facts = dict(host_cleanup)
        facts.update(
            {
                "phase": phase_name,
                "primary_error_type": (
                    primary_error_projection["type"]
                    if primary_error_projection is not None
                    else None
                ),
                "primary_error_code": (
                    primary_error_projection["code"]
                    if primary_error_projection is not None
                    else None
                ),
                "strategy_cleanup_status": strategy_cleanup_status,
                "strategy_stop_error_type": strategy_stop_error_type,
                "strategy_stop_error_code": strategy_stop_error_code,
                "strategy_cleanup_stop_new_status": (
                    strategy_cleanup_result.get("stop_new_status")
                    if isinstance(strategy_cleanup_result, dict)
                    else None
                ),
                "strategy_cleanup_stop_new_owner_final": (
                    strategy_cleanup_result.get("stop_new_owner_final")
                    if isinstance(strategy_cleanup_result, dict)
                    else None
                ),
                "strategy_cleanup_stop_new_reconciliation_required": (
                    strategy_cleanup_result.get("stop_new_reconciliation_required")
                    if isinstance(strategy_cleanup_result, dict)
                    else None
                ),
                "strategy_cleanup_stop_new_effect": (
                    strategy_cleanup_result.get("stop_new_effect")
                    if isinstance(strategy_cleanup_result, dict)
                    else None
                ),
                "strategy_process_tracked": owned_process is not None,
                "strategy_process_pid": process_pid if type(process_pid) is int else None,
                "strategy_process_returncode": (
                    process_returncode if type(process_returncode) is int else None
                ),
                "strategy_instance_pid": instance_pid,
                "host_process_pid": (
                    host_pid_before_cleanup
                    if type(host_pid_before_cleanup) is int
                    else None
                ),
                "host_alive_before_cleanup": host_alive_before_cleanup,
                "owner_exclusion_still_registered": owner_registered,
                "cleanup_error_types": cleanup_error_types,
            }
        )
        try:
            facts["receipt_written"] = True
            cleanup_receipt_path.write_text(
                json.dumps(facts, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        except BaseException as error:
            facts["receipt_written"] = False
            facts["receipt_write_error_type"] = type(error).__name__
        host_cleanup = facts
        return facts

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

    try:
        async def exercise_manager_lifecycle():
            nonlocal phase, process, stop_receipt, strategy_cleanup_result
            stop_attempted = False
            run_id = None
            profile_ref = None
            binding = None
            owner_control = None
            phase = "manager_start"
            started = None
            try:
                started = await manager.start_instance(_INSTANCE_ID, user_id=_SUBJECT_REF)
                phase = "strategy_ready"
                process = manager._processes.get(_INSTANCE_ID)
                current_instance = instances.get(_INSTANCE_ID, {})
                run_id = current_instance.get("_server_service_execution_run_id")
                profile_ref = current_instance.get("_server_service_execution_profile_ref")
                if (
                    isinstance(started, dict)
                    and started.get("status") == "running"
                    and started.get("_server_service_execution_managed") is True
                    and current_instance.get("user_id") == _SUBJECT_REF
                    and current_instance.get("_server_service_execution_managed") is True
                    and type(run_id) is str
                    and run_id
                    and type(profile_ref) is str
                    and profile_ref == _PROFILE_REF
                    and started.get("_server_service_execution_profile_ref") == profile_ref
                    and getattr(process, "_bt_service_execution", False) is True
                    and type(current_instance.get("pid")) is int
                    and current_instance.get("pid") == getattr(process, "pid", None)
                ):
                    stop_calls = []
                    binding = SimpleNamespace(
                        config=SimpleNamespace(
                            subject=_SUBJECT_REF,
                            allowed_actions=["STOP_NEW"],
                            wire_account_ref=_ACCOUNT_REF,
                            command_scope=f"strategy:{_STRATEGY_REF}:{run_id}:stop_new",
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
                                "effect_result": {
                                    "action": "stop_new",
                                    "result": "fenced",
                                },
                                "request_recorded": True,
                                "owner_final": True,
                                "reconciliation_required": False,
                            }

                    owner_control = _OwnerControlDeployment()
                    owner_control.bindings = (binding,)

                assert started["status"] == "running"
                assert started["_server_service_execution_managed"] is True
                assert started["_server_service_execution_profile_ref"] == _PROFILE_REF
                assert getattr(process, "_bt_service_execution", False) is True
                log_path = script_path.parent / "logs" / "subprocess.stdout.log"
                origin_text = _wait_for_log_marker(log_path, _BT_ORIGIN_MARKER)
                origin_line = next(
                    line for line in origin_text.splitlines() if _BT_ORIGIN_MARKER in line
                )
                child_origins = json.loads(origin_line.split(_BT_ORIGIN_MARKER, 1)[1])
                assert set(child_origins) == {
                    "app.service_execution_launch",
                    "app.service_execution_runner",
                    "app.service_execution_runner.__main__",
                    "backtrader",
                    "backtrader.service_execution_session",
                    "bt_api_base.service_protocol",
                    "bt_api_execution.service_order_entry",
                    "bt_api_py.gateway_operator_application",
                    "bt_api_py.service_runtime",
                    "bt_api_transport_zmq.service_v2",
                }
                assert all(
                    Path(origin).resolve().is_relative_to(purelib)
                    for origin in child_origins.values()
                )
                host_bt_origin = Path(
                    host["source_origins"]["backtrader"]["package"]
                ).resolve()
                assert host_bt_origin.is_relative_to(purelib)
                text = _wait_for_log_marker(log_path, _ORDER_QUERY_MARKER)
                assert _ORDER_QUERY_MARKER in text

                graceful_stop = manager._gracefully_stop_service_execution

                async def observe_process_stop(instance_id, stopped_process):
                    stop_calls.append("process_stop")
                    await graceful_stop(instance_id, stopped_process)

                manager._gracefully_stop_service_execution = observe_process_stop
                phase = "strategy_stop"
                stop_attempted = True
                stop_receipt = await stop_service_strategy_process(
                    manager,
                    owner_control,
                    subject=_SUBJECT_REF,
                    instance_id=_INSTANCE_ID,
                    binding=binding,
                    idempotency_key="afi08-stop-r1-test-key",
                    open_order_policy="leave_open_and_report",
                )
                assert stop_receipt.status == "stopped"
                assert stop_receipt.stop_new_effect == "fenced"
                assert stop_receipt.process_status == "stopped"
                assert stop_receipt.process_exit_code == 0
                assert stop_receipt.subscription_status == "released"
                assert stop_receipt.open_orders_status == "left_open_unverified"
                assert stop_receipt.positions_status == "unobserved"
                assert stop_calls == ["stop_new", "process_stop"]
                assert instances[_INSTANCE_ID].get("_server_service_execution_managed") is None
                assert process.returncode == 0
            finally:
                if process is None:
                    process = manager._processes.get(_INSTANCE_ID)
                strategy_cleanup_result = await _cleanup_started_service_strategy(
                    manager,
                    owner_control,
                    subject=_SUBJECT_REF,
                    instance_id=_INSTANCE_ID,
                    binding=binding,
                    profile_ref=profile_ref,
                    run_id=run_id,
                    process=process,
                    stop_attempted=stop_attempted,
                    stop_receipt=stop_receipt,
                    idempotency_key="afi08-stop-r1-test-key",
                )

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
        primary_error = sys.exc_info()[1]
        cleanup = cleanup_host_and_owner(
            phase_name=phase,
            primary_error=primary_error,
            strategy_cleanup_result=strategy_cleanup_result,
        )

    assert cleanup["normal_close"] is True
    assert cleanup["forced_cleanup"] is False
    assert cleanup["owner_exclusion_still_registered"] is False
    assert cleanup["cleanup_error_types"] == []
    assert cleanup["receipt_written"] is True
