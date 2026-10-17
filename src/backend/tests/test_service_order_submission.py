"""Focused contracts for authenticated, deployment-scoped manual orders."""

from __future__ import annotations

from collections.abc import Mapping
import os
import tempfile

import pytest
import pytest_asyncio
from pydantic import ValidationError
from pydantic_settings import BaseSettings as _BaseSettings
from sqlalchemy import select

_SYNTHETIC_ENV = {
    "DEBUG": "false",
    "DATABASE_URL": "sqlite+aiosqlite://",
    "SECRET_KEY": "manual-order-test-secret-0123456789",
    "ADMIN_PASSWORD": "ManualOrderSyntheticAdmin!98765",
    "JWT_SECRET_KEY": "manual-order-test-jwt-secret-0123456789",
    "JWT_ALGORITHM": "HS256",
    "LOG_LEVEL": "CRITICAL",
    "LOG_DIR": tempfile.mkdtemp(prefix="afi_manual_order_unit_"),
    "BT_API_LOG_DIR": tempfile.mkdtemp(prefix="afi_manual_order_sdk_"),
    "SQL_ECHO": "false",
    "AI_CHAT_ENABLED": "false",
    "AI_CHAT_BASE_URL": "",
    "AI_CHAT_API_KEY": "",
    "AI_CHAT_MODEL": "",
}
_ORIGINAL_ENV = os.environ
_ORIGINAL_SETTINGS_INIT = _BaseSettings.__init__


def _settings_without_dotenv(self, *args, **kwargs):
    kwargs["_env_file"] = None
    _ORIGINAL_SETTINGS_INIT(self, *args, **kwargs)


_BaseSettings.__init__ = _settings_without_dotenv
os.environ = dict(_SYNTHETIC_ENV)  # noqa: B003 - prevent ambient/private settings reads
try:
    import app.models  # noqa: F401,E402
    from app.api.service_orders import (  # noqa: E402
        ManualOrderRequest,
        _parse_submit_reply,
        submit_manual_order,
    )
    from app.db.database import Base, async_session_maker, engine  # noqa: E402
    from app.models.permission import ROLE_PERMISSIONS, Permission, Role  # noqa: E402
    from app.models.service_order_operation import ServiceOrderOperation  # noqa: E402
    from app.services.service_order_operations import (  # noqa: E402
        ManualOrderIdempotencyConflict,
        record_manual_order_outcome,
        reserve_manual_order_operation,
        sha256_canonical_json,
    )
    from app.services.service_read.deployment import (  # noqa: E402
        ServiceReadDeploymentError,
        _create_runtime,
        _parse_deployment,
    )
    from app.services.service_read.client import OrderSubmitBinding  # noqa: E402
finally:
    _BaseSettings.__init__ = _ORIGINAL_SETTINGS_INIT
    os.environ = _ORIGINAL_ENV  # noqa: B003 - restore process environment


@pytest_asyncio.fixture(autouse=True)
async def _isolated_schema():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


def _manual_order_profile() -> dict:
    scope_ref = "manual-current"
    service_id = "manual-order-service"
    transport_ref = "manual-order-transport-v1"
    security_ref = "manual-order-curve-v1"
    profile = {
        "subject": "subject-a",
        "identity": {
            "principal_ref": "manual-order-principal",
            "actor_ref": "application-a",
            "delegate_ref": "manual-order-delegate",
        },
        "client_config": {
            "client_config_schema_version": 1,
            "process_role": "application_client",
            "registration": {"application_ref": "application-a"},
            "clients": {
                "execution": {
                    "config_schema_version": 1,
                    "settings": {
                        "bindings": [
                            {
                                "mount": "application.orders",
                                "service_id": service_id,
                                "instance_id": "manual-order-instance",
                                "scope_ref": scope_ref,
                                "transport_ref": transport_ref,
                                "account_ref": "account-a",
                            }
                        ],
                        "options": {"request_timeout_ms": 2000},
                    },
                }
            },
            "communication": {
                "config_schema_version": 1,
                "profiles": {
                    transport_ref: {
                        "backend": "zmq",
                        "config_schema_version": 1,
                        "endpoints": {"rpc_connect": "tcp://127.0.0.1:5555"},
                        "security_profile_ref": security_ref,
                        "options": {
                            "request_timeout_ms": 2000,
                            "high_water_mark": 16,
                            "max_message_bytes": 65_536,
                        },
                    }
                },
            },
        },
        "scope_claims": {},
        "peer_identities": {
            service_id: {
                "principal_ref": "manual-order-service-principal",
                "actor_ref": service_id,
            }
        },
        "curve_keys": {
            security_ref: {"server_key": "A" * 40, "public_key": "B" * 40, "secret_key": "C" * 40}
        },
        "grants": {},
        "account_bindings": {},
        "order_bindings": {},
        "monitor_bindings": {},
        "worker": {"max_queue_size": 8, "maintenance_interval_seconds": 0.01},
    }
    profile["scope_claims"] = {
        scope_ref: {
            "execution_domain_ref": "paper:synthetic",
            "account_ref": "account-a",
            "manual_book_ref": "manual-book-a",
        }
    }
    profile["scope_claims"] = {
        scope_ref: {
            "execution_domain_ref": "paper:synthetic",
            "account_ref": "account-a",
            "manual_book_ref": "manual-book-a",
        }
    }
    profile["grants"] = {
        "account_refs": [],
        "order_scope_refs": [],
        "order_submit_scope_refs": [scope_ref],
        "monitor_scope_refs": [],
    }
    profile["order_bindings"] = {}
    profile["monitor_bindings"] = {}
    profile["order_submit_bindings"] = {
        scope_ref: {
            "mount": "application.orders",
            "account_ref": "account-a",
            "manual_book_ref": "manual-book-a",
            "instrument_metadata_versions": {"BTC-USDT": "manual-order-instrument-v1"},
        }
    }
    profile["client_config"]["clients"]["execution"]["settings"]["bindings"][0][
        "account_ref"
    ] = "account-a"
    return profile


def test_manual_order_profile_requests_only_normal_submit_operation():
    profile = _manual_order_profile()
    parsed = _parse_deployment(_document([profile]))
    assert len(parsed) == 1
    configured = parsed[0].order_submit_bindings["manual-current"]
    assert configured.mount == "application.orders"
    assert configured.scope_ref == "manual-current"
    assert configured.account_ref == "account-a"
    assert configured.manual_book_ref == "manual-book-a"
    assert configured.instrument_metadata_versions == {
        "BTC-USDT": "manual-order-instrument-v1"
    }
    profile["order_submit_bindings"]["manual-current"]["instrument_metadata_versions"][
        "BTC-USDT"
    ] = "mutated-after-parse"
    assert configured.instrument_metadata_versions["BTC-USDT"] == (
        "manual-order-instrument-v1"
    )
    with pytest.raises(TypeError):
        configured.instrument_metadata_versions["BTC-USDT"] = "caller-mutation"

    mutable_versions = {"BTC-USDT": "manual-order-instrument-v1"}
    direct_binding = OrderSubmitBinding(
        mount="application.orders",
        scope_ref="manual-current",
        account_ref="account-a",
        manual_book_ref="manual-book-a",
        instrument_metadata_versions=mutable_versions,
    )
    mutable_versions["BTC-USDT"] = "mutated-after-construction"
    assert direct_binding.instrument_metadata_versions["BTC-USDT"] == (
        "manual-order-instrument-v1"
    )

    runtime = _create_runtime(parsed[0])
    try:
        assert runtime.state == "new"
        assert runtime._requested_operations == {
            "application.orders": frozenset({"orders.submit"})
        }
    finally:
        runtime.close()


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    (
        (
            lambda profile: profile["scope_claims"]["manual-current"].pop(
                "manual_book_ref"
            ),
            "SCOPE_BINDING_MISMATCH",
        ),
        (
            lambda profile: profile["grants"].update(order_submit_scope_refs=[]),
            "GRANT_BINDING_MISMATCH",
        ),
        (
            lambda profile: profile["order_submit_bindings"]["manual-current"].update(
                operations=["orders.cancel"]
            ),
            "INVALID_DEPLOYMENT",
        ),
    ),
)
def test_manual_order_profile_rejects_nonmanual_or_expanded_grants(mutate, expected_code):
    profile = _manual_order_profile()
    mutate(profile)
    with pytest.raises(ServiceReadDeploymentError) as error:
        _parse_deployment(_document([profile]))
    assert error.value.code == expected_code


def test_manual_order_profile_keeps_empty_metadata_map_startup_compatible():
    profile = _manual_order_profile()
    profile["order_submit_bindings"]["manual-current"].pop(
        "instrument_metadata_versions"
    )
    parsed = _parse_deployment(_document([profile]))
    assert (
        parsed[0]
        .order_submit_bindings["manual-current"]
        .instrument_metadata_versions
        == {}
    )


@pytest.mark.parametrize(
    "versions",
    (
        "BTC-USDT",
        {"*": "manual-order-instrument-v1"},
        {"BTC-USDT": ""},
        {"BTC USDT": "manual-order-instrument-v1"},
        {f"SYNTH-{index}": "manual-order-instrument-v1" for index in range(257)},
    ),
)
def test_manual_order_profile_rejects_invalid_instrument_metadata_versions(versions):
    profile = _manual_order_profile()
    profile["order_submit_bindings"]["manual-current"][
        "instrument_metadata_versions"
    ] = versions
    with pytest.raises(ServiceReadDeploymentError):
        _parse_deployment(_document([profile]))


def test_manual_order_request_rejects_client_authority_and_requires_valid_terms():
    request = ManualOrderRequest.model_validate(
        {
            "scope_ref": "manual-current",
            "instrument": "BTC-USDT",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "LIMIT",
            "quantity": "1.25",
            "price": "50000",
        }
    )
    assert str(request.quantity) == "1.25"
    with pytest.raises(ValidationError):
        ManualOrderRequest.model_validate(
            {
                "scope_ref": "manual-current",
                "instrument": "BTC-USDT",
                "side": "BUY",
                "position_effect": "OPEN",
                "order_type": "LIMIT",
                "quantity": "1",
                "price": "50000",
                "actor_ref": "forged-actor",
            }
        )
    with pytest.raises(ValidationError):
        ManualOrderRequest.model_validate(
            {
                "scope_ref": "manual-current",
                "instrument": "BTC-USDT",
                "side": "BUY",
                "position_effect": "OPEN",
                "order_type": "LIMIT",
                "quantity": "1",
                "price": "50000",
                "metadata_version": "forged-version",
            }
        )
    with pytest.raises(ValidationError):
        ManualOrderRequest.model_validate(
            {
                "scope_ref": "manual-current",
                "instrument": "BTC-USDT",
                "side": "SELL",
                "position_effect": "CLOSE",
                "order_type": "MARKET",
                "quantity": "1",
            }
        )


def test_manual_order_parser_accepts_actual_sdk_call_result(tmp_path):
    """SDK ``call`` returns the Execution business envelope, not its wire wrapper."""

    from dataclasses import replace

    from bt_api_base.service_protocol import (
        WireEnvelope,
        WireIdentity,
        WireMessageKind,
        WireRole,
        WireScope,
    )
    from bt_api_execution.service_component import _reply as execution_reply
    from bt_api_py.service_config import parse_client_config
    from bt_api_py.service_registry import (
        PrincipalGrant,
        ResourceGrant,
        ServiceCapability,
        ServiceRegistry,
    )
    from bt_api_py.service_runtime import ServiceClientRuntime
    from fastapi import HTTPException

    profile = _manual_order_profile()
    client_config = parse_client_config(profile["client_config"])
    identity_raw = profile["identity"]
    identity = WireIdentity(
        WireRole.APPLICATION_CLIENT,
        identity_raw["principal_ref"],
        identity_raw["actor_ref"],
        identity_raw["delegate_ref"],
    )
    scope_ref, scope_raw = next(iter(profile["scope_claims"].items()))
    scope = WireScope(
        scope_raw["execution_domain_ref"],
        account_ref=scope_raw["account_ref"],
        manual_book_ref=scope_raw["manual_book_ref"],
    )
    service_id = "manual-order-service"
    instance_id = "manual-order-instance"
    service_identity = WireIdentity(
        WireRole.SERVICE,
        "manual-order-service-principal",
        service_id,
    )
    operations = frozenset({"orders.submit"})
    registry = ServiceRegistry(
        tmp_path / "manual-order-reply.sqlite",
        service_id=service_id,
        capabilities=(
            ServiceCapability(
                instance_id,
                "service.order_entry",
                operations,
                write_operations=operations,
            ),
        ),
        grants={
            identity.principal_ref: (
                PrincipalGrant(
                    identity,
                    (
                        ResourceGrant(
                            instance_id,
                            "service.order_entry",
                            scope_ref,
                            scope,
                            operations,
                        ),
                    ),
                ),
            )
        },
        policy_version="manual-order-access-v1",
        requirements_version="manual-order-ready-v1",
    )
    intent_id = "manual-order-no-host-intent"

    def handle_submit(_context, _arguments):
        return execution_reply(
            True,
            "OK",
            {
                "found": True,
                "record": {
                    "intent_id": intent_id,
                    "state": "ACKED",
                    "provider_order_id": "provider-order-no-host",
                },
            },
        )

    registry.register_handler(instance_id, "orders.submit", handle_submit)

    class RegistryTransport:
        def request(self, request, *, timeout):
            del timeout
            payload = registry.handle(identity.principal_ref, request)
            reply_header = replace(
                request.header,
                kind=WireMessageKind.REPLY,
                message_id=f"reply-{request.header.message_id}",
                correlation_id=request.header.message_id,
                identity=service_identity,
            )
            return WireEnvelope(reply_header, payload)

        def close(self):
            return None

    runtime = ServiceClientRuntime(
        client_config,
        identity=identity,
        scope_resolver=lambda _ref: scope,
        peer_resolver=lambda _service_id: service_identity,
        transport_factory=lambda _profile, _identity: RegistryTransport(),
        run_id="manual-order-reply-no-host",
        requested_operations={"application.orders": operations},
    )
    try:
        runtime.start()
        sdk_call_result = runtime.call(
            "application.orders",
            "orders.submit",
            {"intent_id": intent_id},
            account_ref=scope.account_ref,
            scope_ref=scope_ref,
        )
        # This is the public SDK call result: _rpc validated the WireEnvelope
        # and unwrapped the registry's transport result around Execution's reply.
        assert sdk_call_result == {
            "ok": True,
            "code": "OK",
            "result": {
                "found": True,
                "record": {
                    "intent_id": intent_id,
                    "state": "ACKED",
                    "provider_order_id": "provider-order-no-host",
                },
            },
        }
        service_code, parsed_record = _parse_submit_reply(sdk_call_result, intent_id)
        assert service_code == "OK"
        assert parsed_record is not None
        assert parsed_record["intent_id"] == intent_id
        assert parsed_record["state"] == "ACKED"
        assert parsed_record["provider_order_id"] == "provider-order-no-host"
        with pytest.raises(HTTPException) as wrapped_reply_error:
            _parse_submit_reply(
                {"ok": True, "code": "OK", "result": sdk_call_result}, intent_id
            )
        assert wrapped_reply_error.value.status_code == 503
        assert wrapped_reply_error.value.detail["code"] == "INVALID_EXECUTION_REPLY"
    finally:
        runtime.close()
        registry.close()


@pytest.mark.asyncio
async def test_manual_submit_uses_trusted_metadata_and_binds_it_to_idempotency(
    monkeypatch: pytest.MonkeyPatch,
):
    from types import SimpleNamespace

    from fastapi import HTTPException

    import app.api.service_orders as service_orders

    class Worker:
        def __init__(self):
            self.calls = []

        async def submit_manual_order(self, scope_ref, arguments):
            self.calls.append((scope_ref, dict(arguments)))
            intent_id = arguments["intent_id"]
            return {
                "ok": True,
                "code": "OK",
                "result": {
                    "found": True,
                    "record": {
                        "intent_id": intent_id,
                        "state": "ACKED",
                        "provider_order_id": f"provider-{intent_id}",
                    },
                },
            }

    worker = Worker()
    identity = SimpleNamespace(
        principal_ref="manual-order-principal",
        actor_ref="application-a",
        delegate_ref="manual-order-delegate",
    )
    access = SimpleNamespace(
        order_submit_bindings={
            "manual-current": OrderSubmitBinding(
                mount="application.orders",
                scope_ref="manual-current",
                account_ref="account-a",
                manual_book_ref="manual-book-a",
                instrument_metadata_versions={
                    "BTC-USDT": "manual-order-instrument-v1"
                },
            )
        },
        application_identity=identity,
        worker=worker,
    )
    monkeypatch.setattr(service_orders, "_resolve_access", lambda *_args: access)
    request = ManualOrderRequest.model_validate(
        {
            "scope_ref": "manual-current",
            "instrument": "BTC-USDT",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "10",
        }
    )
    current_user = type("User", (), {"sub": "owner-subject"})()

    async with async_session_maker() as db:
        first = await submit_manual_order(
            request,
            idempotency_key="metadata-version-replay",
            current_user=current_user,
            db=db,
        )
        assert first["service_code"] == "OK"
        assert worker.calls[0][1]["metadata_version"] == "manual-order-instrument-v1"
        first_operation = (
            await db.execute(select(ServiceOrderOperation))
        ).scalar_one()
        first_fingerprint = first_operation.request_sha256
        first_intent_id = first_operation.intent_id

        access.order_submit_bindings["manual-current"] = OrderSubmitBinding(
            mount="application.orders",
            scope_ref="manual-current",
            account_ref="account-a",
            manual_book_ref="manual-book-a",
            instrument_metadata_versions={"BTC-USDT": "manual-order-instrument-v2"},
        )
        with pytest.raises(HTTPException) as conflict:
            await submit_manual_order(
                request,
                idempotency_key="metadata-version-replay",
                current_user=current_user,
                db=db,
            )
        assert conflict.value.status_code == 409
        assert conflict.value.detail["code"] == "IDEMPOTENCY_CONFLICT"
        assert len(worker.calls) == 1
        persisted = (
            await db.execute(select(ServiceOrderOperation))
        ).scalar_one()
        assert persisted.intent_id == first_intent_id
        assert persisted.request_sha256 == first_fingerprint


@pytest.mark.parametrize(
    "versions",
    ({}, {"ETH-USDT": "manual-order-instrument-v1"}),
)
@pytest.mark.asyncio
async def test_manual_submit_missing_metadata_fails_before_reservation_or_dispatch(
    monkeypatch: pytest.MonkeyPatch,
    versions: Mapping[str, str],
):
    from types import SimpleNamespace

    from fastapi import HTTPException

    import app.api.service_orders as service_orders

    class Worker:
        calls = 0

        async def submit_manual_order(self, _scope_ref, _arguments):
            self.calls += 1
            raise AssertionError("missing trusted metadata must fail before SDK dispatch")

    worker = Worker()
    access = SimpleNamespace(
        order_submit_bindings={
            "manual-current": OrderSubmitBinding(
                mount="application.orders",
                scope_ref="manual-current",
                account_ref="account-a",
                manual_book_ref="manual-book-a",
                instrument_metadata_versions=versions,
            )
        },
        application_identity=SimpleNamespace(
            principal_ref="manual-order-principal",
            actor_ref="application-a",
            delegate_ref="manual-order-delegate",
        ),
        worker=worker,
    )
    monkeypatch.setattr(service_orders, "_resolve_access", lambda *_args: access)
    request = ManualOrderRequest.model_validate(
        {
            "scope_ref": "manual-current",
            "instrument": "BTC-USDT",
            "side": "BUY",
            "position_effect": "OPEN",
            "order_type": "LIMIT",
            "quantity": "1",
            "price": "10",
        }
    )
    current_user = type("User", (), {"sub": "owner-subject"})()
    async with async_session_maker() as db:
        with pytest.raises(HTTPException) as missing:
            await submit_manual_order(
                request,
                idempotency_key="missing-metadata",
                current_user=current_user,
                db=db,
            )
        assert missing.value.status_code == 503
        assert missing.value.detail["code"] == (
            "INSTRUMENT_METADATA_VERSION_NOT_CONFIGURED"
        )
        assert worker.calls == 0
        assert (await db.execute(select(ServiceOrderOperation))).scalars().all() == []


def test_manual_submission_permission_excludes_guest_and_approval_admin():
    assert Permission.SUBMIT_MANUAL_ORDER in ROLE_PERMISSIONS[Role.USER]
    assert Permission.SUBMIT_MANUAL_ORDER in ROLE_PERMISSIONS[Role.PREMIUM]
    assert Permission.SUBMIT_MANUAL_ORDER in ROLE_PERMISSIONS[Role.ADMIN]
    assert Permission.SUBMIT_MANUAL_ORDER not in ROLE_PERMISSIONS[Role.GUEST]
    assert Permission.SUBMIT_MANUAL_ORDER not in ROLE_PERMISSIONS[Role.RESEARCH_APPROVAL_ADMIN]


@pytest.mark.asyncio
async def test_operation_key_mapping_is_durable_actor_scoped_and_conflict_detecting():
    request_hash = sha256_canonical_json(
        {"instrument": "BTC-USDT", "quantity": "1", "side": "BUY"}
    )

    async with async_session_maker() as db:
        first = await reserve_manual_order_operation(
            db,
            owner_subject="owner-a",
            principal_ref="afi-app-principal",
            actor_ref="actor-a",
            delegate_ref="delegate-a",
            operation_key="same-business-key",
            request_sha256=request_hash,
            scope_ref="manual-current",
            account_ref="account-a",
            manual_book_ref="manual-book-a",
        )
        await record_manual_order_outcome(
            db,
            first.operation,
            service_code="OK",
            record_state="ACKED",
        )
        replay = await reserve_manual_order_operation(
            db,
            owner_subject="owner-a",
            principal_ref="afi-app-principal",
            actor_ref="actor-a",
            delegate_ref="delegate-a",
            operation_key="same-business-key",
            request_sha256=request_hash,
            scope_ref="manual-current",
            account_ref="account-a",
            manual_book_ref="manual-book-a",
        )
        assert replay.created is False
        assert replay.operation.intent_id == first.operation.intent_id

        with pytest.raises(ManualOrderIdempotencyConflict):
            await reserve_manual_order_operation(
                db,
                owner_subject="owner-a",
                principal_ref="afi-app-principal",
                actor_ref="actor-a",
                delegate_ref="delegate-a",
                operation_key="same-business-key",
                request_sha256=sha256_canonical_json(
                    {"instrument": "BTC-USDT", "quantity": "2", "side": "BUY"}
                ),
                scope_ref="manual-current",
                account_ref="account-a",
                manual_book_ref="manual-book-a",
            )

        other_actor = await reserve_manual_order_operation(
            db,
            owner_subject="owner-a",
            principal_ref="afi-app-principal",
            actor_ref="actor-b",
            delegate_ref="delegate-b",
            operation_key="same-business-key",
            request_sha256=request_hash,
            scope_ref="manual-current",
            account_ref="account-a",
            manual_book_ref="manual-book-a",
        )
        assert other_actor.created is True
        assert other_actor.operation.intent_id != first.operation.intent_id
        first_id = first.operation.intent_id
        other_actor_id = other_actor.operation.intent_id
        row_id = first.operation.id

    async with async_session_maker() as db:
        persisted = await db.get(ServiceOrderOperation, row_id)
        assert persisted is not None
        assert persisted.intent_id == first_id
        assert persisted.last_service_code == "OK"
        assert persisted.last_record_state == "ACKED"
        rows = (
            await db.execute(
                select(ServiceOrderOperation).where(
                    ServiceOrderOperation.operation_key_sha256.is_not(None)
                )
            )
        ).scalars().all()
        assert {row.intent_id for row in rows} >= {first_id, other_actor_id}


def _document(profiles: list[dict]) -> str:
    import json

    return json.dumps({"schema_version": 1, "subjects": profiles})
