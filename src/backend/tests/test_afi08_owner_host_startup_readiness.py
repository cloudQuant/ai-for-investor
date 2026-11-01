from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest


def test_owner_host_start_error_is_not_readiness_and_owned_resource_is_closed(
    monkeypatch, tmp_path
) -> None:
    owner_test = importlib.import_module("tests.test_afi08_owner_freeze_control_http")
    hosts = []
    setup_resources = {"owner": None}

    class FailingServiceHost:
        def __init__(self, config, authority, _registry_path, resource_provider):
            self.config = config
            self.authority = authority
            self.resource_provider = resource_provider
            self.state = "created"
            self.resources = None
            self.close_calls = 0
            hosts.append(self)

        def start(self):
            self.resources = self.resource_provider(
                "monitor",
                owner_test._SERVICE_INSTANCE,
                {},
                self.authority.scope,
            )
            self.state = "starting"
            raise RuntimeError("synthetic owner host startup fault")

        def close(self):
            self.close_calls += 1
            if self.resources is not None:
                self.resources.close()
            self.state = "closed"

    monkeypatch.setattr(owner_test, "ServiceHost", FailingServiceHost)

    with pytest.raises(AssertionError, match="RuntimeError"):
        owner_test._start_owner_host(
            tmp_path,
            subject="operator:afi08-readiness-test",
            afi_account_id="afi08-account-readiness-test",
            risk_account_id="risk-account-readiness-test",
            owner_action=owner_test.ControlAction.STOP_NEW,
            setup_resources=setup_resources,
        )

    assert len(hosts) == 1
    assert hosts[0].resources is not None
    assert hosts[0].close_calls == 1
    assert hosts[0].state == "closed"
    owned = setup_resources["owner"]
    assert owned is not None
    _module, thread, _stopped, refs = owned
    assert not thread.is_alive()
    assert refs["host"] is hosts[0]
    setup_resources["owner"] = None


def test_owner_constructor_failure_is_released_without_reading_empty_result_queue(
    monkeypatch, tmp_path
) -> None:
    owner_test = importlib.import_module("tests.test_afi08_owner_freeze_control_http")
    integration_test = importlib.import_module(
        "tests.integration.test_strategy_process_stop_http_integration"
    )
    setup_resources = {
        "owner": None,
        "execution": None,
        "legacy_registered": False,
        "legacy_token": None,
        "module_names": [],
        "plugin_root": None,
        "strategy_process": None,
        "strategy_process_lookup": None,
        "manager": None,
        "instance_id": None,
    }

    class FailingServiceHost:
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError("synthetic constructor failure")

    monkeypatch.setattr(owner_test, "ServiceHost", FailingServiceHost)

    def unexpected_close(*_args):
        pytest.fail("a Host that was never constructed must not be closed")

    monkeypatch.setattr(owner_test, "close_owner_host_thread", unexpected_close)
    with pytest.raises(AssertionError, match="RuntimeError"):
        owner_test._start_owner_host(
            tmp_path,
            subject="operator:afi08-constructor-failure",
            afi_account_id="afi08-account-constructor-failure",
            risk_account_id="risk-account-constructor-failure",
            owner_action=owner_test.ControlAction.STOP_NEW,
            setup_resources=setup_resources,
        )

    owned = setup_resources["owner"]
    assert owned is not None
    _selected_owner_test, thread, _stopped, refs = owned
    assert not thread.is_alive()
    assert refs.get("host") is None
    assert refs["_owner_startup_result"][2] == ("not_created", None)

    cleanup = integration_test._cleanup_setup_resources(setup_resources)
    assert cleanup["released"] is True
    assert cleanup["errors"] == ()
    assert cleanup["actions"]["owner"] == "startup_failed_before_host_creation"
    assert setup_resources["owner"] is None


class _FakeConnection:
    def __init__(self) -> None:
        self.closed = False
        self.sent = []

    def send(self, value) -> None:
        self.sent.append(value)

    def close(self) -> None:
        self.closed = True


class _FakeThread:
    def __init__(self, *, alive: bool) -> None:
        self.ident = 123 if alive else None
        self.alive = alive
        self.join_calls = 0

    def is_alive(self) -> bool:
        return self.alive

    def join(self, _timeout=None) -> None:
        self.join_calls += 1


class _FakeExecutionFixture:
    def __init__(self, *, receive_error: bool) -> None:
        self._ACCOUNT = "temporary-account"
        self._STRATEGY = "temporary-strategy"
        self._SCOPE = "temporary-scope"
        self.receive_error = receive_error
        self.receive_calls = 0

    def _receive(self, _pipe, *, timeout):
        self.receive_calls += 1
        assert timeout == 20.0
        if self.receive_error:
            raise TimeoutError("synthetic close response timeout")
        return ("closed", "closed")


def _execution_host_fixture(integration_test, *, thread, receive_error=True):
    parent = _FakeConnection()
    child = _FakeConnection()
    fixture = _FakeExecutionFixture(receive_error=receive_error)
    previous = {
        "_ACCOUNT": "original-account",
        "_STRATEGY": "original-strategy",
        "_SCOPE": "original-scope",
    }
    host = {
        "pipe": parent,
        "child_pipe": child,
        "thread": thread,
        "module_globals": previous,
        "fixture": fixture,
        "ready_received": True,
        "startup_reply": ("ready", "endpoint"),
        "thread_started": True,
        "close_command_sent": False,
        "module_globals_restored": False,
        "released": False,
    }
    root = {"execution": host}
    host["custody_root"] = root
    return root, host, parent, child, fixture, previous


def test_execution_host_keeps_pipes_and_fixture_globals_while_thread_is_live() -> None:
    integration_test = importlib.import_module(
        "tests.integration.test_strategy_process_stop_http_integration"
    )
    thread = _FakeThread(alive=True)
    root, host, parent, child, fixture, previous = _execution_host_fixture(
        integration_test, thread=thread
    )
    result = integration_test._close_execution_host(host)

    assert result["thread_alive"] is True
    assert result["released"] is False
    assert parent.closed is False
    assert child.closed is False
    assert fixture._ACCOUNT == "temporary-account"
    assert fixture._STRATEGY == "temporary-strategy"
    assert fixture._SCOPE == "temporary-scope"
    assert host["module_globals"] is previous
    assert integration_test._UNCERTAIN_STOP_TEST_RESOURCE_SETS[-1] is root

    # Resolve this fake custody locally so the unit does not leave retained state.
    thread.alive = False
    result = integration_test._close_execution_host(host)
    assert result["released"] is True
    assert parent.closed is True
    assert child.closed is True
    assert fixture._ACCOUNT == previous["_ACCOUNT"]
    assert fixture._STRATEGY == previous["_STRATEGY"]
    assert fixture._SCOPE == previous["_SCOPE"]
    assert not any(item is root for item in integration_test._UNCERTAIN_STOP_TEST_RESOURCE_SETS)


def test_execution_host_state_is_registered_before_thread_start_can_fail(
    monkeypatch, tmp_path
) -> None:
    integration_test = importlib.import_module(
        "tests.integration.test_strategy_process_stop_http_integration"
    )
    parent = _FakeConnection()
    child = _FakeConnection()

    class FakeScope:
        def __init__(self, domain, *, account_ref, strategy_ref):
            self.domain = domain
            self.account_ref = account_ref
            self.strategy_ref = strategy_ref

    class FailingThread:
        def __init__(self, *, target, args, name, daemon):
            self.target = target
            self.args = args
            self.name = name
            self.daemon = daemon
            self.ident = None
            self.alive = False
            self.join_calls = 0

        def start(self):
            self.ident = 123
            self.alive = True
            raise RuntimeError("synthetic thread start uncertainty")

        def is_alive(self):
            return self.alive

        def join(self, _timeout=None):
            self.join_calls += 1

    class Fixture(_FakeExecutionFixture):
        _DOMAIN = "accepted-synthetic-domain"
        _SCOPE = FakeScope("original-domain", account_ref="old-account", strategy_ref="old")

        def __init__(self):
            super().__init__(receive_error=True)
            self._SCOPE = FakeScope(
                "original-domain", account_ref="old-account", strategy_ref="old"
            )
            self.zmq = SimpleNamespace(curve_keypair=lambda: (b"public", b"secret"))

        @staticmethod
        def _endpoint():
            return "inproc://afi08-start-readiness"

        @staticmethod
        def _service_config(_endpoint):
            return object()

        @staticmethod
        def _host_process(*_args):
            raise AssertionError("fake Host thread must not execute")

    class Context:
        @staticmethod
        def Pipe(*, duplex):
            assert duplex is True
            return parent, child

    fixture = Fixture()
    previous = (fixture._ACCOUNT, fixture._STRATEGY, fixture._SCOPE)
    setup_resources = {"execution": None}
    monkeypatch.setattr(integration_test.multiprocessing, "get_context", lambda _name: Context())
    monkeypatch.setattr(integration_test, "threading", SimpleNamespace(Thread=FailingThread))

    with pytest.raises(AssertionError, match="RuntimeError"):
        integration_test._start_execution_host(
            fixture,
            tmp_path,
            account_ref="risk-account-start-failure",
            strategy_ref="strategy-start-failure",
            setup_resources=setup_resources,
        )

    host = setup_resources["execution"]
    assert host is not None
    assert host["thread"].alive is True
    assert host["close_command_sent"] is True
    assert parent.closed is False
    assert child.closed is False
    assert fixture._ACCOUNT == "risk-account-start-failure"
    assert fixture._STRATEGY == "strategy-start-failure"
    assert integration_test._UNCERTAIN_STOP_TEST_RESOURCE_SETS[-1] is setup_resources

    host["thread"].alive = False
    result = integration_test._close_execution_host(host)
    assert result["released"] is True
    assert parent.closed is True
    assert child.closed is True
    assert (fixture._ACCOUNT, fixture._STRATEGY, fixture._SCOPE) == previous
    assert not any(
        item is setup_resources for item in integration_test._UNCERTAIN_STOP_TEST_RESOURCE_SETS
    )


def test_setup_cleanup_attempts_independent_resources_and_retains_uncertain_host(
    monkeypatch, tmp_path
) -> None:
    integration_test = importlib.import_module(
        "tests.integration.test_strategy_process_stop_http_integration"
    )
    thread = _FakeThread(alive=True)
    root, host, _parent, _child, _fixture, _previous = _execution_host_fixture(
        integration_test, thread=thread
    )
    owner_thread = _FakeThread(alive=True)
    owner_stopped = type("Stopped", (), {"set": lambda self: None})()
    owner_refs = {}
    close_owner_calls = []

    def fail_owner_close(*_args):
        close_owner_calls.append("called")
        raise RuntimeError("synthetic owner close uncertainty")

    owner_test = type("OwnerTest", (), {"close_owner_host_thread": staticmethod(fail_owner_close)})
    owner = (owner_test, owner_thread, owner_stopped, owner_refs)
    token = object()
    unregister_calls = []
    module_name = f"afi08_cleanup_retained_{id(root)}"
    monkeypatch.setitem(sys.modules, module_name, object())
    plugin_root = tmp_path / "retained-plugin-path"
    sys.path.insert(0, str(plugin_root))
    monkeypatch.setattr(
        integration_test,
        "unregister_legacy_gateway_exclusions",
        lambda value: unregister_calls.append(value),
    )
    real_close_execution_host = integration_test._close_execution_host

    def fail_execution_close(*_args, **_kwargs):
        raise RuntimeError("synthetic execution close uncertainty")

    monkeypatch.setattr(integration_test, "_close_execution_host", fail_execution_close)
    setup_resources = {
        "owner": owner,
        "execution": host,
        "legacy_token": token,
        "legacy_registered": True,
        "plugin_root": plugin_root,
        "module_names": [module_name],
        "strategy_process": None,
        "strategy_process_lookup": None,
        "manager": None,
        "instance_id": None,
    }
    host["custody_root"] = setup_resources

    result = integration_test._cleanup_setup_resources(setup_resources)

    assert result["released"] is False
    assert close_owner_calls == ["called"]
    assert unregister_calls == []
    assert setup_resources["execution"] is host
    assert setup_resources["owner"] is owner
    assert setup_resources["legacy_registered"] is True
    assert setup_resources["legacy_token"] is token
    assert module_name in sys.modules
    assert str(plugin_root) in sys.path
    assert integration_test._UNCERTAIN_STOP_TEST_RESOURCE_SETS[-1] is setup_resources

    # Confirmed fake exits allow an orderly second cleanup and avoid leaking test state.
    monkeypatch.setattr(integration_test, "_close_execution_host", real_close_execution_host)
    thread.alive = False
    owner_thread.alive = False
    owner_refs["_owner_close_result"] = ("closed", "closed")
    owner_test.close_owner_host_thread = staticmethod(lambda *_args: None)
    result = integration_test._cleanup_setup_resources(setup_resources)
    assert result["released"] is True
    assert unregister_calls == [token]
    assert setup_resources["legacy_registered"] is False
    assert setup_resources["legacy_token"] is None
    assert module_name not in sys.modules
    assert str(plugin_root) not in sys.path
    assert not any(
        item is setup_resources for item in integration_test._UNCERTAIN_STOP_TEST_RESOURCE_SETS
    )
