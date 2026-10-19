from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace

import pytest

from app.services.live_trading import manager as manager_module
from app.services.live_trading import strategy_process_stop as stop_module


def _stop_fixture(monkeypatch, *, stop_projection):
    profile = SimpleNamespace(
        profile_ref="profile.test",
        strategy_id="strategy.test",
        account_ref="account.test",
        strategy_ref="strategy-ref.test",
        authorized_subjects=frozenset({"subject.test"}),
    )
    process = SimpleNamespace(pid=321, returncode=None, _bt_service_execution=True)
    instance = {
        "id": "instance.test",
        "user_id": "subject.test",
        "strategy_id": "strategy.test",
        "status": "running",
        "pid": process.pid,
        "_server_execution_mode": "live",
        "_server_service_execution_managed": True,
        "_server_service_execution_profile_ref": profile.profile_ref,
        "_server_service_execution_run_id": "run.test",
    }
    binding = SimpleNamespace(
        config=SimpleNamespace(
            subject="subject.test",
            allowed_actions=["STOP_NEW"],
            wire_account_ref=profile.account_ref,
            command_scope=f"strategy:{profile.strategy_ref}:run.test:stop_new",
        ),
        wire_scope=SimpleNamespace(
            account_ref=profile.account_ref,
            strategy_ref=profile.strategy_ref,
            run_id="run.test",
        ),
    )

    class _Deployment:
        def __init__(self, *, envelope_action="stop_new", deployment_version="owner-v1"):
            self.bindings = (binding,)
            self.calls = []
            self.envelope_action = envelope_action
            self.deployment_version = deployment_version

        def submit_control(self, selected_binding, **kwargs):
            self.calls.append((selected_binding, kwargs))
            return {
                "action": self.envelope_action,
                "deployment_version": self.deployment_version,
                **stop_projection,
            }

    class _Manager:
        def __init__(self):
            self._processes = {"instance.test": process}
            self.stop_calls = []

        async def stop_instance(self, instance_id, **kwargs):
            self.stop_calls.append((instance_id, kwargs))
            process.returncode = 0
            return {"status": "stopped"}

    deployment = _Deployment()
    manager = _Manager()
    monkeypatch.setattr(manager_module, "_instance_store_lock", contextlib.nullcontext)
    monkeypatch.setattr(manager_module, "_load_instances", lambda: {"instance.test": instance})
    monkeypatch.setattr(
        stop_module,
        "get_service_strategy_profile_registry",
        lambda _refs: SimpleNamespace(resolve=lambda _profile_ref: profile),
    )
    return manager, deployment, binding, process, profile


def test_unresolved_stop_new_keeps_strategy_and_does_not_claim_cleanup(monkeypatch):
    manager, deployment, binding, process, _profile = _stop_fixture(
        monkeypatch,
        stop_projection={
            "command_id": "afi-monitor-stop-new-v1-" + "a" * 32,
            "status": "unknown",
            "outcome": "unknown",
            "effect_ref": None,
            "effect_result": None,
            "request_recorded": True,
            "owner_final": False,
            "reconciliation_required": True,
        },
    )

    receipt = asyncio.run(
        stop_module.stop_service_strategy_process(
            manager,
            deployment,
            subject="subject.test",
            instance_id="instance.test",
            binding=binding,
            idempotency_key="afi08-unknown-r1",
            open_order_policy="leave_open_and_report",
        )
    )

    assert deployment.calls[0][1]["action"] == "STOP_NEW"
    assert receipt.status == "unknown"
    assert receipt.stop_new_status == "unknown"
    assert receipt.stop_new_command_id == "afi-monitor-stop-new-v1-" + "a" * 32
    assert receipt.stop_new_owner_final is False
    assert receipt.stop_new_reconciliation_required is True
    assert receipt.process_status == "running"
    assert receipt.subscription_status == "retained"
    assert receipt.open_orders_status == "not_reached"
    assert receipt.positions_status == "unobserved"
    assert manager.stop_calls == []
    assert process.returncode is None


def test_rejected_stop_new_is_partial_and_does_not_release_strategy(monkeypatch):
    manager, deployment, binding, process, _profile = _stop_fixture(
        monkeypatch,
        stop_projection={
            "command_id": "afi-monitor-stop-new-v1-" + "a" * 32,
            "status": "rejected",
            "outcome": "rejected",
            "effect_ref": None,
            "effect_result": {"action": "stop_new", "result": "run_not_active"},
            "request_recorded": True,
            "owner_final": True,
            "reconciliation_required": False,
        },
    )

    receipt = asyncio.run(
        stop_module.stop_service_strategy_process(
            manager,
            deployment,
            subject="subject.test",
            instance_id="instance.test",
            binding=binding,
            idempotency_key="afi08-rejected-r1",
            open_order_policy="leave_open_and_report",
        )
    )

    assert receipt.status == "partial"
    assert receipt.stop_new_status == "rejected"
    assert receipt.process_status == "running"
    assert receipt.subscription_status == "retained"
    assert receipt.open_orders_status == "not_reached"
    assert manager.stop_calls == []
    assert process.returncode is None


def test_wrong_subject_cannot_submit_or_stop(monkeypatch):
    manager, deployment, binding, process, _profile = _stop_fixture(
        monkeypatch,
        stop_projection={},
    )

    with pytest.raises(stop_module.StrategyProcessStopError) as error:
        asyncio.run(
            stop_module.stop_service_strategy_process(
                manager,
                deployment,
                subject="subject.attacker",
                instance_id="instance.test",
                binding=binding,
                idempotency_key="afi08-denied-r1",
                open_order_policy="leave_open_and_report",
            )
        )

    assert error.value.code == "OWNER_CONTROL_NOT_AUTHORIZED"
    assert deployment.calls == []
    assert manager.stop_calls == []
    assert process.returncode is None


def test_run_mismatch_is_rejected_before_owner_or_process_action(monkeypatch):
    manager, deployment, binding, process, _profile = _stop_fixture(
        monkeypatch,
        stop_projection={},
    )
    binding.wire_scope.run_id = "another.run"

    with pytest.raises(stop_module.StrategyProcessStopError) as error:
        asyncio.run(
            stop_module.stop_service_strategy_process(
                manager,
                deployment,
                subject="subject.test",
                instance_id="instance.test",
                binding=binding,
                idempotency_key="afi08-mismatch-r1",
                open_order_policy="leave_open_and_report",
            )
        )

    assert error.value.code == "OWNER_CONTROL_RUN_MISMATCH"
    assert deployment.calls == []
    assert manager.stop_calls == []
    assert process.returncode is None


def test_wrong_owner_action_envelope_stays_unknown_and_does_not_stop(monkeypatch):
    manager, deployment, binding, process, _profile = _stop_fixture(
        monkeypatch,
        stop_projection={
            "command_id": "afi-monitor-stop-new-v1-" + "a" * 32,
            "status": "acknowledged",
            "outcome": "applied",
            "effect_ref": "strategy-stop-new-v1:" + "b" * 64,
            "effect_result": {"action": "stop_new", "result": "fenced"},
            "request_recorded": True,
            "owner_final": True,
            "reconciliation_required": False,
        },
    )
    deployment.envelope_action = "freeze"
    receipt = asyncio.run(
        stop_module.stop_service_strategy_process(
            manager,
            deployment,
            subject="subject.test",
            instance_id="instance.test",
            binding=binding,
            idempotency_key="afi08-wrong-envelope-r1",
            open_order_policy="leave_open_and_report",
        )
    )

    assert receipt.status == "unknown"
    assert receipt.stop_new_status == "unknown"
    assert receipt.process_status == "running"
    assert receipt.subscription_status == "retained"
    assert manager.stop_calls == []
    assert process.returncode is None
