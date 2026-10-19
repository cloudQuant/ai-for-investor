from __future__ import annotations

import json
import time
from types import SimpleNamespace

import pytest
import zmq
from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
from bt_api_transport_zmq.server import CurveClientCredentials
from fastapi import HTTPException, Response
from pydantic import SecretStr, ValidationError

import app.api.strategy_reduction as reduction_api
import app.services.strategy_reduction_control as reduction_control
from app.api.afi_owner_scope import PersistedOwnerScope
from app.api.strategy_reduction import (
    StrategyReductionRequest,
    _not_dispatched_projection,
    _validate_owner_reply,
    _validate_persisted_close_target,
)
from app.schemas.auth import TokenPayload
from app.services.strategy_reduction_control import (
    StrategyReductionControlError,
    StrategyReductionDeployment,
)
from app.services.strategy_target_approvals import canonical_target_json, canonical_target_sha256


def test_reduction_curve_keys_remain_z85_encoded_for_transport():
    server_key, _server_secret = zmq.curve_keypair()
    client_public_key, client_secret_key = zmq.curve_keypair()

    resolved = tuple(
        reduction_control._z85_bytes(SecretStr(key.decode("ascii")))
        for key in (server_key, client_public_key, client_secret_key)
    )

    assert resolved == (server_key, client_public_key, client_secret_key)
    assert all(len(key) == 40 for key in resolved)
    credentials = CurveClientCredentials(*resolved)
    assert credentials.server_key == server_key
    assert credentials.public_key == client_public_key

    for invalid_key in ("0" * 39, "0" * 39 + "_"):
        with pytest.raises(StrategyReductionControlError) as error:
            reduction_control._z85_bytes(SecretStr(invalid_key))
        assert error.value.code == "DEPLOYMENT_INVALID"


def _service_config(*, account_ref: str, service_id: str, instance_id: str, scope_ref: str, endpoint: str):
    return {
        "service_config_schema_version": 1,
        "process_role": "service",
        # This is the client process's own service identity. The binding's
        # service_id below names the distinct remote account owner; using the
        # same identifier would be a self-reference and is rejected by the
        # canonical SDK config parser.
        "service_id": "afi-reduction-application-client",
        "scope_ref": "reduction-client-registration-v1",
        "transport_ref": "reduction-client-listener-v1",
        "registration_policy_ref": "reduction-client-registration-policy-v1",
        "service_requirements_ref": "reduction-client-requirements-v1",
        "components": {
            "execution": {
                "config_schema_version": 2,
                "settings": {
                    "instance_id": instance_id,
                    "bind_ports": ["service.owner_control"],
                    "options": {"role": "account_owner"},
                },
            }
        },
        "clients": {
            "execution": {
                "config_schema_version": 1,
                "settings": {
                    "bindings": [
                        {
                            "mount": "upstream.owner_control",
                            "service_id": service_id,
                            "instance_id": instance_id,
                            "scope_ref": scope_ref,
                            "transport_ref": "reduction-client-connect-v1",
                            "account_ref": account_ref,
                        }
                    ],
                    "options": {"request_timeout_ms": 2_000},
                },
            }
        },
        "communication": {
            "config_schema_version": 1,
            "profiles": {
                "reduction-client-listener-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_bind": endpoint},
                    "security_profile_ref": "reduction-server-curve-v1",
                },
                "reduction-client-connect-v1": {
                    "backend": "zmq",
                    "config_schema_version": 1,
                    "endpoints": {"rpc_connect": endpoint},
                    "security_profile_ref": "reduction-client-curve-v1",
                },
            },
        },
    }


def _deployment_value(tmp_path, *, subject: str = "subject.test", run_id: str = "run.test"):
    server_public, _server_secret = zmq.curve_keypair()
    client_public, client_secret = zmq.curve_keypair()
    scope = WireScope(
        "paper:reduction-test",
        account_ref="account.test",
        strategy_ref="strategy.test",
        run_id=run_id,
    )
    service_id = "reduction-owner-service"
    instance_id = "reduction-owner-instance"
    owner_scope_ref = "owner-run-scope"
    profile = {
        "profile_ref": "reduction-profile",
        "subject": subject,
        "selector_ref": "afi-selector",
        "approved_target_scope_ref": "approved-target-scope",
        "account_ref": "account.test",
        "strategy_ref": "strategy.test",
        "run_id": run_id,
        "service_id": service_id,
        "instance_id": instance_id,
        "scope_ref": owner_scope_ref,
        "not_before_utc": time.time() - 60,
        "expires_at_utc": time.time() + 3600,
        "wire_scope": {
            "execution_domain_ref": scope.execution_domain_ref,
            "account_ref": scope.account_ref,
            "account_refs": [],
            "strategy_ref": scope.strategy_ref,
            "run_id": scope.run_id,
            "manual_book_ref": None,
            "portfolio_ref": None,
            "group_id": None,
            "leg_id": None,
        },
        "client_identity": {
            "principal_ref": "principal.test",
            "actor_ref": "actor.test",
            "delegate_ref": "delegate.test",
        },
        "peer_identity": {
            "principal_ref": "owner.principal",
            "actor_ref": "owner.actor",
            "delegate_ref": "owner.delegate",
        },
        "client_config": _service_config(
            account_ref=scope.account_ref,
            service_id=service_id,
            instance_id=instance_id,
            scope_ref=owner_scope_ref,
            endpoint="tcp://127.0.0.1:19878",
        ),
        "curve_keys": {
            "reduction-client-curve-v1": {
                "server_key_z85": server_public.decode("ascii"),
                "public_key_z85": client_public.decode("ascii"),
                "secret_key_z85": client_secret.decode("ascii"),
            }
        },
    }
    return {
        "schema_version": 1,
        "deployment_id": "reduction-deployment",
        "deployment_version": "v1",
        "not_before_utc": time.time() - 60,
        "expires_at_utc": time.time() + 3600,
        "profiles": [profile],
    }, scope


def _persisted_close_target(*, position_effect: str = "CLOSE", reduce_only: bool = True):
    scope = WireScope(
        "paper:reduction-test",
        account_ref="account.test",
        strategy_ref="strategy.test",
        run_id="run.test",
    )
    identity = WireIdentity(
        WireRole.APPLICATION_CLIENT, "principal.test", "actor.test", "delegate.test"
    )
    target = {
        "schema_id": "bt_api.approved_order_target",
        "schema_version": 1,
        "target_ref": "target.reduction",
        "target_version": 1,
        "owner_subject": "subject.test",
        "principal_ref": identity.principal_ref,
        "actor_ref": identity.actor_ref,
        "delegate_ref": identity.delegate_ref,
        "scope_ref": "approved-target-scope",
        "wire_scope": {
            "execution_domain_ref": scope.execution_domain_ref,
            "account_ref": scope.account_ref,
            "account_refs": [],
            "strategy_ref": scope.strategy_ref,
            "run_id": scope.run_id,
            "manual_book_ref": None,
            "portfolio_ref": None,
            "group_id": None,
            "leg_id": None,
        },
        "strategy_version": 1,
        "membership_version": None,
        "membership_sha256": None,
        "instrument": "BTC-USDT",
        "metadata_version": "instrument-v1",
        "side": "SELL",
        "position_effect": position_effect,
        "order_type": "LIMIT",
        "quantity": "2",
        "price": "100",
        "time_in_force": "GTC",
        "reduce_only": reduce_only,
        "deadline_ns": None,
        "limits": {
            "max_quantity": "2",
            "max_notional": "200",
            "min_price": "1",
            "max_price": "200",
        },
        "policy_ref": "policy.reduction",
        "policy_version": 1,
        "policy_sha256": "a" * 64,
    }
    canonical = canonical_target_json(target)
    approval = SimpleNamespace(
        approval_version=1,
        target_sha256=canonical_target_sha256(target),
        scope_ref="approved-target-scope",
        owner_subject="subject.test",
        account_ref="account.test",
        strategy_ref="strategy.test",
        execution_domain_ref=scope.execution_domain_ref,
        principal_ref=identity.principal_ref,
        actor_ref=identity.actor_ref,
        delegate_ref=identity.delegate_ref,
        canonical_target_json=canonical,
    )
    return approval, identity, scope


def test_reduction_deployment_binds_authenticated_identity_and_exact_run(tmp_path):
    value, wire_scope = _deployment_value(tmp_path)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    deployment = StrategyReductionDeployment.from_secret(SecretStr(raw))
    assert deployment is not None
    profile = deployment.profile_for(
        subject="subject.test",
        selector_ref="afi-selector",
        approved_target_scope_ref="approved-target-scope",
        application_identity=WireIdentity(
            WireRole.APPLICATION_CLIENT,
            "principal.test",
            "actor.test",
            "delegate.test",
        ),
        approved_target_wire_scope=wire_scope,
    )
    assert profile.wire_scope.run_id == "run.test"

    with pytest.raises(StrategyReductionControlError) as wrong_run:
        deployment.profile_for(
            subject="subject.test",
            selector_ref="afi-selector",
            approved_target_scope_ref="approved-target-scope",
            application_identity=WireIdentity(
                WireRole.APPLICATION_CLIENT,
                "principal.test",
                "actor.test",
                "delegate.test",
            ),
            approved_target_wire_scope=WireScope(
                wire_scope.execution_domain_ref,
                account_ref="account.test",
                strategy_ref="strategy.test",
                run_id="run.other",
            ),
        )
    assert wrong_run.value.code == "PROFILE_SCOPE_MISMATCH"

    with pytest.raises(StrategyReductionControlError) as foreign_owner:
        deployment.profile_for(
            subject="other.subject",
            selector_ref="afi-selector",
            approved_target_scope_ref="approved-target-scope",
            application_identity=WireIdentity(
                WireRole.APPLICATION_CLIENT,
                "principal.test",
                "actor.test",
                "delegate.test",
            ),
            approved_target_wire_scope=wire_scope,
        )
    assert foreign_owner.value.code == "PROFILE_NOT_AUTHORIZED"


def test_reduction_deployment_rejects_duplicate_json_keys_and_never_exposes_curve_secret(tmp_path):
    value, _scope = _deployment_value(tmp_path)
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    deployment = StrategyReductionDeployment.from_secret(SecretStr(raw))
    assert deployment is not None
    secret = value["profiles"][0]["curve_keys"]["reduction-client-curve-v1"]["secret_key_z85"]
    assert secret not in repr(deployment)

    duplicated = '{"schema_version":1,' + raw[1:]
    with pytest.raises(StrategyReductionControlError) as duplicate_error:
        StrategyReductionDeployment.from_secret(SecretStr(duplicated))
    assert duplicate_error.value.code == "DEPLOYMENT_INVALID"


def test_reduction_request_rejects_caller_selected_trade_terms_and_scope():
    valid = {
        "scope_ref": "afi-selector",
        "approval_ref": "approval.test",
        "approval_version": 1,
        "target_sha256": "a" * 64,
    }
    assert StrategyReductionRequest.model_validate(valid).approval_ref == "approval.test"
    for injected in (
        {"quantity": "2"},
        {"run_id": "run.other"},
        {"account_ref": "account.other"},
        {"position_effect": "OPEN"},
    ):
        with pytest.raises(ValidationError):
            StrategyReductionRequest.model_validate(valid | injected)


def test_persisted_target_scope_and_close_terms_are_authoritative():
    approval, identity, scope = _persisted_close_target()
    target = _validate_persisted_close_target(
        approval,
        owner_subject="subject.test",
        application_identity=identity,
        scope_ref="approved-target-scope",
        wire_scope=scope,
        approval_version=1,
        target_sha256=approval.target_sha256,
    )
    assert target["position_effect"] == "CLOSE"
    assert target["reduce_only"] is True
    assert target["quantity"] == "2"

    for effect, reduce_only in (("OPEN", False), ("CLOSE_TODAY", True)):
        rejected, rejected_identity, rejected_scope = _persisted_close_target(
            position_effect=effect, reduce_only=reduce_only
        )
        with pytest.raises(HTTPException) as error:
            _validate_persisted_close_target(
                rejected,
                owner_subject="subject.test",
                application_identity=rejected_identity,
                scope_ref="approved-target-scope",
                wire_scope=rejected_scope,
                approval_version=1,
                target_sha256=rejected.target_sha256,
            )
        assert error.value.status_code == 409

    with pytest.raises(HTTPException) as wrong_run:
        _validate_persisted_close_target(
            approval,
            owner_subject="subject.test",
            application_identity=identity,
            scope_ref="approved-target-scope",
            wire_scope=WireScope(
                scope.execution_domain_ref,
                account_ref=scope.account_ref,
                strategy_ref=scope.strategy_ref,
                run_id="run.other",
            ),
            approval_version=1,
            target_sha256=approval.target_sha256,
        )
    assert wrong_run.value.status_code == 403


@pytest.mark.asyncio
async def test_reduction_http_service_path_uses_only_persisted_target_and_stable_intent(monkeypatch):
    value, scope = _deployment_value(None)
    deployment = StrategyReductionDeployment.from_secret(
        SecretStr(json.dumps(value, sort_keys=True, separators=(",", ":")))
    )
    assert deployment is not None
    approval, _identity, _approved_scope = _persisted_close_target()
    identity = WireIdentity(
        WireRole.APPLICATION_CLIENT, "principal.test", "actor.test", "delegate.test"
    )
    binding = SimpleNamespace(
        expected_scope_ref="approved-target-scope",
        account_ref="account.test",
        strategy_ref="strategy.test",
        wire_scope=scope,
    )
    monkeypatch.setattr(
        reduction_api,
        "_resolve_access",
        lambda *_args: SimpleNamespace(
            approved_target_bindings={"afi-selector": binding},
            application_identity=identity,
        ),
    )

    class _Db:
        async def scalar(self, _query):
            return approval

    async def reserve(_db, **_arguments):
        return SimpleNamespace(intent_id="intent.stable", created=True)

    monkeypatch.setattr(
        reduction_api, "reserve_approved_target_http_operation", reserve
    )
    received = []

    def submit(_profile, **arguments):
        received.append(arguments)
        return {
            "ok": True,
            "code": "OK",
            "result": {
                "reduction": {
                    "schema_id": "bt_api.owner_strategy_reduction_outcome",
                    "schema_version": 1,
                    "intent_id": "intent.stable",
                    "status": "FILLED",
                    "stage": "EXECUTION",
                    "execution_state": "FILLED",
                    "filled_quantity": "2",
                    "is_terminal": True,
                    "review_required": False,
                    "reason_code": "OUTCOME_OBSERVED",
                }
            },
        }

    monkeypatch.setattr(deployment, "submit", submit)
    response = Response()
    result = await reduction_api.reduce_approved_strategy_target(
        StrategyReductionRequest(
            scope_ref="afi-selector",
            approval_ref="approval.test",
            approval_version=1,
            target_sha256=approval.target_sha256,
        ),
        response,
        "idem.reduction",
        PersistedOwnerScope("subject.test", "HUMAN"),
        TokenPayload(sub="subject.test", username="owner"),
        _Db(),
        deployment,
    )
    assert response.status_code == 200
    assert result["intent_id"] == "intent.stable"
    assert result["outcome"] == "filled"
    assert result["flatness"] == "not_established"
    assert received == [
        {
            "approval_ref": "approval.test",
            "approval_version": 1,
            "target_sha256": approval.target_sha256,
            "intent_id": "intent.stable",
        }
    ]


@pytest.mark.parametrize(
    ("state", "status_text", "terminal", "review", "http_outcome", "filled_quantity"),
    [
        ("ACKED", "PENDING", False, False, "pending", "0"),
        ("PARTIALLY_FILLED", "PARTIAL", False, False, "partial", "1.25"),
        ("FILLED", "FILLED", True, False, "filled", "2"),
        ("UNKNOWN", "UNKNOWN", False, True, "unknown_review_required", "0"),
    ],
)
def test_reduction_projects_owner_order_state_without_claiming_flatness(
    state, status_text, terminal, review, http_outcome, filled_quantity
):
    intent_id = "intent.reduction"
    reply = {
        "ok": True,
        "code": "OK",
        "result": {
            "reduction": {
                "schema_id": "bt_api.owner_strategy_reduction_outcome",
                "schema_version": 1,
                "intent_id": intent_id,
                "status": status_text,
                "stage": "EXECUTION",
                "execution_state": state,
                "filled_quantity": filled_quantity,
                "is_terminal": terminal,
                "review_required": review,
                "reason_code": "OUTCOME_OBSERVED",
            }
        },
    }
    projection = _validate_owner_reply(reply, intent_id, approved_quantity="2")
    assert projection["outcome"] == http_outcome
    assert projection["execution"]["filled_quantity"] == filled_quantity
    assert projection["flatness"] == "not_established"


def test_reduction_rejects_impossible_or_over_target_owner_fill_projection():
    base = {
        "ok": True,
        "code": "OK",
        "result": {
            "reduction": {
                "schema_id": "bt_api.owner_strategy_reduction_outcome",
                "schema_version": 1,
                "intent_id": "intent.reduction",
                "status": "FILLED",
                "stage": "EXECUTION",
                "execution_state": None,
                "filled_quantity": "0",
                "is_terminal": False,
                "review_required": False,
                "reason_code": "OUTCOME_OBSERVED",
            }
        },
    }
    impossible = _validate_owner_reply(
        base, "intent.reduction", approved_quantity="2"
    )
    assert impossible["outcome"] == "unknown_review_required"

    overfilled = json.loads(json.dumps(base))
    overfilled["result"]["reduction"].update(
        {
            "execution_state": "FILLED",
            "filled_quantity": "2.1",
            "is_terminal": True,
        }
    )
    projection = _validate_owner_reply(
        overfilled, "intent.reduction", approved_quantity="2"
    )
    assert projection["outcome"] == "unknown_review_required"


def test_expired_operator_profile_returns_explicit_not_dispatched_projection():
    projection = _not_dispatched_projection(
        "intent.reduction", "DEPLOYMENT_INACTIVE_OR_EXPIRED"
    )
    assert projection["outcome"] == "not_dispatched"
    assert projection["execution"]["execution_state"] is None
    assert projection["execution"]["filled_quantity"] == "0"
    assert projection["execution"]["stage"] == "AUTHORITY"
    assert projection["flatness"] == "not_established"


def test_expiring_deployment_is_rechecked_before_service_client_creation(monkeypatch):
    value, _scope = _deployment_value(None)
    value["expires_at_utc"] = time.time() + 30
    value["profiles"][0]["expires_at_utc"] = time.time() + 30
    deployment = StrategyReductionDeployment.from_secret(
        SecretStr(json.dumps(value, sort_keys=True, separators=(",", ":")))
    )
    assert deployment is not None
    profile = deployment.profiles[0]
    monkeypatch.setattr(reduction_control.time, "time", lambda: value["expires_at_utc"])
    monkeypatch.setattr(
        reduction_control,
        "_load_sdk",
        lambda: pytest.fail("expired deployment reached SDK client creation"),
    )
    with pytest.raises(StrategyReductionControlError) as expired:
        deployment.submit(
            profile,
            approval_ref="approval.test",
            approval_version=1,
            target_sha256="a" * 64,
            intent_id="intent.reduction",
        )
    assert expired.value.code == "DEPLOYMENT_INACTIVE_OR_EXPIRED"

