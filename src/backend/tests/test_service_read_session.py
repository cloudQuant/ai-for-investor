"""Boundary tests for the explicitly owned SDK service-read session."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope

from app.services.service_read import client as read_client_module
from app.services.service_read.client import (
    AccountBinding,
    AuthorizedServiceReadClient,
    OrderBinding,
    ServiceReadClientCloseError,
    ServiceReadUnavailableError,
)
from app.services.service_read.session import (
    SdkServiceReadSession,
    ServiceReadSessionError,
)


def _identity(actor_ref: str = "application-a") -> WireIdentity:
    return WireIdentity(WireRole.APPLICATION_CLIENT, "principal-a", actor_ref)


def _account_binding() -> AccountBinding:
    return AccountBinding(
        mount="application.account",
        scope_ref="account-a-read-v1",
        currency="USD",
        account_key=object(),
        coverage=(object(),),
    )


def _account_scope(account_ref: str = "account-a") -> WireScope:
    return WireScope("paper:venue-a", account_ref=account_ref)


def _registered(
    mount: str, scope_ref: str, operation: str | frozenset[str], scope: WireScope
):
    operations = frozenset({operation}) if type(operation) is str else operation
    return SimpleNamespace(
        mount=mount,
        scope_ref=scope_ref,
        operations=operations,
        active=True,
        scope=scope,
    )


class _Runtime:
    def __init__(self, identity: WireIdentity | None = None) -> None:
        self.identity = identity or _identity()
        self.state = "new"
        self.healthy = False
        self.cleanup_failures = 0
        self.unregister_uncertainties = 0
        self.bindings = [
            _registered(
                "application.account",
                "account-a-read-v1",
                frozenset({"account.snapshot", "account.head"}),
                _account_scope(),
            )
        ]
        self.view_scope_ref = "account-a-read-v1"
        self.view_scope = _account_scope()
        self.calls: list[tuple[object, ...]] = []
        self.maintain_calls = 0
        self.close_calls = 0

    def start(self):
        self.state = "registered"
        self.healthy = True
        return SimpleNamespace(bindings=tuple(self.bindings))

    def maintain(self):
        self.maintain_calls += 1

    def account_binding_view(self, mount, account_ref, *, required_operations):
        return SimpleNamespace(
            mount=mount,
            scope_ref=self.view_scope_ref,
            account_ref=account_ref,
            operations=frozenset({"account.snapshot", "account.head"}),
            rpc_scope=self.view_scope,
        )

    def call(self, mount, operation, arguments, **kwargs):
        self.calls.append((mount, operation, dict(arguments), kwargs))
        return {"found": False, "record": None}

    def close(self):
        self.close_calls += 1
        self.state = "closed"
        self.healthy = False


class _Facade:
    def __init__(
        self,
        runtime: _Runtime,
        *,
        expected_scope_ref: str | None = None,
        fail_close: bool = False,
    ) -> None:
        self.runtime = runtime
        self.expected_scope_ref = expected_scope_ref
        self.fail_close = fail_close
        self.close_calls = 0

    def refresh(self):
        self.runtime.maintain()
        binding = self.runtime.account_binding_view(
            "application.account",
            "account-a",
            required_operations=frozenset({"account.snapshot"}),
        )
        if self.expected_scope_ref is not None and binding.scope_ref != self.expected_scope_ref:
            raise _SdkScopeError()
        self.runtime.call(
            "application.account",
            "account.snapshot",
            {"limit": 1},
            account_ref="account-a",
            scope_ref="account-a-read-v1",
        )
        return SimpleNamespace(observation=None)

    def close(self):
        self.close_calls += 1
        if self.fail_close:
            raise RuntimeError("facade close failed")


class _SdkScopeError(RuntimeError):
    code = "SCOPE_DENIED"


def test_session_uses_exact_registered_scope_for_order_read():
    runtime = _Runtime()
    runtime.bindings.append(
        _registered(
            "application.orders",
            "strategy-a-read-v1",
            "orders.query",
            WireScope("paper:venue-a", strategy_ref="strategy-a"),
        )
    )
    session = SdkServiceReadSession(
        lambda: runtime,
        _identity(),
        account_bindings={"account-a": _account_binding()},
        order_bindings={
            "strategy-a-read-v1": OrderBinding(
                mount="application.orders", scope_ref="strategy-a-read-v1"
            )
        },
    )
    session.start()

    view = session.read_order("strategy-a-read-v1", "intent-17")

    assert view.intent_id == "intent-17"
    assert runtime.calls == [
        (
            "application.orders",
            "orders.query",
            {"intent_id": "intent-17"},
            {"scope_ref": "strategy-a-read-v1"},
        )
    ]
    session.close()
    assert session.close_succeeded


def test_session_passes_expected_account_scope_to_facade_and_denies_rebind(monkeypatch):
    runtime = _Runtime()
    captured: dict[str, object] = {}

    def create_facade(*args, **kwargs):
        captured.update(kwargs)
        return _Facade(runtime, expected_scope_ref=kwargs["expected_scope_ref"])

    _service_account_module = SimpleNamespace(ServiceAccountClient=create_facade)

    monkeypatch.setattr(
        read_client_module, "_service_account_module", lambda: _service_account_module
    )
    session = SdkServiceReadSession(
        lambda: runtime,
        _identity(),
        account_bindings={"account-a": _account_binding()},
    )
    session.start()

    original_maintain = runtime.maintain

    def renew_into_wrong_scope():
        original_maintain()
        runtime.view_scope_ref = "account-b-read-v1"
        runtime.view_scope = _account_scope("account-b")

    runtime.maintain = renew_into_wrong_scope
    with pytest.raises(ServiceReadUnavailableError) as caught:
        session.read_account("account-a")

    assert caught.value.code == "SCOPE_DENIED"
    assert captured["expected_scope_ref"] == "account-a-read-v1"
    assert runtime.calls == []
    assert runtime.maintain is renew_into_wrong_scope
    session.close()


def test_mismatched_runtime_identity_fails_before_registration_and_closes():
    runtime = _Runtime(_identity("other-application"))

    with pytest.raises(ServiceReadSessionError) as caught:
        SdkServiceReadSession(
            lambda: runtime,
            _identity(),
            account_bindings={"account-a": _account_binding()},
        )

    assert caught.value.code == "SERVICE_READ_IDENTITY_MISMATCH"
    assert runtime.state == "closed"
    assert runtime.close_calls == 1


def test_missing_bindings_do_not_construct_a_runtime():
    factory_calls = 0

    def runtime_factory():
        nonlocal factory_calls
        factory_calls += 1
        return _Runtime()

    with pytest.raises(ServiceReadSessionError) as caught:
        SdkServiceReadSession(
            runtime_factory,
            _identity(),
            account_bindings={},
        )

    assert caught.value.code == "SERVICE_READ_NOT_CONFIGURED"
    assert factory_calls == 0


def test_registered_scope_mismatch_fails_start_without_read_rpc():
    runtime = _Runtime()
    runtime.bindings[0] = _registered(
        "application.account",
        "other-account-scope",
        "account.snapshot",
        _account_scope(),
    )
    session = SdkServiceReadSession(
        lambda: runtime,
        _identity(),
        account_bindings={"account-a": _account_binding()},
    )

    with pytest.raises(ServiceReadSessionError) as caught:
        session.start()

    assert caught.value.code == "SERVICE_READ_BINDING_MISMATCH"
    assert runtime.calls == []
    session.close()


def test_client_close_attempts_every_facade_and_retains_only_failed_one():
    runtime = _Runtime()
    client = AuthorizedServiceReadClient(
        runtime, account_bindings={"account-a": _account_binding()}
    )
    failed = _Facade(_Runtime(), fail_close=True)
    succeeded = _Facade(_Runtime())
    client._account_clients.update({"failed": failed, "succeeded": succeeded})

    with pytest.raises(ServiceReadClientCloseError) as caught:
        client.close()

    assert failed.close_calls == succeeded.close_calls == 1
    assert client._account_clients == {"failed": failed}
    assert caught.value.failures[0] is client.close_failures[0]
    with pytest.raises(ServiceReadUnavailableError) as closed:
        client.read_order("scope", "intent-1")
    assert closed.value.code == "SERVICE_READ_CLOSED"

    failed.fail_close = False
    client.close()
    assert failed.close_calls == 2
    assert client._account_clients == {}
    assert runtime.close_calls == 0


def test_session_close_reports_runtime_uncertainty_and_blocks_future_reads():
    runtime = _Runtime()
    session = SdkServiceReadSession(
        lambda: runtime,
        _identity(),
        account_bindings={"account-a": _account_binding()},
    )
    session.start()
    runtime.cleanup_failures = 1
    runtime.unregister_uncertainties = 2

    with pytest.raises(ServiceReadSessionError) as caught:
        session.close()

    assert caught.value.code == "SERVICE_READ_CLOSE_FAILED"
    assert not session.close_succeeded
    assert session.cleanup_failures == 1
    assert session.unregister_uncertainties == 2
    assert any(failure.component == "runtime_uncertainty" for failure in session.close_failures)
    with pytest.raises(ServiceReadUnavailableError) as closed:
        session.read_account("account-a")
    assert closed.value.code == "SERVICE_READ_CLOSED"
