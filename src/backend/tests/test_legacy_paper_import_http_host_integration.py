"""A nonempty legacy Paper migration over HTTP and the trusted SDK Host path."""

from __future__ import annotations

import asyncio
import json
import queue
import socket
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import pytest
import zmq
from sqlalchemy import select

from app.api.deps import get_current_user
from app.api.service_read import configure_service_read
from app.db import database
from app.models.alerts import Alert, AlertNotification, AlertRule
from app.models.legacy_paper_import import LegacyPaperImportReceipt
from app.models.paper_runtime import PaperEquitySnapshot, RiskRule
from app.models.strategy_approval_authority import (
    StrategyApprovalAuthorityEpoch,
    StrategyOrderApprovalPolicyHead,
    StrategyOrderApprovalPolicyVersion,
)
from app.models.strategy_target_approval import StrategyTargetApproval, StrategyTargetApprovalEvent
from app.models.workspace import StrategyUnit, Workspace
from app.services.legacy_paper_migration import _model_row, inspect_stable_legacy_paper_account
from app.services.paper_trading_service import PaperTradingService
from app.services.paper_runtime_service import PaperRuntimeService
from app.services.service_read.access import ReadAccess, ServiceReadAccessDirectory
from app.services.service_read.client import PaperLegacyImportBinding, PaperSubmitBinding
from app.services.service_read.session import SdkServiceReadSession
from app.services.service_read.worker import ServiceReadWorker
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_execution import SqliteExecutionStore
from bt_api_execution.paper_legacy_import import LegacyPaperSymbolBindingV1
from bt_api_py.service_components import ComponentResources
from bt_api_py.service_config import parse_client_config, parse_service_config
from bt_api_py.service_host import ServiceHost, TrustedServiceAuthority
from bt_api_py.service_registry import PrincipalGrant, ResourceGrant
from bt_api_py.service_runtime import ClientCurveKeys, ServiceClientRuntime, ZmqTransportFactory

from tests import test_legacy_paper_import_migration as legacy


_SERVICE_ID = "afi12-http-host-service"
_SERVICE_PRINCIPAL = "afi12-http-host-service-principal"
_SERVICE_INSTANCE = "afi12-http-host-import-owner"
_SERVICE_SCOPE_REF = "afi12-http-host-service-scope-v1"
_SERVER_SECURITY_REF = "afi12-http-host-server-curve-v1"
_CLIENT_SECURITY_REF = "afi12-http-host-client-curve-v1"
_APPLICATION_ID = "afi12-http-host-application"
_SCOPE_REF = "afi12-http-host-import-scope-v1"
_MOUNT = "application.paper_legacy_import"
_PORT = "service.paper_legacy_import"
_OPERATIONS = frozenset(
    {
        "paper.import.status",
        "paper.import.inspect_source",
        "paper.import.prepare",
        "paper.import.activate",
        "paper.import.abort",
    }
)
_MAX_MESSAGE_BYTES = 65_536
_ALERT_RULE_ID = "afi12-alert-rule-v1"
_ALERT_ID = "afi12-alert-v1"
_ALERT_NOTIFICATION_ID = "afi12-alert-notification-v1"
_RISK_RULE_ID = "afi12-risk-rule-v1"
_APPROVAL_REF = "afi12-approval-v1"
_APPROVAL_EVENT_ID = "afi12-approval-event-v1"
_POLICY_REF = "afi12-order-policy-v1"
_POLICY_VERSION_ID = "afi12-policy-version-v1"
_AUTHORITY_EPOCH = 7
_SNAPSHOT_IDS = (
    "afi12-equity-snapshot-v1",
    "afi12-equity-snapshot-v2",
    "afi12-equity-snapshot-v3",
)
_WORKSPACE_ID = "afi12-paper-workspace-v1"
_UNIT_ID = "afi12-paper-unit-v1"
_HASH_A = "a" * 64
_HASH_B = "b" * 64
_HASH_C = "c" * 64


def _endpoint() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return f"tcp://127.0.0.1:{probe.getsockname()[1]}"


def _service_config(endpoint: str):
    return parse_service_config(
        {
            "service_config_schema_version": 1,
            "process_role": "service",
            "service_id": _SERVICE_ID,
            "scope_ref": _SERVICE_SCOPE_REF,
            "transport_ref": "afi12-http-host-listener-v1",
            "registration_policy_ref": "afi12-http-host-registration-v1",
            "service_requirements_ref": "afi12-http-host-requirements-v1",
            "components": {
                "execution": {
                    "config_schema_version": 2,
                    "settings": {
                        "instance_id": _SERVICE_INSTANCE,
                        "bind_ports": [_PORT],
                        "options": {"role": "legacy_import_owner"},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "afi12-http-host-listener-v1": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_bind": endpoint},
                        "security_profile_ref": _SERVER_SECURITY_REF,
                        "options": {
                            "high_water_mark": 32,
                            "max_message_bytes": _MAX_MESSAGE_BYTES,
                        },
                    }
                },
            },
        }
    )


def _client_config(endpoint: str):
    return parse_client_config(
        {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": _APPLICATION_ID},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": _MOUNT,
                                "service_id": _SERVICE_ID,
                                "instance_id": _SERVICE_INSTANCE,
                                "scope_ref": _SCOPE_REF,
                                "transport_ref": "afi12-http-host-connect-v1",
                                "account_ref": legacy._ACCOUNT_REF,
                            }
                        ],
                        "options": {"request_timeout_ms": 2_000},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    "afi12-http-host-connect-v1": {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": endpoint},
                        "security_profile_ref": _CLIENT_SECURITY_REF,
                        "options": {
                            "request_timeout_ms": 2_000,
                            "high_water_mark": 32,
                            "max_message_bytes": _MAX_MESSAGE_BYTES,
                        },
                    }
                },
            },
        }
    )


async def _seed_preserved_controls() -> None:
    async with database.async_session_maker() as session:
        async with session.begin():
            session.add(
                Workspace(
                    id=_WORKSPACE_ID,
                    user_id=legacy._SOURCE_OWNER_ID,
                    name="AFI12 legacy paper workspace",
                    workspace_type="trading",
                )
            )
            session.add(
                StrategyUnit(
                    id=_UNIT_ID,
                    workspace_id=_WORKSPACE_ID,
                    strategy_name="AFI12 legacy paper strategy",
                    symbol=legacy._LEGACY_SYMBOL,
                    trading_mode="paper",
                    trading_instance_id="afi12-paper-instance-v1",
                )
            )
            session.add_all(
                [
                    PaperEquitySnapshot(
                        id=snapshot_id,
                        user_id=legacy._SOURCE_OWNER_ID,
                        workspace_id=_WORKSPACE_ID,
                        unit_id=_UNIT_ID,
                        instance_id="afi12-paper-instance-v1",
                        paper_account_id=legacy._SOURCE_ACCOUNT_ID,
                        observed_at=datetime(2026, 10, 16, 12, index, tzinfo=timezone.utc),
                        source="mark_to_market",
                        total_equity=99.9 + index / 10,
                        cash=89.9 + index / 10,
                        position_value=10.0,
                        unrealized_pnl=0.0,
                        realized_pnl=-0.1,
                        metadata_json={"migration_fixture": "source-only"},
                    )
                    for index, snapshot_id in enumerate(_SNAPSHOT_IDS)
                ]
            )
            session.add(
                AlertRule(
                    id=_ALERT_RULE_ID,
                    user_id=legacy._SOURCE_OWNER_ID,
                    alert_type="risk",
                    severity="warning",
                    name="Legacy loss threshold",
                    description="Preserved, never activated by import",
                    trigger_type="threshold",
                    trigger_config={"max_loss": 5},
                    notification_enabled=True,
                    notification_channels=["email"],
                    is_active=True,
                    triggered_count=2,
                )
            )
            session.add(
                Alert(
                    id=_ALERT_ID,
                    user_id=legacy._SOURCE_OWNER_ID,
                    alert_type="risk",
                    severity="warning",
                    status="acknowledged",
                    title="Legacy drawdown alert",
                    message="Synthetic historical alert",
                    details={"source": "legacy"},
                    rule_id=_ALERT_RULE_ID,
                    account_id=legacy._SOURCE_ACCOUNT_ID,
                    position_id=legacy._POSITION_ID,
                    order_id=legacy._ORDER_ID,
                    trigger_type="threshold",
                    trigger_value=5.0,
                    threshold_value=4.0,
                    is_read=True,
                    is_notification_sent=True,
                )
            )
            session.add(
                AlertNotification(
                    id=_ALERT_NOTIFICATION_ID,
                    alert_id=_ALERT_ID,
                    channel="email",
                    status="sent",
                    message="Synthetic historical notification",
                )
            )
            session.add(
                RiskRule(
                    id=_RISK_RULE_ID,
                    user_id=legacy._SOURCE_OWNER_ID,
                    paper_account_id=legacy._SOURCE_ACCOUNT_ID,
                    name="Legacy maximum position size",
                    rule_type="max_position_size",
                    config={"maximum": 3},
                    severity="critical",
                    is_active=True,
                    version=4,
                )
            )
            session.add(
                StrategyOrderApprovalPolicyVersion(
                    id=_POLICY_VERSION_ID,
                    owner_subject=legacy._SOURCE_OWNER_ID,
                    policy_ref=_POLICY_REF,
                    policy_version=2,
                    policy_sha256=_HASH_B,
                    canonical_policy_json='{"max_notional":"1000"}',
                    published_by_subject="legacy-approver",
                    published_by_principal_ref="legacy-approver-principal",
                    published_by_actor_ref="legacy-approver-actor",
                    published_by_delegate_ref="",
                    published_at_ns=100,
                )
            )
            session.add(
                StrategyOrderApprovalPolicyHead(
                    owner_subject=legacy._SOURCE_OWNER_ID,
                    policy_ref=_POLICY_REF,
                    policy_version=2,
                    policy_sha256=_HASH_B,
                    head_version=3,
                )
            )
            approval = StrategyTargetApproval(
                approval_ref=_APPROVAL_REF,
                approval_version=2,
                record_version=5,
                state="APPROVED",
                owner_subject=legacy._SOURCE_OWNER_ID,
                principal_ref="legacy-strategy-principal",
                actor_ref="legacy-strategy-actor",
                delegate_ref="",
                scope_ref="legacy-approval-scope",
                execution_domain_ref=legacy._DOMAIN_REF,
                account_ref=legacy._ACCOUNT_REF,
                strategy_ref=legacy._STRATEGY_REF,
                strategy_version=6,
                membership_version=8,
                membership_sha256=_HASH_C,
                target_ref="legacy-target-v2",
                target_version=9,
                target_sha256=_HASH_A,
                canonical_target_json='{"instrument":"BTC-USDT","side":"BUY"}',
                policy_ref=_POLICY_REF,
                policy_version=2,
                policy_sha256=_HASH_B,
                approved_by_subject="legacy-approver",
                approved_by_principal_ref="legacy-approver-principal",
                approved_by_actor_ref="legacy-approver-actor",
                approved_by_delegate_ref="",
                approved_at_ns=200,
                expires_at_ns=9_000,
            )
            session.add(approval)
            await session.flush()
            session.add(
                StrategyTargetApprovalEvent(
                    id=_APPROVAL_EVENT_ID,
                    approval_ref=_APPROVAL_REF,
                    approval_version=2,
                    record_version=1,
                    event_type="APPROVED",
                    owner_subject=legacy._SOURCE_OWNER_ID,
                    actor_subject="legacy-approver",
                    principal_ref="legacy-approver-principal",
                    actor_ref="legacy-approver-actor",
                    delegate_ref="",
                    target_sha256=_HASH_A,
                    occurred_at_ns=200,
                    reason_code="owner_approved",
                )
            )
            session.add(
                StrategyApprovalAuthorityEpoch(
                    owner_subject=legacy._SOURCE_OWNER_ID,
                    epoch=_AUTHORITY_EPOCH,
                )
            )


async def _source_control_snapshot() -> dict[str, list[dict[str, Any]]]:
    models = {
        "paper_equity_snapshots": PaperEquitySnapshot,
        "risk_rules": RiskRule,
        "alerts": Alert,
        "alert_rules": AlertRule,
        "alert_notifications": AlertNotification,
        "strategy_target_approvals": StrategyTargetApproval,
        "strategy_target_approval_events": StrategyTargetApprovalEvent,
        "strategy_order_approval_policy_versions": StrategyOrderApprovalPolicyVersion,
        "strategy_order_approval_policy_heads": StrategyOrderApprovalPolicyHead,
        "strategy_approval_authority_epoch": StrategyApprovalAuthorityEpoch,
    }
    async with database.async_session_maker() as session:
        output: dict[str, list[dict[str, Any]]] = {}
        for name, model in models.items():
            rows = list((await session.execute(select(model))).scalars().all())
            output[name] = [_model_row(row) for row in rows]
        return output


@pytest.mark.asyncio
async def test_nonempty_http_import_uses_trusted_host_and_archives_old_controls(
    client: Any,
    tmp_path,
) -> None:
    await _run_http_host_import(client, tmp_path, residual_case=False)


@pytest.mark.asyncio
async def test_http_residual_refusal_rolls_back_exact_host_bound_import_idempotently(
    client: Any,
    tmp_path,
) -> None:
    await _run_http_host_import(client, tmp_path, residual_case=True)


async def _run_http_host_import(
    client: Any,
    tmp_path,
    *,
    residual_case: bool,
) -> None:
    """Exercise one owner-confirmed migration through API, worker, ZMQ and Host."""

    await legacy._install_source_migrations()
    if residual_case:
        await legacy._seed_account(
            total_equity=100.4,
            profit_loss=0.4,
            profit_loss_pct=0.4,
        )
    else:
        await legacy._seed_account()
    await _seed_preserved_controls()
    source_service = PaperTradingService()
    source_before = await inspect_stable_legacy_paper_account(
        source_service, legacy._SOURCE_ACCOUNT_ID, legacy._SOURCE_OWNER_ID
    )
    controls_before = await _source_control_snapshot()
    runtime_reader = PaperRuntimeService()
    async with database.async_session_maker() as session:
        snapshots_before = list(
            (
                await session.execute(
                    select(PaperEquitySnapshot)
                    .where(PaperEquitySnapshot.paper_account_id == legacy._SOURCE_ACCOUNT_ID)
                    .order_by(PaperEquitySnapshot.observed_at.asc(), PaperEquitySnapshot.id.asc())
                )
            )
            .scalars()
            .all()
        )
    assert [row.id for row in snapshots_before] == list(_SNAPSHOT_IDS)
    old_cursor = runtime_reader._encode_cursor(snapshots_before[0])
    source_page_before = await runtime_reader.list_snapshot_page(
        legacy._SOURCE_OWNER_ID,
        "afi12-paper-instance-v1",
        cursor=old_cursor,
        max_points=1,
    )
    assert source_page_before is not None
    assert [row.id for row in source_page_before.points] == [_SNAPSHOT_IDS[1]]
    assert source_page_before.next_cursor is not None
    source_last_page_before = await runtime_reader.list_snapshot_page(
        legacy._SOURCE_OWNER_ID,
        "afi12-paper-instance-v1",
        cursor=source_page_before.next_cursor,
        max_points=1,
    )
    assert source_last_page_before is not None
    assert [row.id for row in source_last_page_before.points] == [_SNAPSHOT_IDS[2]]
    assert source_last_page_before.next_cursor is None

    execution_scope, domain = legacy._domain()
    wire_scope = WireScope(
        legacy._DOMAIN_REF,
        account_ref=legacy._ACCOUNT_REF,
        strategy_ref=legacy._STRATEGY_REF,
    )
    service_endpoint = _endpoint()
    server_public, server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    service_config = _service_config(service_endpoint)
    app_identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        legacy._SOURCE_OWNER_ID,
        _APPLICATION_ID,
    )
    grant = ResourceGrant(
        _SERVICE_INSTANCE,
        _PORT,
        _SCOPE_REF,
        wire_scope,
        _OPERATIONS,
    )
    authority = TrustedServiceAuthority(
        identity=WireIdentity(WireRole.SERVICE, _SERVICE_PRINCIPAL, _SERVICE_ID),
        scope=WireScope(legacy._DOMAIN_REF),
        scope_ref=service_config.scope_ref,
        scope_version="afi12-http-host-scope-v1",
        security_ref=_SERVER_SECURITY_REF,
        security_version="curve-key-v1",
        registration_policy_ref=service_config.registration_policy_ref,
        registration_policy_version="afi12-http-host-registration-v1",
        service_requirements_ref=service_config.service_requirements_ref,
        service_requirements_version="afi12-http-host-requirements-v1",
        curve_public_key=server_public,
        curve_secret_key=server_secret,
        principals={client_public: legacy._SOURCE_OWNER_ID},
        grants={legacy._SOURCE_OWNER_ID: (PrincipalGrant(app_identity, (grant,)),)},
    )
    execution_store_path = tmp_path / "afi12-http-host-execution.sqlite3"
    registry_path = tmp_path / "afi12-http-host-registry.sqlite3"
    ready: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1)
    stop_host = threading.Event()
    host_observation: dict[str, Any] = {}
    stores: list[SqliteExecutionStore] = []

    def serve_host() -> None:
        store = SqliteExecutionStore(execution_store_path)
        stores.append(store)
        host: ServiceHost | None = None
        try:
            def resource_provider(component, instance_id, _options, _service_scope):
                assert component == "execution"
                assert instance_id == _SERVICE_INSTANCE
                return ComponentResources.borrowed(
                    {
                        "store": store,
                        "targets": {wire_scope: execution_scope},
                        "legacy_import_domain": domain,
                    },
                    ready=lambda: True,
                )

            host = ServiceHost(service_config, authority, registry_path, resource_provider)
            host.start()
            ready.put(("started", host.endpoint))
            while not stop_host.is_set():
                host.serve_once(timeout_ms=20)
        except BaseException as error:
            host_observation["error_type"] = type(error).__name__
            if ready.empty():
                ready.put(("failed", type(error).__name__))
        finally:
            if host is not None and host.state == "started":
                try:
                    host.close()
                except BaseException as error:
                    host_observation["close_error_type"] = type(error).__name__
            store.close()
            host_observation["state"] = None if host is None else host.state

    host_thread = threading.Thread(target=serve_host, name="afi12-http-host", daemon=True)
    host_thread.start()
    worker: ServiceReadWorker | None = None
    owner_app = legacy.app
    try:
        ready_state, actual_endpoint = ready.get(timeout=10)
        assert ready_state == "started", actual_endpoint
        client_config = _client_config(actual_endpoint)
        client_keys = ClientCurveKeys(server_public, client_public, client_secret)

        paper_binding = PaperSubmitBinding(
            control_mode="execution_only",
            mount="application.orders",
            scope_ref=_SCOPE_REF,
            query_scope_ref=legacy._binding(domain).query_scope_ref,
            legacy_account_id=legacy._SOURCE_ACCOUNT_ID,
            account_ref=legacy._ACCOUNT_REF,
            execution_domain_ref=legacy._DOMAIN_REF,
            strategy_ref=legacy._STRATEGY_REF,
            paper_owner_domain=domain,
            wire_scope=wire_scope,
            execution_scope=execution_scope,
        )
        import_binding = PaperLegacyImportBinding(
            mount=_MOUNT,
            owner_subject=legacy._SOURCE_OWNER_ID,
            legacy_account_id=legacy._SOURCE_ACCOUNT_ID,
            scope_ref=_SCOPE_REF,
            paper_binding=paper_binding,
            symbol_bindings=(LegacyPaperSymbolBindingV1(legacy._LEGACY_SYMBOL, legacy._INSTRUMENT),),
        )

        def session_factory() -> SdkServiceReadSession:
            owner_thread_id = threading.get_ident()

            def runtime_factory() -> ServiceClientRuntime:
                assert threading.get_ident() == owner_thread_id
                return ServiceClientRuntime(
                    client_config,
                    identity=app_identity,
                    scope_resolver=lambda _ref: wire_scope,
                    peer_resolver=lambda _service_id: authority.identity,
                    transport_factory=ZmqTransportFactory(
                        {
                            _CLIENT_SECURITY_REF: client_keys,
                        }
                    ),
                    requested_operations={_MOUNT: _OPERATIONS},
                )

            return SdkServiceReadSession(
                runtime_factory,
                app_identity,
                account_bindings={},
                paper_legacy_import_bindings={legacy._SOURCE_ACCOUNT_ID: import_binding},
            )

        worker = ServiceReadWorker(
            session_factory,
            max_queue_size=8,
            maintenance_interval_seconds=30.0,
            name="afi12-http-import-owner",
        )
        await worker.start()
        access = ReadAccess(
            worker=worker,
            allow_order_scope_refs=frozenset({paper_binding.query_scope_ref}),
            allow_paper_submit_account_ids=frozenset({legacy._SOURCE_ACCOUNT_ID}),
            allow_paper_legacy_import_account_ids=frozenset({legacy._SOURCE_ACCOUNT_ID}),
            paper_submit_bindings={legacy._SOURCE_ACCOUNT_ID: paper_binding},
            paper_legacy_import_bindings={legacy._SOURCE_ACCOUNT_ID: import_binding},
            application_identity=app_identity,
        )
        configure_service_read(ServiceReadAccessDirectory({legacy._SOURCE_OWNER_ID: access}))
        owner_app.dependency_overrides[get_current_user] = lambda: legacy._http_user(
            legacy._SOURCE_OWNER_ID
        )

        target_store = stores[0]
        target_changes_before_reads = target_store._connection.total_changes
        inspected = await client.get(
            f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}"
        )
        assert inspected.status_code == 200, inspected.text
        assert inspected.json()["source_inventory"]["sha256"] == source_before.digest
        assert inspected.json()["source_receipt"] is None
        assert inspected.json()["target"]["source_receipt"] is None
        assert target_store._connection.total_changes == target_changes_before_reads

        if residual_case:
            migrate_path = (
                f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}/migrate"
            )
            rollback_path = (
                f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}/rollback"
            )
            refused = await client.post(
                migrate_path,
                json={"confirmed": True},
                headers={"X-User-Id": "forged-owner", "X-Principal-Ref": "forged-principal"},
            )
            assert refused.status_code == 409
            assert refused.json()["details"]["code"] == (
                "LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE"
            )

            frozen = await client.get(
                f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}"
            )
            assert frozen.status_code == 200, frozen.text
            receipt = frozen.json()["source_receipt"]
            assert receipt is not None and receipt["state"] == "PREPARED"
            assert receipt["unallocated_equity_residual"] == "0.5"
            assert receipt["source_inventory_sha256"] == source_before.digest
            assert frozen.json()["target"] == {
                "owner_domain_exists": False,
                "active_account_import_state": None,
                "source_receipt": None,
            }

            repeated_refusal = await client.post(
                migrate_path,
                json={"confirmed": True},
                headers={"X-User-Id": "forged-owner", "X-Principal-Ref": "forged-principal"},
            )
            assert repeated_refusal.status_code == 409
            assert repeated_refusal.json()["details"]["code"] == (
                "LEGACY_EQUITY_RESIDUAL_UNREPRESENTABLE"
            )
            still_frozen = await client.get(
                f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}"
            )
            assert still_frozen.status_code == 200, still_frozen.text
            retry_receipt = still_frozen.json()["source_receipt"]
            assert retry_receipt is not None
            assert retry_receipt["receipt_id"] == receipt["receipt_id"]
            assert retry_receipt["generation"] == receipt["generation"]
            assert retry_receipt["source_inventory_sha256"] == source_before.digest
            assert still_frozen.json()["target"] == frozen.json()["target"]

            wrong_digest = await client.post(
                rollback_path,
                json={"confirmed": True, "source_inventory_sha256": "0" * 64},
            )
            assert wrong_digest.status_code == 403
            assert wrong_digest.json()["details"]["code"] == (
                "LEGACY_IMPORT_BINDING_MISMATCH"
            )
            after_wrong_digest = await client.get(
                f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}"
            )
            assert after_wrong_digest.status_code == 200
            assert after_wrong_digest.json()["source_receipt"]["state"] == "PREPARED"
            assert after_wrong_digest.json()["target"] == frozen.json()["target"]

            rollback_body = {
                "confirmed": True,
                "source_inventory_sha256": source_before.digest,
            }
            aborted = await client.post(rollback_path, json=rollback_body)
            assert aborted.status_code == 200, aborted.text
            assert aborted.json()["receipt"]["state"] == "ABORTED"
            assert aborted.json()["receipt"]["receipt_id"] == receipt["receipt_id"]
            assert aborted.json()["receipt"]["generation"] == receipt["generation"]

            repeated_rollback = await client.post(rollback_path, json=rollback_body)
            assert repeated_rollback.status_code == 200, repeated_rollback.text
            assert repeated_rollback.json()["receipt"] == aborted.json()["receipt"]
            after_rollback = await client.get(
                f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}"
            )
            assert after_rollback.status_code == 200, after_rollback.text
            assert after_rollback.json()["source_receipt"]["state"] == "ABORTED"
            assert after_rollback.json()["target"] == frozen.json()["target"]

            source_after = await inspect_stable_legacy_paper_account(
                PaperTradingService(), legacy._SOURCE_ACCOUNT_ID, legacy._SOURCE_OWNER_ID
            )
            assert source_after.complete and source_after.digest == source_before.digest
            assert await _source_control_snapshot() == controls_before
            assert target_store.get_paper_legacy_import(execution_scope) is None
            status = target_store.inspect_paper_legacy_import_account(
                execution_scope, source_account_id=legacy._SOURCE_ACCOUNT_ID
            )
            assert status.source_receipt is None
            assert status.owner_domain_exists is False
            assert status.active_account_import_state is None
            async with legacy.legacy_paper_writer_lease(legacy._SOURCE_ACCOUNT_ID):
                pass
            return

        migrated = await client.post(
            f"/api/v1/legacy-paper-imports/accounts/{legacy._SOURCE_ACCOUNT_ID}/migrate",
            json={"confirmed": True},
            headers={"X-User-Id": "forged-owner", "X-Principal-Ref": "forged-principal"},
        )
        assert migrated.status_code == 200, migrated.text
        payload = migrated.json()
        receipt = payload["receipt"]
        assert receipt["state"] == "ACTIVE"
        assert receipt["source_inventory_sha256"] == source_before.digest
        assert receipt["source_order_count"] == 1
        assert receipt["source_position_count"] == 1
        assert receipt["source_trade_count"] == 1
        assert receipt["cumulative_fees"] == "0.1"
        assert receipt["unallocated_equity_residual"] == "0.0"
        assert payload["legacy_ledger_retained_read_only"] is True
        assert payload["imported_rows_are_exchange_facts"] is False
        assert payload["old_rules_approvals_alerts_activated"] is False
        assert "source_snapshot_json" not in receipt
        assert "preserved_context_json" not in receipt

        after = await inspect_stable_legacy_paper_account(
            PaperTradingService(), legacy._SOURCE_ACCOUNT_ID, legacy._SOURCE_OWNER_ID
        )
        assert after.complete and after.digest == source_before.digest
        assert await _source_control_snapshot() == controls_before

        async with database.async_session_maker() as session:
            source_row = await session.scalar(
                select(LegacyPaperImportReceipt).where(
                    LegacyPaperImportReceipt.legacy_account_id == legacy._SOURCE_ACCOUNT_ID
                )
            )
            assert source_row is not None and source_row.state == "ACTIVE"
            assert source_row.preserved_context_sha256 == receipt["preserved_context_sha256"]
            preserved = json.loads(source_row.preserved_context_json)
        categories = preserved["categories"]
        assert [row["id"] for row in categories["risk_rules"]] == [_RISK_RULE_ID]
        assert [row["id"] for row in categories["alerts"]] == [_ALERT_ID]
        assert [row["id"] for row in categories["alert_rules"]] == [_ALERT_RULE_ID]
        assert [row["id"] for row in categories["alert_notifications"]] == [
            _ALERT_NOTIFICATION_ID
        ]
        assert [row["approval_ref"] for row in categories["strategy_target_approvals"]] == [
            _APPROVAL_REF
        ]
        assert [row["id"] for row in categories["strategy_target_approval_events"]] == [
            _APPROVAL_EVENT_ID
        ]
        assert categories["strategy_order_approval_policy_versions"][0]["policy_ref"] == (
            _POLICY_REF
        )
        assert categories["strategy_order_approval_policy_heads"][0]["policy_version"] == 2
        assert categories["strategy_approval_authority_epoch"][0]["epoch"] == _AUTHORITY_EPOCH
        assert {row["id"] for row in categories["paper_equity_snapshots"]} == set(
            _SNAPSHOT_IDS
        )
        assert categories["paper_equity_snapshots"][0]["total_equity"] == 99.9
        assert categories["paper_equity_snapshots"][0]["metadata"] == {
            "migration_fixture": "source-only"
        }
        assert preserved["cursor_contract"] == {
            "legacy_cursor_format": "base64url_json_observed_at_id",
            "legacy_cursor_retained": "stateless_runtime_source_only",
            "target_cursor_activated": False,
        }
        source_page_after = await runtime_reader.list_snapshot_page(
            legacy._SOURCE_OWNER_ID,
            "afi12-paper-instance-v1",
            cursor=old_cursor,
            max_points=1,
        )
        assert source_page_after is not None
        assert [row.id for row in source_page_after.points] == [
            row.id for row in source_page_before.points
        ]
        assert source_page_after.next_cursor == source_page_before.next_cursor
        source_last_page_after = await runtime_reader.list_snapshot_page(
            legacy._SOURCE_OWNER_ID,
            "afi12-paper-instance-v1",
            cursor=source_page_after.next_cursor,
            max_points=1,
        )
        assert source_last_page_after is not None
        assert [row.id for row in source_last_page_after.points] == [
            row.id for row in source_last_page_before.points
        ]
        assert source_last_page_after.next_cursor == source_last_page_before.next_cursor

        imported = target_store.get_paper_legacy_import(execution_scope)
        assert imported is not None and imported.state == "ACTIVE"
        assert imported.imported.origin == "imported_legacy"
        assert imported.imported.source_sha256 == source_before.digest
        book = target_store.read_paper_book(execution_scope)
        assert book.cash == Decimal("89.9")
        assert book.cumulative_fees == Decimal("0.1")
        assert [(row.instrument, row.quantity, row.average_cost) for row in book.positions] == [
            (legacy._INSTRUMENT, Decimal("1"), Decimal("10"))
        ]
        assert book.receipt_count == 0
        assert book.execution_cursor == 0
        assert legacy._ORDER_ID in imported.imported.source_document_json
    finally:
        configure_service_read(None)
        owner_app.dependency_overrides.pop(get_current_user, None)
        try:
            if worker is not None:
                await worker.aclose()
        finally:
            stop_host.set()
            await asyncio.to_thread(host_thread.join, 10)
            assert not host_thread.is_alive()
        assert host_observation.get("error_type") is None
        assert host_observation.get("close_error_type") is None
        assert host_observation.get("state") == "closed"
