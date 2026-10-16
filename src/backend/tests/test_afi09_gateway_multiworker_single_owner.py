"""Local synthetic evidence for one Gateway owner behind multiple AFI clients."""

from __future__ import annotations

import asyncio
import json
import multiprocessing
from contextlib import suppress
from pathlib import Path
from typing import Any


def _service_read_profile(
    integration: Any,
    *,
    endpoint: str,
    app_public: bytes,
    app_secret: bytes,
    server_public: bytes,
    account_key: Any,
    account_ref: str,
    service_id: str,
    instance_id: str,
    client_scope_ref: str,
    transport_ref: str,
    security_ref: str,
) -> dict[str, Any]:
    from bt_api_base.account_protocol import AccountResourceKey

    identity = integration._DUAL_LIVE_APPLICATION_IDENTITY
    return {
        "subject": integration._SUBJECT_A,
        "identity": {
            "principal_ref": identity.principal_ref,
            "actor_ref": identity.actor_ref,
            "delegate_ref": identity.delegate_ref,
        },
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": identity.actor_ref},
            "clients": {
                "gateway": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "application.account",
                                "service_id": service_id,
                                "instance_id": instance_id,
                                "scope_ref": client_scope_ref,
                                "transport_ref": transport_ref,
                                "account_ref": account_ref,
                            }
                        ],
                        "options": {
                            "request_timeout_ms": integration._REQUEST_TIMEOUT_MS
                        },
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    transport_ref: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": security_ref,
                        "options": {
                            "high_water_mark": 32,
                            "max_message_bytes": integration._MAX_MESSAGE_BYTES,
                        },
                    }
                },
            },
        },
        "scope_claims": {
            client_scope_ref: {
                "execution_domain_ref": integration._DUAL_LIVE_DOMAIN,
                "account_ref": account_ref,
            }
        },
        "peer_identities": {
            service_id: {
                "principal_ref": f"{service_id}-principal",
                "actor_ref": service_id,
            }
        },
        "curve_keys": {
            security_ref: {
                "server_key": server_public.decode("ascii"),
                "public_key": app_public.decode("ascii"),
                "secret_key": app_secret.decode("ascii"),
            }
        },
        "grants": {
            "account_refs": [account_ref],
            "order_scope_refs": [],
            "monitor_scope_refs": [],
        },
        "account_bindings": {
            account_ref: {
                "mount": "application.account",
                "scope_ref": client_scope_ref,
                "currency": "USDT",
                "account_key": account_key.to_dict(),
                "coverage": [
                    AccountResourceKey("spot", "cash").to_dict()
                ],
                "require_open_orders": False,
            }
        },
        "order_bindings": {},
        "monitor_bindings": {},
        "worker": {"maintenance_interval_seconds": 60},
    }


def _afi09_session_owner_gateway_process(
    control: Any,
    raw_config: dict[str, Any],
    registry_path: str,
    journal_path: str,
    guard_directory: str,
    account_ref: str,
    client_scope_ref: str,
    account_key_values: dict[str, Any],
    service_keys: dict[str, bytes],
    session_credential_refs: dict[str, str],
    account_operations: frozenset[str],
) -> None:
    """Spawn target: actual ServiceHost owner resolves one synthetic secret ref."""

    from pathlib import Path

    from bt_api_base.account_protocol import AccountKey, AccountResourceKey
    from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
    from bt_api_gateway import GatewayEventJournal
    from bt_api_gateway.router import GatewayCommandKind, GatewayPrincipal
    from bt_api_gateway.service_component import GatewayServiceAccountScope
    from bt_api_gateway.session_guard import LocalAccountSessionGuard
    from bt_api_gateway.session_owner import GatewaySessionOwner
    from bt_api_py.gateway_operator import (
        GatewayAccountSessionBinding,
        GatewayOperatorDeployment,
    )
    from bt_api_py.service_config import parse_service_config
    from bt_api_py.service_host import TrustedServiceAuthority
    from bt_api_py.service_registry import PrincipalGrant, ResourceGrant

    from tests import test_service_read_authorized_http_integration as integration

    config = parse_service_config(raw_config)
    account_key = AccountKey.from_dict(account_key_values)
    journal = GatewayEventJournal(journal_path)
    session_ref, credential_ref = next(iter(session_credential_refs.items()))
    secret_resolution_calls = 0
    provider_factory_calls = 0
    synthetic_credential = "AFI09-LOCAL-SYNTHETIC-SECRET"
    provider = None

    def resolve_credential(requested_ref: str) -> object:
        nonlocal secret_resolution_calls
        if requested_ref != credential_ref:
            raise RuntimeError(synthetic_credential)
        secret_resolution_calls += 1
        return synthetic_credential

    def provider_factory(requested_session_ref: str, credential: object) -> Any:
        nonlocal provider_factory_calls, provider
        if requested_session_ref != session_ref or credential != synthetic_credential:
            raise RuntimeError(synthetic_credential)
        provider_factory_calls += 1
        provider = integration._DualLiveSyntheticAccountProvider(account_key, account_ref)
        return provider

    session_owner = GatewaySessionOwner(
        session_credential_refs,
        resolve_credential=resolve_credential,
        provider_factory=provider_factory,
    )
    journal_scope = f"afi09-session-owner-journal:{account_ref}"
    state_scope = f"afi09-session-owner-state:{account_ref}"
    account_scope = GatewayServiceAccountScope(
        account_ref=account_ref,
        execution_domain_ref=integration._DUAL_LIVE_DOMAIN,
        journal_account_scope=journal_scope,
        account_read_strategy_scope=state_scope,
        shared_account_facts_scope=state_scope,
    )
    principal = GatewayPrincipal(
        principal_id=integration._DUAL_LIVE_PRINCIPAL,
        account_scopes=frozenset({journal_scope}),
        strategy_scopes=frozenset({state_scope}),
        allowed_kinds=frozenset({GatewayCommandKind.READ}),
    )
    def resource_provider(component: str, _instance_id: str, _options: Any, _scope: Any):
        raise AssertionError(f"unexpected non-Gateway AFI09 resource request: {component}")

    account_binding = GatewayAccountSessionBinding(
        account_session_ref=session_ref,
        journal=journal,
        account_key=account_key,
        account_scope=account_scope,
        state_scope=state_scope,
        guard=LocalAccountSessionGuard(
            Path(guard_directory),
            account_key.account_key_id,
            owner_ref=f"afi09-{account_ref}",
        ),
        required_coverage=(AccountResourceKey("spot", "cash"),),
        principals={integration._DUAL_LIVE_PRINCIPAL: principal},
        refresh_interval_seconds=3600,
        max_staleness_seconds=7200,
        request_timeout_seconds=2,
    )

    identity = integration._DUAL_LIVE_APPLICATION_IDENTITY
    app_grant = ResourceGrant(
        config.components["gateway"]["settings"]["instance_id"],
        "service.account_read",
        client_scope_ref,
        WireScope(integration._DUAL_LIVE_DOMAIN, account_ref=account_ref),
        account_operations,
    )
    deployment = None
    try:
        authority = TrustedServiceAuthority(
            identity=WireIdentity(
                WireRole.SERVICE, f"{config.service_id}-principal", config.service_id
            ),
            scope=WireScope(integration._DUAL_LIVE_DOMAIN),
            scope_ref=config.scope_ref,
            scope_version=f"{account_ref}-afi09-scope-v1",
            security_ref=service_keys["security_ref"],
            security_version="curve-key-v1",
            registration_policy_ref=config.registration_policy_ref,
            registration_policy_version=f"{account_ref}-afi09-policy-v1",
            service_requirements_ref=config.service_requirements_ref,
            service_requirements_version=f"{account_ref}-afi09-requirements-v1",
            curve_public_key=service_keys["server_public"],
            curve_secret_key=service_keys["server_secret"],
            principals={
                service_keys["application_public"]: integration._DUAL_LIVE_PRINCIPAL
            },
            grants={
                integration._DUAL_LIVE_PRINCIPAL: (
                    PrincipalGrant(identity, (app_grant,)),
                )
            },
        )
        deployment = GatewayOperatorDeployment(
            config,
            authority,
            registry_path,
            resource_provider=resource_provider,
            session_owner=session_owner,
            account_session=account_binding,
        )
        deployment.start()
        status = deployment.account_session_status
        control.send(
            (
                "ready",
                deployment.endpoint,
                deployment.state,
                {
                    "worker_state": status["state"],
                    "worker_ready": status["ready"],
                    "session_generation": status["session_generation"],
                    "provider_connect_calls": provider.connect_calls,
                    "provider_read_calls": provider.read_calls,
                    "provider_close_calls": provider.close_calls,
                    "secret_resolution_calls": secret_resolution_calls,
                    "provider_factory_calls": provider_factory_calls,
                    "claimed_session_count": session_owner.claimed_session_count,
                    "account_key_id": account_key.account_key_id,
                },
            )
        )
        while True:
            deployment.serve_once(timeout_ms=10)
            if not control.poll():
                continue
            command = control.recv()
            if command == ("recover",):
                old_generation = deployment.account_session_status["session_generation"]
                status = deployment.recover_account_session()
                control.send(
                    (
                        "recovered",
                        old_generation,
                        status["session_generation"],
                        status["ready"],
                        provider.connect_calls,
                        provider.read_calls,
                        provider.close_calls,
                        secret_resolution_calls,
                        provider_factory_calls,
                        session_owner.claimed_session_count,
                    )
                )
                continue
            if command == ("status",):
                status = deployment.account_session_status
                control.send(
                    (
                        "status",
                        provider.connect_calls,
                        provider.read_calls,
                        provider.close_calls,
                        secret_resolution_calls,
                        provider_factory_calls,
                        session_owner.claimed_session_count,
                        status["ready"],
                    )
                )
                continue
            if command == ("close",):
                deployment.close()
                control.send(
                    (
                        "closed",
                        deployment.state,
                        provider.connect_calls,
                        provider.read_calls,
                        provider.close_calls,
                        secret_resolution_calls,
                        provider_factory_calls,
                        session_owner.claimed_session_count,
                        deployment.account_session_status["state"],
                    )
                )
                return
            raise AssertionError("unknown AFI09 synthetic owner command")
    except BaseException as error:
        if deployment is not None and deployment.state not in {"closed", "failed"}:
            with suppress(BaseException):
                deployment.close()
        with suppress(Exception):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def _afi09_gateway_health_api_process(
    control: Any,
    deployment_json: str,
    subject: str,
    port: int,
) -> None:
    """Spawn target: real HTTP and WebSocket routers over an SDK read worker."""

    import asyncio
    import os
    from types import SimpleNamespace

    from tests import test_service_read_authorized_http_integration as integration

    # The test fixture established the app's real JWT settings without reading
    # repository dotenv files. Keep only its explicitly synthetic settings in
    # this child before importing the application modules.
    os.environ.update(integration._SYNTHETIC_ENV)

    import uvicorn
    from fastapi import FastAPI
    from pydantic import SecretStr

    from app.api.service_gateway import router as gateway_router
    from app.api.service_gateway_ws import router as gateway_ws_router
    from app.api.service_read import configure_service_read
    from app.db.database import get_db
    from app.models.user import User
    from app.services.service_read.deployment import start_service_read_deployment

    class SyntheticOwnerDatabase:
        async def get(self, model: type[Any], requested_subject: str) -> Any:
            if model is not User or requested_subject != subject:
                return None
            return SimpleNamespace(
                id=subject,
                is_active=True,
                principal_kind="HUMAN",
            )

    async def run_api() -> None:
        deployment = None
        server_task = None
        server = None
        app = FastAPI()
        database = SyntheticOwnerDatabase()

        async def database_dependency() -> SyntheticOwnerDatabase:
            return database

        app.dependency_overrides[get_db] = database_dependency
        app.include_router(gateway_router, prefix="/api/v1")
        app.include_router(gateway_ws_router, prefix="/api/v1")

        try:
            deployment = await start_service_read_deployment(SecretStr(deployment_json))
            if deployment is None:
                raise RuntimeError("synthetic ServiceRead deployment unavailable")
            configure_service_read(deployment.directory)
            server = uvicorn.Server(
                uvicorn.Config(
                    app,
                    host="127.0.0.1",
                    port=port,
                    log_level="critical",
                    access_log=False,
                    lifespan="off",
                )
            )
            server_task = asyncio.create_task(server.serve())
            deadline = asyncio.get_running_loop().time() + 20.0
            while not server.started:
                if server_task.done():
                    await server_task
                    raise RuntimeError("synthetic HTTP server did not start")
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("synthetic HTTP server startup timed out")
                await asyncio.sleep(0.02)
            control.send(("ready", os.getpid(), port))
            while not control.poll():
                if server_task.done():
                    await server_task
                    raise RuntimeError("synthetic HTTP server stopped unexpectedly")
                await asyncio.sleep(0.02)
            if control.recv() != ("close",):
                raise AssertionError("unknown synthetic API lifecycle command")
        finally:
            if server is not None:
                server.should_exit = True
            if server_task is not None:
                await asyncio.gather(server_task, return_exceptions=True)
            configure_service_read(None)
            close_code = "closed"
            if deployment is not None:
                try:
                    await deployment.aclose()
                except BaseException as error:
                    close_code = getattr(error, "code", type(error).__name__)
            control.send(("closed", os.getpid(), close_code))

    try:
        asyncio.run(run_api())
    except BaseException as error:
        with suppress(BaseException):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def _afi09_service_read_client_process(
    control: Any,
    deployment_json: str,
    account_ref: str,
    subject: str,
    forbidden_public_values: tuple[str, ...],
) -> None:
    """Spawn target: one independent AFI process with one authorized worker."""

    import importlib
    import os

    from pydantic import SecretStr

    # This fixture establishes isolated, synthetic app settings before the
    # real AFI service-read deployment imports application configuration.
    # The fixture import establishes synthetic settings before application config.
    integration = importlib.import_module("tests.test_service_read_authorized_http_integration")

    from types import SimpleNamespace

    import httpx
    from fastapi import FastAPI

    from app.api.service_gateway import router as service_gateway_router
    from app.api.service_read import configure_service_read
    from app.db.database import get_db
    from app.models.user import User
    from app.services.service_read.deployment import start_service_read_deployment

    def receive_command() -> Any:
        if not control.poll(30.0):
            raise TimeoutError("AFI09 synthetic client command timed out")
        return control.recv()

    async def run_client() -> None:
        deployment = None
        try:
            deployment = await start_service_read_deployment(SecretStr(deployment_json))
            if deployment is None:
                raise RuntimeError("synthetic service-read deployment unavailable")
            configure_service_read(deployment.directory)

            class Database:
                async def get(self, model: type[Any], requested_subject: str) -> Any:
                    if model is not User or requested_subject != subject:
                        return None
                    return SimpleNamespace(
                        id=subject, is_active=True, principal_kind="HUMAN"
                    )

            database = Database()

            async def database_dependency():
                yield database

            app = FastAPI()
            app.include_router(service_gateway_router, prefix="/api/v1")
            app.dependency_overrides[get_db] = database_dependency
            token = integration._make_token(subject, integration._JWT_SECRET)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://afi09-session-owner.synthetic.test",
            ) as api_client:

                async def project_health() -> tuple[Any, ...]:
                    response = await api_client.get(
                        f"/api/v1/service-gateway/accounts/{account_ref}/health",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if response.status_code != 200:
                        raise AssertionError("synthetic Gateway health API request failed")
                    payload = response.json()
                    assert payload["service_connection"]["rpc_status"] == "reachable"
                    assert payload["market_data_feed"]["status"] == "unobserved"
                    assert integration._SYNTHETIC_ENV["SECRET_KEY"] not in response.text
                    assert all(value not in response.text for value in forbidden_public_values)
                    return (
                        payload["gateway_session"]["status"],
                        payload["gateway_session"]["session_generation"],
                        payload["account_observation"]["quality"],
                        payload["account_observation"]["same_session_generation"],
                    )

                control.send(("ready", os.getpid(), *await project_health()))
                while True:
                    command = await asyncio.to_thread(receive_command)
                    if command == ("read",):
                        control.send(("health", os.getpid(), *await project_health()))
                        continue
                    if command == ("close",):
                        await deployment.aclose()
                        configure_service_read(None)
                        control.send(("closed", os.getpid()))
                        return
                    raise AssertionError("unknown AFI09 client command")
        finally:
            configure_service_read(None)
            if deployment is not None and not deployment.closed:
                await deployment.aclose()

    try:
        asyncio.run(run_client())
    except BaseException as error:
        with suppress(BaseException):
            control.send(("error", getattr(error, "code", type(error).__name__)))
        raise
    finally:
        control.close()


def test_afi09_two_service_read_workers_share_one_gateway_owner(tmp_path: Path) -> None:
    """Two separate AFI client workers read one real synthetic Gateway owner."""

    import pytest

    pytest.importorskip("bt_api_py")
    pytest.importorskip("bt_api_gateway")
    pytest.importorskip("zmq")

    # The service process uses the production GatewayOperatorDeployment
    # composition. Separate AFI deployments remain clients and cannot invoke
    # its credential resolver.
    from bt_api_base.account_protocol import AccountKey

    from tests import test_service_read_authorized_http_integration as integration

    account_ref = integration._ACCOUNT_A
    account_key = AccountKey(
        "PAPER", "synthetic-venue", "simulation", "afi-multiworker-owner"
    )
    app_public, app_secret = integration.zmq.curve_keypair()
    server_public, server_secret = integration.zmq.curve_keypair()
    endpoint = integration._order._endpoint()
    service_id = "afi09-multiworker-gateway-service"
    instance_id = "afi09-multiworker-gateway-instance"
    service_scope_ref = "afi09-multiworker-gateway-v1"
    transport_ref = "afi09-multiworker-gateway-connect-v1"
    security_ref = "afi09-multiworker-gateway-curve-v1"
    client_scope_ref = "afi09-multiworker-account-read-v1"
    raw_service_config = integration._dual_gateway_service_config(
        endpoint,
        account_ref,
        service_id,
        instance_id,
        service_scope_ref,
        "afi09-multiworker-gateway-listen-v1",
        security_ref,
    )
    session_ref = raw_service_config["components"]["gateway"]["settings"]["options"][
        "account_session_ref"
    ]
    credential_ref = "afi09-synthetic-vault://gateway/account-a"

    root = tmp_path / "afi09-multiworker-single-owner"
    root.mkdir()
    guard_directory = root / "session-guard"
    guard_directory.mkdir()
    host = integration._order._start_process(
        multiprocessing.get_context("spawn"),
        _afi09_session_owner_gateway_process,
        (
            raw_service_config,
            str(root / "registry.sqlite3"),
            str(root / "journal.sqlite3"),
            str(guard_directory),
            account_ref,
            client_scope_ref,
            account_key.to_dict(),
            {
                "server_public": server_public,
                "server_secret": server_secret,
                "application_public": app_public,
                "security_ref": security_ref,
            },
            {session_ref: credential_ref},
            frozenset({"account.snapshot", "account.head"}),
        ),
        "afi09-one-gateway-owner-two-clients",
    )
    client_processes: list[dict[str, Any]] = []
    browser_api: dict[str, Any] | None = None
    close_reply: Any = None
    recovery_succeeded = False
    try:
        ready = integration._order._receive(host["pipe"], timeout=20.0)
        assert ready[0:3] == ("ready", endpoint, "started"), ready
        startup = ready[3]
        assert startup["worker_ready"] is True
        assert startup["provider_connect_calls"] == startup["provider_read_calls"] == 1
        assert startup["provider_close_calls"] == 0
        assert startup["secret_resolution_calls"] == startup["provider_factory_calls"] == 1
        assert startup["claimed_session_count"] == 1

        profile = _service_read_profile(
            integration,
            endpoint=endpoint,
            app_public=app_public,
            app_secret=app_secret,
            server_public=server_public,
            account_key=account_key,
            account_ref=account_ref,
            service_id=service_id,
            instance_id=instance_id,
            client_scope_ref=client_scope_ref,
            transport_ref=transport_ref,
            security_ref=security_ref,
        )
        deployment_json = json.dumps({"schema_version": 1, "subjects": [profile]})
        forbidden_public_values = (credential_ref, "AFI09-LOCAL-SYNTHETIC-SECRET")
        context = multiprocessing.get_context("spawn")
        import os

        if os.environ.get("AFI09_RUN_BROWSER_E2E") == "1":
            import shutil
            import socket
            import subprocess

            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                api_port = probe.getsockname()[1]
            browser_api = integration._order._start_process(
                context,
                _afi09_gateway_health_api_process,
                (deployment_json, integration._SUBJECT_A, api_port),
                "afi09-browser-health-api",
            )
            api_ready = integration._order._receive(browser_api["pipe"], timeout=30.0)
            assert api_ready[0] == "ready" and api_ready[2] == api_port, api_ready

            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                frontend_port = probe.getsockname()[1]
            frontend_root = Path(__file__).resolve().parents[1].parent / "frontend"
            node_executable = shutil.which("node")
            assert node_executable is not None, "Node.js is required for the AFI09 browser check"
            e2e_environment = dict(os.environ)
            isolated_vite_env = root / "empty-vite-env"
            isolated_vite_env.mkdir()
            e2e_environment.update(
                {
                    "AFI09_E2E_ACCESS_TOKEN": integration._make_token(
                        integration._SUBJECT_A, integration._JWT_SECRET
                    ),
                    "AFI09_E2E_ACCOUNT_REF": account_ref,
                    "AFI09_E2E_API_TARGET": f"http://127.0.0.1:{api_port}",
                    "AFI09_E2E_CREDENTIAL_REF": credential_ref,
                    "AFI09_E2E_ENV_DIR": str(isolated_vite_env),
                    "AFI09_E2E_FRONTEND_PORT": str(frontend_port),
                    "AFI09_E2E_SYNTHETIC_SECRET": forbidden_public_values[1],
                }
            )
            browser = subprocess.run(
                [
                    node_executable,
                    "node_modules/@playwright/test/cli.js",
                    "test",
                    "--config=e2e/afi09-gateway-health.config.ts",
                ],
                cwd=frontend_root,
                env=e2e_environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
                check=False,
            )
            browser_output = (browser.stdout or "") + (browser.stderr or "")
            browser_output_path = (
                Path(__file__).parent
                / ".codex-tmp"
                / "afi09-session-owner-local-qa-20261017"
                / "gateway-health-browser-final.txt"
            )
            browser_output_path.parent.mkdir(parents=True, exist_ok=True)
            browser_output_path.write_text(browser_output, encoding="utf-8")
            assert browser.returncode == 0, (
                f"AFI09 browser E2E failed; raw output saved at {browser_output_path}"
            )

            browser_api["pipe"].send(("close",))
            api_closed = integration._order._receive(browser_api["pipe"], timeout=30.0)
            browser_api["process"].join(timeout=30.0)
            assert api_closed[0] == "closed" and api_closed[2] == "closed", api_closed
            assert browser_api["process"].exitcode == 0
            browser_api = None

        for index in range(2):
            client_processes.append(
                integration._order._start_process(
                    context,
                    _afi09_service_read_client_process,
                    (
                        deployment_json,
                        account_ref,
                        integration._SUBJECT_A,
                        forbidden_public_values,
                    ),
                    f"afi09-independent-client-{index + 1}",
                )
            )
        initial = [
            integration._order._receive(client["pipe"], timeout=30.0)
            for client in client_processes
        ]
        assert all(reply[0] == "ready" for reply in initial), initial
        assert initial[0][1] != initial[1][1]
        assert initial[0][1] != host["process"].pid
        assert initial[1][1] != host["process"].pid
        assert all(reply[2] == "ready" for reply in initial)
        old_generation = initial[0][3]
        assert old_generation and initial[1][3] == old_generation
        assert all(reply[4:] == ("fresh", True) for reply in initial)

        host["pipe"].send(("status",))
        before_recovery = integration._order._receive(host["pipe"], timeout=5.0)
        assert before_recovery == ("status", 1, 1, 0, 1, 1, 1, True)

        host["pipe"].send(("recover",))
        recovered = integration._order._receive(host["pipe"], timeout=10.0)
        assert recovered[0] == "recovered", recovered
        assert recovered[1] == old_generation
        new_generation = recovered[2]
        assert new_generation and new_generation != old_generation
        assert recovered[3] is True
        assert recovered[4:10] == (2, 2, 1, 1, 1, 1)
        recovery_succeeded = True

        for client in client_processes:
            client["pipe"].send(("read",))
        after_recovery = [
            integration._order._receive(client["pipe"], timeout=15.0)
            for client in client_processes
        ]
        assert all(reply[0] == "health" for reply in after_recovery), after_recovery
        assert all(reply[2] == "ready" for reply in after_recovery)
        assert all(reply[3] == new_generation for reply in after_recovery)
        assert all(reply[4:] == ("fresh", True) for reply in after_recovery)
        assert all(app_secret.decode("ascii") not in str(reply) for reply in initial)
        assert all(server_secret.decode("ascii") not in str(reply) for reply in initial)
        assert all(app_secret.decode("ascii") not in str(reply) for reply in after_recovery)
        assert all(server_secret.decode("ascii") not in str(reply) for reply in after_recovery)

        # Replacing one independent AFI process must reuse the already-running
        # Gateway owner session rather than resolving or connecting a second
        # provider for the same account-session reference.
        original_client = client_processes[0]
        original_client_pid = original_client["process"].pid
        original_client["pipe"].send(("close",))
        original_close = integration._order._receive(original_client["pipe"], timeout=20.0)
        assert original_close == ("closed", original_client_pid)
        original_client["process"].join(timeout=20.0)
        assert original_client["process"].exitcode == 0
        client_processes.pop(0)

        restarted_client = integration._order._start_process(
            context,
            _afi09_service_read_client_process,
            (
                deployment_json,
                account_ref,
                integration._SUBJECT_A,
                forbidden_public_values,
            ),
            "afi09-restarted-client-same-gateway-owner",
        )
        client_processes.append(restarted_client)
        restarted = integration._order._receive(restarted_client["pipe"], timeout=30.0)
        assert restarted[0] == "ready", restarted
        assert restarted[1] != original_client_pid
        assert restarted[1] != host["process"].pid
        assert restarted[2:] == ("ready", new_generation, "fresh", True)

        host["pipe"].send(("status",))
        status_reply = integration._order._receive(host["pipe"], timeout=5.0)
        assert status_reply == ("status", 2, 2, 1, 1, 1, 1, True)
        for client in client_processes:
            client["pipe"].send(("close",))
        client_closes = [
            integration._order._receive(client["pipe"], timeout=20.0)
            for client in client_processes
        ]
        assert all(reply[0] == "closed" for reply in client_closes), client_closes
        for client in client_processes:
            client["process"].join(timeout=20.0)
            assert client["process"].exitcode == 0
    finally:
        if browser_api is not None:
            if browser_api["process"].is_alive():
                with suppress(BaseException):
                    browser_api["pipe"].send(("close",))
                    integration._order._receive(browser_api["pipe"], timeout=10.0)
                browser_api["process"].join(timeout=10.0)
        for client in client_processes:
            if client["process"].is_alive():
                with suppress(BaseException):
                    client["pipe"].send(("close",))
                    integration._order._receive(client["pipe"], timeout=10.0)
                client["process"].join(timeout=10.0)
        if host["process"].is_alive():
            with suppress(BaseException):
                host["pipe"].send(("close",))
                close_reply = integration._order._receive(host["pipe"], timeout=20.0)
            host["process"].join(timeout=20.0)
        assert close_reply is not None
        assert close_reply[0:2] == ("closed", "closed"), close_reply
        expected_lifecycle = (2, 2, 2, 1, 1, 1) if recovery_succeeded else (1, 1, 1, 1, 1, 1)
        assert close_reply[2:8] == expected_lifecycle, close_reply
        assert host["process"].exitcode == 0

