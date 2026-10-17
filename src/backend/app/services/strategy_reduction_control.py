"""Operator-owned client path for exact approved strategy reductions.

This module owns only the AFI-to-SDK client configuration. It does not create
an account provider, choose a strategy/run, or make an order decision. A POST
selects one server-configured profile by authenticated subject and the existing
approved-target selector, then asks the existing SDK owner service to resolve
the immutable approved target through its normal Risk/Execution path.
"""

from __future__ import annotations

import json
import math
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

_MAX_DEPLOYMENT_BYTES = 262_144
_MAX_PROFILES = 128
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_IDENTITY_FIELDS = frozenset({"principal_ref", "actor_ref", "delegate_ref"})
_SCOPE_FIELDS = frozenset(
    {
        "execution_domain_ref",
        "account_ref",
        "account_refs",
        "strategy_ref",
        "run_id",
        "manual_book_ref",
        "portfolio_ref",
        "group_id",
        "leg_id",
    }
)
_Z85 = frozenset(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#"
)
_OWNER_MOUNT = "upstream.owner_control"
_OWNER_OPERATION = "owner.reduce"


class StrategyReductionControlError(RuntimeError):
    """Finite, value-free error from trusted reduction deployment wiring."""

    _CODES = frozenset(
        {
            "DEPLOYMENT_INVALID",
            "DEPLOYMENT_INACTIVE_OR_EXPIRED",
            "DEPLOYMENT_NOT_CONFIGURED",
            "PROFILE_NOT_AUTHORIZED",
            "PROFILE_AMBIGUOUS",
            "PROFILE_SCOPE_MISMATCH",
            "SDK_NOT_INSTALLED",
            "OWNER_SERVICE_UNAVAILABLE",
            "OWNER_OPERATION_DENIED",
            "OWNER_OUTCOME_UNKNOWN",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "DEPLOYMENT_INVALID"
        super().__init__(self.code)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _CurveKey(_StrictModel):
    server_key_z85: SecretStr = Field(repr=False, exclude=True)
    public_key_z85: SecretStr = Field(repr=False, exclude=True)
    secret_key_z85: SecretStr = Field(repr=False, exclude=True)


class _ProfileConfig(_StrictModel):
    profile_ref: str = Field(min_length=1, max_length=128)
    subject: str = Field(min_length=1, max_length=256)
    selector_ref: str = Field(min_length=1, max_length=128)
    approved_target_scope_ref: str = Field(min_length=1, max_length=128)
    account_ref: str = Field(min_length=1, max_length=128)
    strategy_ref: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    service_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    scope_ref: str = Field(min_length=1, max_length=128)
    not_before_utc: float
    expires_at_utc: float
    wire_scope: dict[str, Any] = Field(repr=False)
    client_identity: dict[str, str | None] = Field(repr=False)
    peer_identity: dict[str, str | None] = Field(repr=False)
    client_config: dict[str, Any] = Field(repr=False, exclude=True)
    curve_keys: dict[str, _CurveKey] = Field(repr=False, exclude=True)


class _DeploymentConfig(_StrictModel):
    schema_version: int
    deployment_id: str = Field(min_length=1, max_length=128)
    deployment_version: str = Field(min_length=1, max_length=64)
    not_before_utc: float
    expires_at_utc: float
    profiles: list[_ProfileConfig] = Field(min_length=1, max_length=_MAX_PROFILES)


@dataclass(frozen=True, slots=True)
class StrategyReductionProfile:
    config: _ProfileConfig = field(repr=False)
    wire_scope: Any = field(repr=False)
    client_identity: Any = field(repr=False)
    peer_identity: Any = field(repr=False)
    client_config: Any = field(repr=False)
    curve_keys: Mapping[str, Any] = field(repr=False)


class StrategyReductionDeployment:
    """Validated server profile map; it never connects until ``submit``."""

    def __init__(self, config: _DeploymentConfig, profiles: tuple[StrategyReductionProfile, ...]):
        self._config = config
        self.profiles = profiles

    @classmethod
    def from_secret(
        cls, value: SecretStr | str | None
    ) -> StrategyReductionDeployment | None:
        if isinstance(value, SecretStr):
            raw = value.get_secret_value()
        elif type(value) is str:
            raw = value
        elif value is None:
            raw = ""
        else:
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        if not raw:
            return None
        try:
            if len(raw.encode("utf-8", errors="strict")) > _MAX_DEPLOYMENT_BYTES:
                raise StrategyReductionControlError("DEPLOYMENT_INVALID")
            json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
            config = _DeploymentConfig.model_validate_json(raw)
            if (
                type(config.schema_version) is not int
                or config.schema_version != 1
                or not _SAFE_REF.fullmatch(config.deployment_id)
                or not _SAFE_REF.fullmatch(config.deployment_version)
                or not _finite(config.not_before_utc)
                or not _finite(config.expires_at_utc)
                or config.expires_at_utc <= config.not_before_utc
            ):
                raise StrategyReductionControlError("DEPLOYMENT_INVALID")
            sdk = _load_sdk()
            profiles = tuple(_build_profile(item, sdk) for item in config.profiles)
            profile_refs = [item.config.profile_ref for item in profiles]
            selectors = [(item.config.subject, item.config.selector_ref) for item in profiles]
            if len(profile_refs) != len(set(profile_refs)) or len(selectors) != len(set(selectors)):
                raise StrategyReductionControlError("DEPLOYMENT_INVALID")
            return cls(config, profiles)
        except StrategyReductionControlError:
            raise
        except (ArithmeticError, OSError, UnicodeError, ValueError, TypeError, ValidationError, RecursionError):
            raise StrategyReductionControlError("DEPLOYMENT_INVALID") from None
        except Exception:
            # Import/config parser failures are deliberately value-free; no
            # serialized deployment material enters the error or its repr.
            raise StrategyReductionControlError("DEPLOYMENT_INVALID") from None

    @property
    def version(self) -> str:
        return self._config.deployment_version

    def profile_for(
        self,
        *,
        subject: str,
        selector_ref: str,
        approved_target_scope_ref: str,
        application_identity: object,
        approved_target_wire_scope: object,
    ) -> StrategyReductionProfile:
        now = time.time()
        if not self._config.not_before_utc <= now < self._config.expires_at_utc:
            raise StrategyReductionControlError("DEPLOYMENT_INACTIVE_OR_EXPIRED")
        matches = [
            item
            for item in self.profiles
            if item.config.subject == subject and item.config.selector_ref == selector_ref
        ]
        if not matches:
            raise StrategyReductionControlError("PROFILE_NOT_AUTHORIZED")
        if len(matches) != 1:
            raise StrategyReductionControlError("PROFILE_AMBIGUOUS")
        profile = matches[0]
        config = profile.config
        if not config.not_before_utc <= now < config.expires_at_utc:
            raise StrategyReductionControlError("DEPLOYMENT_INACTIVE_OR_EXPIRED")
        if (
            config.approved_target_scope_ref != approved_target_scope_ref
            or _identity_refs(application_identity) != _identity_refs(profile.client_identity)
            or _scope_payload(profile.wire_scope) != _scope_payload(approved_target_wire_scope)
        ):
            raise StrategyReductionControlError("PROFILE_SCOPE_MISMATCH")
        return profile

    def submit(
        self,
        profile: StrategyReductionProfile,
        *,
        approval_ref: str,
        approval_version: int,
        target_sha256: str,
        intent_id: str,
    ) -> Mapping[str, Any]:
        """Call owner.reduce once; callers retry only with the same durable intent."""

        if not any(item is profile for item in self.profiles):
            raise StrategyReductionControlError("PROFILE_NOT_AUTHORIZED")
        now = time.time()
        if (
            not self._config.not_before_utc <= now < self._config.expires_at_utc
            or not profile.config.not_before_utc <= now < profile.config.expires_at_utc
        ):
            # profile_for can run before a DB transaction; recheck the
            # operator grant immediately before opening the service client.
            raise StrategyReductionControlError("DEPLOYMENT_INACTIVE_OR_EXPIRED")
        sdk = _load_sdk()
        runtime = sdk.ServiceClientRuntime(
            profile.client_config,
            identity=profile.client_identity,
            scope_resolver=lambda scope_ref: _fixed_lookup(
                {profile.config.scope_ref: profile.wire_scope}, scope_ref
            ),
            peer_resolver=lambda service_id: _fixed_lookup(
                {profile.config.service_id: profile.peer_identity}, service_id
            ),
            transport_factory=sdk.ZmqTransportFactory(profile.curve_keys),
            requested_operations={_OWNER_MOUNT: frozenset({_OWNER_OPERATION})},
        )
        call_started = False
        try:
            registered = runtime.start()
            if registered.degraded_count or len(registered.bindings) != 1:
                raise StrategyReductionControlError("OWNER_SERVICE_UNAVAILABLE")
            call_started = True
            try:
                reply = runtime.call(
                    _OWNER_MOUNT,
                    _OWNER_OPERATION,
                    {
                        "schema_id": "bt_api.owner_strategy_reduction",
                        "schema_version": 1,
                        "approval_ref": approval_ref,
                        "approval_version": approval_version,
                        "target_sha256": target_sha256,
                        "intent_id": intent_id,
                    },
                    account_ref=profile.wire_scope.account_ref,
                    scope_ref=profile.config.scope_ref,
                )
            except Exception as error:
                code = getattr(error, "code", None)
                if code in {"SCOPE_DENIED", "ACTION_NOT_GRANTED", "ROLE_NOT_AUTHORIZED"}:
                    raise StrategyReductionControlError("OWNER_OPERATION_DENIED") from None
                raise StrategyReductionControlError("OWNER_OUTCOME_UNKNOWN") from None
            return reply
        except StrategyReductionControlError:
            raise
        except Exception:
            raise StrategyReductionControlError(
                "OWNER_OUTCOME_UNKNOWN" if call_started else "OWNER_SERVICE_UNAVAILABLE"
            ) from None
        finally:
            try:
                runtime.close()
            except Exception:
                # A received immutable owner result remains useful. A cleanup
                # failure is not turned into a second call or fabricated fill.
                pass


def get_deployment_setting() -> SecretStr:
    """Read the separately configured server-owned reduction profile map."""

    from app.config import get_settings

    return get_settings().SERVICE_STRATEGY_REDUCTION_DEPLOYMENT_JSON


def _load_sdk() -> Any:
    try:
        from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
        from bt_api_py.service_config import parse_service_config
        from bt_api_py.service_runtime import (
            ClientCurveKeys,
            ServiceClientRuntime,
            ZmqTransportFactory,
        )
    except ImportError:
        raise StrategyReductionControlError("SDK_NOT_INSTALLED") from None
    return type(
        "_Sdk",
        (),
        {
            "WireIdentity": WireIdentity,
            "WireRole": WireRole,
            "WireScope": WireScope,
            "parse_service_config": parse_service_config,
            "ClientCurveKeys": ClientCurveKeys,
            "ServiceClientRuntime": ServiceClientRuntime,
            "ZmqTransportFactory": ZmqTransportFactory,
        },
    )


def _build_profile(config: _ProfileConfig, sdk: Any) -> StrategyReductionProfile:
    fields = (
        config.profile_ref,
        config.subject,
        config.selector_ref,
        config.approved_target_scope_ref,
        config.account_ref,
        config.strategy_ref,
        config.run_id,
        config.service_id,
        config.instance_id,
        config.scope_ref,
    )
    if any(not _safe_text(value) or not _SAFE_REF.fullmatch(value) for value in fields):
        raise StrategyReductionControlError("DEPLOYMENT_INVALID")
    if (
        not _finite(config.not_before_utc)
        or not _finite(config.expires_at_utc)
        or config.expires_at_utc <= config.not_before_utc
        or type(config.wire_scope) is not dict
        or set(config.wire_scope) != _SCOPE_FIELDS
    ):
        raise StrategyReductionControlError("DEPLOYMENT_INVALID")
    identity = _parse_identity(config.client_identity, sdk, role=sdk.WireRole.SERVICE)
    peer = _parse_identity(config.peer_identity, sdk, role=sdk.WireRole.SERVICE)
    try:
        scope_values = dict(config.wire_scope)
        wire_scope = sdk.WireScope(**scope_values)
        if (
            wire_scope.account_ref != config.account_ref
            or tuple(wire_scope.account_refs)
            or wire_scope.strategy_ref != config.strategy_ref
            or wire_scope.run_id != config.run_id
            or wire_scope.manual_book_ref is not None
            or wire_scope.portfolio_ref is not None
            or wire_scope.group_id is not None
            or wire_scope.leg_id is not None
        ):
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        client_config = sdk.parse_service_config(config.client_config)
        public = client_config.to_public_dict()
        clients = public.get("clients")
        if (
            public.get("process_role") != "service"
            or type(clients) is not dict
            or set(clients) != {"execution"}
        ):
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        settings = clients["execution"].get("settings")
        bindings = settings.get("bindings") if type(settings) is dict else None
        if type(bindings) is not list or len(bindings) != 1:
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        client_binding = bindings[0]
        if (
            client_binding.get("mount") != _OWNER_MOUNT
            or client_binding.get("service_id") != config.service_id
            or client_binding.get("instance_id") != config.instance_id
            or client_binding.get("scope_ref") != config.scope_ref
            or client_binding.get("account_ref") != config.account_ref
        ):
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        communication = public.get("communication")
        profiles = communication.get("profiles") if type(communication) is dict else None
        if type(profiles) is not dict:
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        transport_profile = profiles.get(client_binding.get("transport_ref"))
        security_ref = (
            transport_profile.get("security_profile_ref")
            if type(transport_profile) is dict
            else None
        )
        if type(security_ref) is not str or set(config.curve_keys) != {security_ref}:
            raise StrategyReductionControlError("DEPLOYMENT_INVALID")
        key = config.curve_keys[security_ref]
        curves = {
            security_ref: sdk.ClientCurveKeys(
                _z85_bytes(key.server_key_z85),
                _z85_bytes(key.public_key_z85),
                _z85_bytes(key.secret_key_z85),
            )
        }
    except StrategyReductionControlError:
        raise
    except Exception:
        raise StrategyReductionControlError("DEPLOYMENT_INVALID") from None
    return StrategyReductionProfile(
        config=config,
        wire_scope=wire_scope,
        client_identity=identity,
        peer_identity=peer,
        client_config=client_config,
        curve_keys=curves,
    )


def _parse_identity(value: object, sdk: Any, *, role: Any) -> Any:
    if type(value) is not dict or set(value) != _IDENTITY_FIELDS:
        raise StrategyReductionControlError("DEPLOYMENT_INVALID")
    principal_ref = value["principal_ref"]
    actor_ref = value["actor_ref"]
    delegate_ref = value["delegate_ref"]
    if (
        not _safe_text(principal_ref)
        or not _SAFE_REF.fullmatch(principal_ref)
        or not _safe_text(actor_ref)
        or not _SAFE_REF.fullmatch(actor_ref)
        or (
            delegate_ref is not None
            and (not _safe_text(delegate_ref) or not _SAFE_REF.fullmatch(delegate_ref))
        )
    ):
        raise StrategyReductionControlError("DEPLOYMENT_INVALID")
    try:
        return sdk.WireIdentity(role, principal_ref, actor_ref, delegate_ref)
    except Exception:
        raise StrategyReductionControlError("DEPLOYMENT_INVALID") from None


def _scope_payload(scope: object) -> dict[str, object]:
    return {
        "execution_domain_ref": getattr(scope, "execution_domain_ref", None),
        "account_ref": getattr(scope, "account_ref", None),
        "account_refs": list(getattr(scope, "account_refs", ())),
        "strategy_ref": getattr(scope, "strategy_ref", None),
        "run_id": getattr(scope, "run_id", None),
        "manual_book_ref": getattr(scope, "manual_book_ref", None),
        "portfolio_ref": getattr(scope, "portfolio_ref", None),
        "group_id": getattr(scope, "group_id", None),
        "leg_id": getattr(scope, "leg_id", None),
    }


def _identity_refs(value: object) -> tuple[object, object, object]:
    if isinstance(value, Mapping):
        return value.get("principal_ref"), value.get("actor_ref"), value.get("delegate_ref")
    return (
        getattr(value, "principal_ref", None),
        getattr(value, "actor_ref", None),
        getattr(value, "delegate_ref", None),
    )


def _fixed_lookup(values: Mapping[str, Any], key: str) -> Any:
    try:
        return values[key]
    except (KeyError, TypeError):
        raise StrategyReductionControlError("PROFILE_SCOPE_MISMATCH") from None


def _z85_bytes(value: SecretStr) -> bytes:
    text = value.get_secret_value()
    if type(text) is not str or len(text) != 40 or any(char not in _Z85 for char in text):
        raise StrategyReductionControlError("DEPLOYMENT_INVALID")
    try:
        from zmq.utils import z85

        # The SDK's ClientCurveKeys contract is the 40-byte Z85 form consumed
        # by CurveClientCredentials and PyZMQ socket options. Decode once to
        # validate the configured key, but retain its encoded representation.
        z85.decode(text.encode("ascii"))
        return text.encode("ascii")
    except Exception:
        raise StrategyReductionControlError("DEPLOYMENT_INVALID") from None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate deployment key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite deployment number")


def _finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(float(value))


def _safe_text(value: object) -> bool:
    return type(value) is str and value == value.strip() and value.isprintable()


__all__ = [
    "StrategyReductionControlError",
    "StrategyReductionDeployment",
    "StrategyReductionProfile",
    "get_deployment_setting",
]
