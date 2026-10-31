"""Owner controls issued through the authenticated SDK service host.

AFI holds an operator-provisioned issuer grant and a constrained client
runtime. FREEZE and STOP_NEW use the signed Monitor ledger. CANCEL uses the
separately granted execution ``owner.cancel`` port and the same persistent
issuer/idempotency ledger; it never supplies order identifiers or constructs
cancellation policy locally. This module never opens a Risk database or
constructs a Risk policy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import sqlite3
import threading
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

_MAX_DEPLOYMENT_BYTES = 262_144
_MAX_BINDINGS = 128
_MAX_ISSUANCE_ROWS = 10_000
_COMMAND_TTL_SECONDS = 30.0
_MAX_IDEMPOTENCY_KEY_BYTES = 256
_CONTROL_HMAC_DOMAIN = b"bt-api-monitor.control-command.hmac.v1\0"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_COMMAND_ID_RE = re.compile(
    r"^afi-monitor-(?P<action>freeze|stop-new|cancel)-v1-[0-9a-f]{32}$"
)
_STOP_NEW_EFFECT_REF_RE = re.compile(r"^strategy-stop-new-v1:[0-9a-f]{64}$")
_Z85_ALPHABET = frozenset(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _CurveKeyConfig(_StrictModel):
    server_key_z85: SecretStr = Field(repr=False, exclude=True)
    public_key_z85: SecretStr = Field(repr=False, exclude=True)
    secret_key_z85: SecretStr = Field(repr=False, exclude=True)


class _BindingConfig(_StrictModel):
    subject: str = Field(min_length=1, max_length=256)
    afi_account_id: str = Field(min_length=1, max_length=128)
    portfolio_ref: str | None = Field(default=None, max_length=128)
    account_id: str = Field(min_length=1, max_length=128)
    mode: str = Field(min_length=1, max_length=128)
    command_scope: str = Field(min_length=1, max_length=256)
    issuer: str = Field(min_length=1, max_length=128)
    key_ref: str = Field(min_length=1, max_length=128)
    key_material_b64: SecretStr = Field(repr=False, exclude=True)
    issuer_policy_version: str = Field(min_length=1, max_length=64)
    authority_receipt_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    not_before_utc: float
    expires_at_utc: float
    issuer_sequence_start: int = Field(default=0, ge=0)
    allowed_actions: list[Literal["FREEZE", "STOP_NEW", "CANCEL"]] = Field(
        min_length=1, max_length=2
    )
    service_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)
    scope_ref: str = Field(min_length=1, max_length=128)
    wire_account_ref: str = Field(min_length=1, max_length=256)
    wire_portfolio_ref: str | None = Field(default=None, max_length=128)
    wire_scope: dict[str, Any] = Field(repr=False)
    client_identity: dict[str, str]
    peer_identity: dict[str, str]
    client_config: dict[str, Any] = Field(repr=False)
    curve_keys: dict[str, _CurveKeyConfig] = Field(repr=False, exclude=True)

    @field_validator(
        "subject",
        "afi_account_id",
        "account_id",
        "mode",
        "command_scope",
        "issuer",
        "key_ref",
        "issuer_policy_version",
        "service_id",
        "instance_id",
        "scope_ref",
        "wire_account_ref",
    )
    @classmethod
    def _required_trimmed_text(cls, value: str) -> str:
        if value != value.strip() or not value.isprintable():
            raise ValueError("control binding text must be trimmed printable text")
        return value

    @field_validator("portfolio_ref", "wire_portfolio_ref")
    @classmethod
    def _optional_trimmed_text(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or not value.isprintable()):
            raise ValueError("portfolio reference must be trimmed printable text")
        return value


class _DeploymentConfig(_StrictModel):
    schema_version: Literal[1]
    deployment_id: str = Field(min_length=1, max_length=128)
    deployment_version: str = Field(min_length=1, max_length=64)
    not_before_utc: float
    expires_at_utc: float
    issuer_state_path: str = Field(min_length=1, max_length=1024)
    bindings: list[_BindingConfig] = Field(min_length=1, max_length=_MAX_BINDINGS)

    @field_validator("deployment_id", "deployment_version", "issuer_state_path")
    @classmethod
    def _trimmed_text(cls, value: str) -> str:
        if value != value.strip() or not value.isprintable():
            raise ValueError("control deployment text must be trimmed printable text")
        return value


class OwnerControlRequest(_StrictModel):
    """The request chooses an action only; it cannot carry authority or secrets."""

    action: Literal["FREEZE", "STOP_NEW", "CANCEL", "DRAIN", "CLOSE"]
    portfolio_ref: str | None = None

    @field_validator("portfolio_ref")
    @classmethod
    def _portfolio_ref(cls, value: str | None) -> str | None:
        if value is not None and (
            not value or value != value.strip() or len(value) > 128 or not value.isprintable()
        ):
            raise ValueError("portfolio reference is invalid")
        return value

    @model_validator(mode="after")
    def _cancel_has_no_client_selected_portfolio(self) -> OwnerControlRequest:
        if self.action == "CANCEL" and self.portfolio_ref is not None:
            raise ValueError("CANCEL scope is fixed by the server binding")
        return self


class OwnerControlError(ValueError):
    """Finite public error code; never contains deployment data or secrets."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class OwnerControlBinding:
    config: _BindingConfig = field(repr=False)
    binding_id: str
    wire_scope: Any = field(repr=False)
    client_identity: Any = field(repr=False)
    peer_identity: Any = field(repr=False)
    client_config: Any = field(repr=False)
    curve_keys: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _IssuedCommand:
    command_id: str
    sequence: int
    expires_at: float
    payload: bytes = field(repr=False)
    signature: bytes = field(repr=False)


class OwnerControlDeployment:
    """Immutable operator grant and issuer-side idempotency store."""

    def __init__(self, config: _DeploymentConfig, bindings: tuple[OwnerControlBinding, ...]):
        self._config = config
        self.bindings = bindings
        self._state_path = Path(config.issuer_state_path)
        self._by_id = {binding.binding_id: binding for binding in bindings}
        self._lock = threading.RLock()

    @classmethod
    def from_secret(cls, value: SecretStr | str | None) -> OwnerControlDeployment | None:
        if isinstance(value, SecretStr):
            raw = value.get_secret_value()
        elif type(value) is str:
            raw = value
        elif value is None:
            raw = ""
        else:
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if not raw:
            return None
        try:
            if len(raw.encode("utf-8", errors="strict")) > _MAX_DEPLOYMENT_BYTES:
                raise OwnerControlError("DEPLOYMENT_INVALID")
            json.loads(raw, object_pairs_hook=_reject_duplicate_pairs, parse_constant=_reject_constant)
            config = _DeploymentConfig.model_validate_json(raw)
            _validate_timestamp(config.not_before_utc)
            _validate_timestamp(config.expires_at_utc)
            if config.expires_at_utc <= config.not_before_utc:
                raise OwnerControlError("DEPLOYMENT_INVALID")
            sdk = _load_sdk()
            bindings = tuple(_build_binding(item, sdk) for item in config.bindings)
            if len({item.config.issuer for item in bindings}) != len(bindings):
                # A ledger row records the issuer, not a wire caller. A unique
                # issuer per actor prevents same-route status disclosure.
                raise OwnerControlError("DEPLOYMENT_INVALID")
            if len({item.binding_id for item in bindings}) != len(bindings):
                raise OwnerControlError("DEPLOYMENT_INVALID")
            state_path = Path(config.issuer_state_path)
            if not state_path.is_absolute() or state_path.parent.is_symlink():
                raise OwnerControlError("DEPLOYMENT_INVALID")
            if state_path.exists() and (state_path.is_symlink() or not state_path.is_file()):
                raise OwnerControlError("DEPLOYMENT_INVALID")
            return cls(config, bindings)
        except OwnerControlError:
            raise
        except (ArithmeticError, OSError, UnicodeError, ValueError, TypeError, ValidationError, RecursionError):
            raise OwnerControlError("DEPLOYMENT_INVALID") from None

    def binding_for(
        self,
        *,
        subject: str,
        afi_account_id: str,
        portfolio_ref: str | None,
        action: str | None = None,
        require_active: bool = True,
    ) -> OwnerControlBinding | None:
        if action is not None and (
            type(action) is not str
            or action not in {"FREEZE", "STOP_NEW", "CANCEL"}
        ):
            raise OwnerControlError("CONTROL_ACTION_INVALID")
        now = datetime.now(UTC).timestamp()
        if require_active and not self._config.not_before_utc <= now < self._config.expires_at_utc:
            raise OwnerControlError("DEPLOYMENT_INACTIVE_OR_EXPIRED")
        matches = [
            binding
            for binding in self.bindings
            if binding.config.subject == subject
            and binding.config.afi_account_id == afi_account_id
            and binding.config.portfolio_ref == portfolio_ref
            and binding.config.wire_portfolio_ref == portfolio_ref
            and (action is None or action in binding.config.allowed_actions)
            and (
                not require_active
                or binding.config.not_before_utc <= now < binding.config.expires_at_utc
            )
        ]
        if len(matches) > 1:
            raise OwnerControlError("DEPLOYMENT_AMBIGUOUS")
        return matches[0] if matches else None

    def submit_freeze(
        self,
        binding: OwnerControlBinding,
        *,
        subject: str,
        alert_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        return self.submit_control(
            binding,
            action="FREEZE",
            subject=subject,
            alert_id=alert_id,
            idempotency_key=idempotency_key,
        )

    def submit_control(
        self,
        binding: OwnerControlBinding,
        *,
        action: str,
        subject: str,
        alert_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        if not any(item is binding for item in self.bindings):
            raise OwnerControlError("CONTROL_BINDING_INVALID")
        if subject != binding.config.subject:
            raise OwnerControlError("CONTROL_BINDING_INVALID")
        if (
            type(action) is not str
            or action not in {"FREEZE", "STOP_NEW", "CANCEL"}
            or action not in binding.config.allowed_actions
        ):
            raise OwnerControlError("OWNER_CONTROL_NOT_AUTHORIZED")
        _validate_idempotency_key(idempotency_key)
        with self._lock:
            issued = self._reserve_or_replay(
                binding,
                action=action,
                subject=subject,
                alert_id=alert_id,
                idempotency_key=idempotency_key,
            )
            arguments = {
                "schema_version": 1,
                "payload_b64": base64.b64encode(issued.payload).decode("ascii"),
                "signature_b64": base64.b64encode(issued.signature).decode("ascii"),
            }
            if action == "CANCEL":
                row = self._issuance_row(issued.command_id)
                if row is None:
                    raise OwnerControlError("ISSUER_STATE_UNAVAILABLE")
                cached = _decode_persisted_projection(
                    row["owner_projection_json"],
                    issued.command_id,
                )
                projection = (
                    cached
                    if cached is not None and cached.get("owner_final") is True
                    else self._query_cancel_owner(binding, issued.command_id)
                )
            else:
                projection = self._query_status(
                    binding,
                    issued.command_id,
                    action=action,
                    submit_arguments=arguments
                    if datetime.now(UTC).timestamp() < issued.expires_at
                    else None,
                )
            self._record_final(issued.command_id, projection)
            return projection

    def status_for_command(
        self, command_id: str, *, subject: str
    ) -> tuple[OwnerControlBinding, str, dict[str, Any]] | None:
        if type(command_id) is not str:
            return None
        command_match = _COMMAND_ID_RE.fullmatch(command_id)
        if command_match is None:
            return None
        with self._lock:
            row = self._issuance_row(command_id)
            if row is None or row["subject"] != subject:
                return None
            action = {
                "freeze": "FREEZE",
                "stop-new": "STOP_NEW",
                "cancel": "CANCEL",
            }[command_match.group("action")]
            try:
                raw_payload = row["payload"]
                claims = json.loads(bytes(raw_payload).decode("utf-8", errors="strict"))
            except (TypeError, ValueError, UnicodeError, json.JSONDecodeError):
                raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None
            expected_wire_action = {
                "FREEZE": "freeze",
                "STOP_NEW": "stop_new",
                "CANCEL": "cancel",
            }[action]
            if (
                not isinstance(claims, Mapping)
                or claims.get("command_id") != command_id
                or claims.get("action") != expected_wire_action
            ):
                raise OwnerControlError("ISSUER_STATE_UNAVAILABLE")
            binding = self._by_id.get(str(row["binding_id"]))
            if binding is None:
                return None
            if action == "CANCEL":
                connection_projection = row["owner_projection_json"]
                cached = _decode_persisted_projection(connection_projection, command_id)
                if cached is not None and cached.get("owner_final") is True:
                    return binding, str(row["alert_id"]), cached
                try:
                    projection = self._query_cancel_owner(binding, command_id)
                except OwnerControlError:
                    if cached is None:
                        projection = _cancel_unknown_projection(
                            command_id,
                            action="cancel",
                            deployment_version=self._config.deployment_version,
                        )
                    else:
                        projection = cached
            else:
                projection = self._query_status(binding, command_id, action=action)
            self._record_final(command_id, projection)
            return binding, str(row["alert_id"]), projection

    def _query_status(
        self,
        binding: OwnerControlBinding,
        command_id: str,
        *,
        action: str,
        submit_arguments: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        sdk = _load_sdk()
        runtime = sdk.ServiceClientRuntime(
            binding.client_config,
            identity=binding.client_identity,
            scope_resolver=lambda scope_ref: _fixed_lookup(
                {binding.config.scope_ref: binding.wire_scope}, scope_ref
            ),
            peer_resolver=lambda service_id: _fixed_lookup(
                {binding.config.service_id: binding.peer_identity}, service_id
            ),
            transport_factory=sdk.ZmqTransportFactory(binding.curve_keys),
            requested_operations={
                "application.monitor": frozenset(
                    {"monitor.control", "monitor.control_status"}
                )
            },
        )
        try:
            registered = runtime.start()
            if registered.degraded_count or len(registered.bindings) != 1:
                raise OwnerControlError("OWNER_SERVICE_UNAVAILABLE")
            if submit_arguments is not None:
                try:
                    runtime.call("application.monitor", "monitor.control", submit_arguments)
                except sdk.ServiceRuntimeError as error:
                    # The request may have reached the owner before a reply
                    # failed. Only the status RPC may settle that uncertainty.
                    if error.code in {"SCOPE_DENIED", "ACTION_NOT_GRANTED"}:
                        raise OwnerControlError("OWNER_CONTROL_NOT_AUTHORIZED") from None
            status = runtime.call(
                "application.monitor",
                "monitor.control_status",
                {"schema_version": 1, "command_id": command_id},
            )
            projection = _validate_owner_projection(status, command_id, action=action)
            return projection | {
                "action": "freeze" if action == "FREEZE" else "stop_new",
                "deployment_version": self._config.deployment_version,
            }
        except OwnerControlError:
            raise
        except Exception:
            raise OwnerControlError("OWNER_SERVICE_UNAVAILABLE") from None
        finally:
            try:
                runtime.close()
            except Exception:
                # A client cleanup failure never fabricates a terminal owner
                # result; the next status call remains available for recovery.
                raise OwnerControlError("OWNER_CLIENT_CLEANUP_UNCERTAIN") from None

    def _query_cancel_owner(
        self, binding: OwnerControlBinding, command_id: str
    ) -> dict[str, Any]:
        """Read/submit one durable owner.cancel batch using its same command id."""
        sdk = _load_sdk()
        runtime = sdk.ServiceClientRuntime(
            binding.client_config,
            identity=binding.client_identity,
            scope_resolver=lambda scope_ref: _fixed_lookup(
                {binding.config.scope_ref: binding.wire_scope}, scope_ref
            ),
            peer_resolver=lambda service_id: _fixed_lookup(
                {binding.config.service_id: binding.peer_identity}, service_id
            ),
            transport_factory=sdk.ZmqTransportFactory(binding.curve_keys),
            requested_operations={
                "upstream.owner_control": frozenset({"owner.cancel"})
            },
        )
        projection: dict[str, Any]
        try:
            registered = runtime.start()
            if registered.degraded_count or len(registered.bindings) != 1:
                return _cancel_unknown_projection(
                    command_id,
                    action="cancel",
                    deployment_version=self._config.deployment_version,
                )
            try:
                reply = runtime.call(
                    "upstream.owner_control",
                    "owner.cancel",
                    {"command_id": command_id},
                    account_ref=binding.wire_scope.account_ref,
                    scope_ref=binding.config.scope_ref,
                )
            except sdk.ServiceRuntimeError as error:
                if error.code in {"SCOPE_DENIED", "ACTION_NOT_GRANTED", "ROLE_NOT_AUTHORIZED"}:
                    return _cancel_rejected_projection(
                        command_id,
                        action="cancel",
                        deployment_version=self._config.deployment_version,
                        owner_code=error.code,
                    )
                return _cancel_unknown_projection(
                    command_id,
                    action="cancel",
                    deployment_version=self._config.deployment_version,
                )
            if isinstance(reply, Mapping) and reply.get("code") in {
                "SCOPE_DENIED",
                "ACTION_NOT_GRANTED",
                "ROLE_NOT_AUTHORIZED",
            }:
                return _cancel_rejected_projection(
                    command_id,
                    action="cancel",
                    deployment_version=self._config.deployment_version,
                    owner_code=str(reply["code"]),
                )
            projection = _validate_owner_cancel_reply(
                reply,
                command_id,
                binding=binding,
                deployment_version=self._config.deployment_version,
            )
        except OwnerControlError:
            return _cancel_unknown_projection(
                command_id,
                action="cancel",
                deployment_version=self._config.deployment_version,
            )
        except Exception:
            return _cancel_unknown_projection(
                command_id,
                action="cancel",
                deployment_version=self._config.deployment_version,
            )
        finally:
            try:
                runtime.close()
            except Exception:
                # The owner reply is already durable. A client close failure
                # cannot turn an acknowledged batch into a terminal result or
                # erase its per-order receipt.
                pass
        return projection

    def _reserve_or_replay(
        self,
        binding: OwnerControlBinding,
        *,
        action: str,
        subject: str,
        alert_id: str,
        idempotency_key: str,
    ) -> _IssuedCommand:
        config = binding.config
        now = datetime.now(UTC).timestamp()
        if not (
            self._config.not_before_utc <= now < self._config.expires_at_utc
            and config.not_before_utc <= now < config.expires_at_utc
        ):
            raise OwnerControlError("DEPLOYMENT_INACTIVE_OR_EXPIRED")
        action_slug = {"FREEZE": "freeze", "STOP_NEW": "stop-new", "CANCEL": "cancel"}[
            action
        ]
        wire_action = {
            "FREEZE": "freeze",
            "STOP_NEW": "stop_new",
            "CANCEL": "cancel",
        }[action]
        key_digest = hashlib.sha256(
            (subject + "\0" + binding.binding_id + "\0" + idempotency_key).encode("utf-8")
        ).hexdigest()
        facts = {
            "action": action,
            "afi_account_id": config.afi_account_id,
            "alert_id": alert_id,
            "binding_id": binding.binding_id,
            "deployment_id": self._config.deployment_id,
            "deployment_version": self._config.deployment_version,
            "issuer": config.issuer,
            "portfolio_ref": config.portfolio_ref,
            "subject": subject,
        }
        request_digest = _sha256_json(facts)
        connection = self._connect_issuer_state()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM afi_monitor_control_issuance WHERE issuer = ? AND idempotency_digest = ?",
                (config.issuer, key_digest),
            ).fetchone()
            if existing is not None:
                if existing["request_digest"] != request_digest:
                    raise OwnerControlError("IDEMPOTENCY_KEY_CONFLICT")
                connection.commit()
                return _IssuedCommand(
                    str(existing["command_id"]),
                    int(existing["issuer_sequence"]),
                    float(existing["expires_at"]),
                    bytes(existing["payload"]),
                    bytes(existing["signature"]),
                )
            unresolved = connection.execute(
                "SELECT 1 FROM afi_monitor_control_issuance "
                "WHERE issuer = ? AND owner_final = 0 "
                "AND (owner_status IS NULL OR owner_status <> 'expired') LIMIT 1",
                (config.issuer,),
            ).fetchone()
            if unresolved is not None:
                raise OwnerControlError("ISSUER_COMMAND_UNRESOLVED")
            count = connection.execute(
                "SELECT COUNT(*) FROM afi_monitor_control_issuance WHERE issuer = ?",
                (config.issuer,),
            ).fetchone()[0]
            if int(count) >= _MAX_ISSUANCE_ROWS:
                raise OwnerControlError("ISSUER_REPLAY_CAPACITY")
            previous = connection.execute(
                "SELECT MAX(issuer_sequence) FROM afi_monitor_control_issuance WHERE issuer = ?",
                (config.issuer,),
            ).fetchone()[0]
            sequence = max(config.issuer_sequence_start, int(previous or 0)) + 1
            command_id = f"afi-monitor-{action_slug}-v1-" + uuid.uuid4().hex
            expires_at = min(
                now + _COMMAND_TTL_SECONDS,
                config.expires_at_utc,
                self._config.expires_at_utc,
            )
            if expires_at <= now:
                raise OwnerControlError("DEPLOYMENT_INACTIVE_OR_EXPIRED")
            claims = {
                "schema_version": 1,
                "key_id": config.key_ref,
                "issuer": config.issuer,
                "command_id": command_id,
                "account_id": config.account_id,
                "mode": config.mode,
                "scope": config.command_scope,
                "action": wire_action,
                "reason": {
                    "FREEZE": "AFI monitoring alert owner freeze",
                    "STOP_NEW": "AFI monitoring alert strategy stop new",
                    "CANCEL": "AFI monitoring alert exact-run owner cancellation",
                }[action],
                "receipt_digest": config.authority_receipt_digest,
                "issued_at": now,
                "expires_at": expires_at,
                "issuer_sequence": sequence,
                "manual_resume_authorized": False,
            }
            payload = json.dumps(
                claims,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
            key_bytes = _decode_secret(config.key_material_b64, minimum=32)
            key_id = config.key_ref.encode("ascii")
            signature = hmac.new(
                key_bytes,
                _CONTROL_HMAC_DOMAIN + len(key_id).to_bytes(2, "big") + key_id + payload,
                hashlib.sha256,
            ).digest()
            connection.execute(
                """INSERT INTO afi_monitor_control_issuance (
                    issuer, idempotency_digest, request_digest, command_id,
                    issuer_sequence, subject, binding_id, afi_account_id,
                    portfolio_ref, alert_id, expires_at, payload, signature,
                    owner_final, owner_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL)""",
                (
                    config.issuer,
                    key_digest,
                    request_digest,
                    command_id,
                    sequence,
                    subject,
                    binding.binding_id,
                    config.afi_account_id,
                    config.portfolio_ref,
                    alert_id,
                    expires_at,
                    payload,
                    signature,
                ),
            )
            connection.commit()
            return _IssuedCommand(command_id, sequence, expires_at, payload, signature)
        except OwnerControlError:
            connection.rollback()
            raise
        except (OSError, sqlite3.Error, TypeError, ValueError):
            connection.rollback()
            raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None
        finally:
            connection.close()

    def _connect_issuer_state(self) -> sqlite3.Connection:
        path = self._state_path
        if path.is_symlink() or (path.exists() and not path.is_file()) or not path.parent.is_dir():
            raise OwnerControlError("ISSUER_STATE_UNAVAILABLE")
        try:
            connection = sqlite3.connect(path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute(
                """CREATE TABLE IF NOT EXISTS afi_monitor_control_issuance (
                    issuer TEXT NOT NULL,
                    idempotency_digest TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    command_id TEXT NOT NULL UNIQUE,
                    issuer_sequence INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    binding_id TEXT NOT NULL,
                    afi_account_id TEXT NOT NULL,
                    portfolio_ref TEXT,
                    alert_id TEXT NOT NULL,
                    expires_at REAL NOT NULL,
                    payload BLOB NOT NULL,
                    signature BLOB NOT NULL,
                    owner_final INTEGER NOT NULL CHECK(owner_final IN (0, 1)),
                    owner_status TEXT,
                    owner_projection_json TEXT,
                    PRIMARY KEY (issuer, idempotency_digest),
                    UNIQUE (issuer, issuer_sequence)
                )"""
            )
            columns = {
                str(row[1])
                for row in connection.execute(
                    "PRAGMA table_info(afi_monitor_control_issuance)"
                ).fetchall()
            }
            if "owner_projection_json" not in columns:
                connection.execute(
                    "ALTER TABLE afi_monitor_control_issuance "
                    "ADD COLUMN owner_projection_json TEXT"
                )
            return connection
        except (OSError, sqlite3.Error):
            raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None

    def _issuance_row(self, command_id: str) -> sqlite3.Row | None:
        connection = self._connect_issuer_state()
        try:
            return connection.execute(
                "SELECT * FROM afi_monitor_control_issuance WHERE command_id = ?",
                (command_id,),
            ).fetchone()
        except sqlite3.Error:
            raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None
        finally:
            connection.close()

    def _record_final(self, command_id: str, projection: Mapping[str, Any]) -> None:
        final = projection.get("owner_final") is True
        try:
            projection_json = json.dumps(
                dict(projection),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
        except (TypeError, ValueError):
            raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None
        connection = self._connect_issuer_state()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT owner_final FROM afi_monitor_control_issuance WHERE command_id = ?",
                (command_id,),
            ).fetchone()
            if existing is None:
                raise OwnerControlError("ISSUER_STATE_UNAVAILABLE")
            if existing["owner_final"] == 1:
                connection.commit()
                return
            connection.execute(
                """UPDATE afi_monitor_control_issuance
                   SET owner_final = ?, owner_status = ?, owner_projection_json = ?
                   WHERE command_id = ?""",
                (1 if final else 0, projection.get("status"), projection_json, command_id),
            )
            connection.commit()
        except sqlite3.Error:
            connection.rollback()
            raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None
        except OwnerControlError:
            connection.rollback()
            raise
        finally:
            connection.close()


def control_implementation_status(action: str) -> str:
    if action == "FREEZE":
        return "FREEZE_SUPPORTED"
    if action == "STOP_NEW":
        return "STOP_NEW_SUPPORTED"
    if action == "CANCEL":
        return "CANCEL_SUPPORTED"
    if action == "DRAIN":
        return "DRAIN_PENDING_IMPLEMENTATION"
    if action == "CLOSE":
        return "CLOSE_PENDING_DIM04_EXECUTION_JOURNAL_COORDINATION"
    raise OwnerControlError("CONTROL_ACTION_INVALID")


def get_deployment_setting() -> SecretStr:
    """Read the separately configured owner-control deployment setting."""

    from app.config import get_settings

    return get_settings().SERVICE_MONITOR_CONTROL_DEPLOYMENT_JSON


def _load_sdk() -> Any:
    try:
        from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
        from bt_api_py.service_config import parse_client_config, parse_service_config
        from bt_api_py.service_runtime import (
            ClientCurveKeys,
            ServiceClientRuntime,
            ZmqTransportFactory,
        )
    except ImportError:
        raise OwnerControlError("SDK_NOT_INSTALLED") from None
    return type(
        "_Sdk",
        (),
        {
            "WireIdentity": WireIdentity,
            "WireRole": WireRole,
            "WireScope": WireScope,
            "parse_client_config": parse_client_config,
            "parse_service_config": parse_service_config,
            "ClientCurveKeys": ClientCurveKeys,
            "ServiceClientRuntime": ServiceClientRuntime,
            "ZmqTransportFactory": ZmqTransportFactory,
        },
    )


def _build_binding(config: _BindingConfig, sdk: Any) -> OwnerControlBinding:
    _validate_timestamp(config.not_before_utc)
    _validate_timestamp(config.expires_at_utc)
    if config.expires_at_utc <= config.not_before_utc:
        raise OwnerControlError("DEPLOYMENT_INVALID")
    if (
        not config.allowed_actions
        or len(set(config.allowed_actions)) != len(config.allowed_actions)
        or _KEY_ID_RE.fullmatch(config.key_ref) is None
    ):
        raise OwnerControlError("DEPLOYMENT_INVALID")
    _decode_secret(config.key_material_b64, minimum=32)
    cancel_binding = config.allowed_actions == ["CANCEL"]
    client_role = sdk.WireRole.SERVICE if cancel_binding else sdk.WireRole.APPLICATION_CLIENT
    identity = _parse_identity(config.client_identity, sdk, role=client_role)
    peer = _parse_identity(config.peer_identity, sdk, role=sdk.WireRole.SERVICE)
    if identity.delegate_ref is None:
        raise OwnerControlError("DEPLOYMENT_INVALID")
    try:
        scope_values = dict(config.wire_scope)
        scope_keys = {
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
        if not {"execution_domain_ref", "account_ref"} <= set(scope_values):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if set(scope_values) - scope_keys:
            raise OwnerControlError("DEPLOYMENT_INVALID")
        scope_values.setdefault("account_refs", ())
        wire_scope = sdk.WireScope(**scope_values)
        if "CANCEL" in config.allowed_actions and (
            wire_scope.account_ref is None
            or wire_scope.account_refs
            or wire_scope.strategy_ref is None
            or wire_scope.run_id is None
            or wire_scope.manual_book_ref is not None
            or wire_scope.portfolio_ref is not None
            or wire_scope.group_id is not None
            or wire_scope.leg_id is not None
            or config.portfolio_ref is not None
            or config.wire_portfolio_ref is not None
        ):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if "CANCEL" in config.allowed_actions and config.command_scope != (
            f"strategy:{wire_scope.strategy_ref}:{wire_scope.run_id}:cancel"
        ):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if "STOP_NEW" in config.allowed_actions and (
            wire_scope.account_ref is None
            or wire_scope.account_refs
            or wire_scope.strategy_ref is None
            or wire_scope.run_id is None
            or wire_scope.manual_book_ref is not None
            or wire_scope.group_id is not None
            or wire_scope.leg_id is not None
        ):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if "STOP_NEW" in config.allowed_actions and config.command_scope != (
            f"strategy:{wire_scope.strategy_ref}:{wire_scope.run_id}:stop_new"
        ):
            # The issuer's readable scope label is a secondary operator check.
            # The exact WireScope is separately pinned in the deployment and
            # Monitor owner route; this label is never parsed to select a run.
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if "CANCEL" in config.allowed_actions and len(config.allowed_actions) != 1:
            # A CANCEL resource grant is a service-role execution binding;
            # monitor controls use an application-client mount. Keep them in
            # separately scoped operator bindings.
            raise OwnerControlError("DEPLOYMENT_INVALID")
        client_config = (
            sdk.parse_service_config(config.client_config)
            if cancel_binding
            else sdk.parse_client_config(config.client_config)
        )
        public_config = client_config.to_public_dict()
        clients = public_config.get("clients")
        expected_role = "service" if cancel_binding else "application_client"
        expected_client = "execution" if cancel_binding else "monitor"
        expected_mount = "upstream.owner_control" if cancel_binding else "application.monitor"
        if (
            public_config.get("process_role") != expected_role
            or type(clients) is not dict
            or set(clients) != {expected_client}
        ):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        client = clients[expected_client]
        settings = client.get("settings") if type(client) is dict else None
        bindings = settings.get("bindings") if type(settings) is dict else None
        if type(bindings) is not list or len(bindings) != 1:
            raise OwnerControlError("DEPLOYMENT_INVALID")
        client_binding = bindings[0]
        if (
            client_binding.get("mount") != expected_mount
            or client_binding.get("service_id") != config.service_id
            or client_binding.get("instance_id") != config.instance_id
            or client_binding.get("scope_ref") != config.scope_ref
            or (
                cancel_binding
                and client_binding.get("account_ref") != config.wire_account_ref
            )
        ):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        if (
            wire_scope.account_ref != config.wire_account_ref
            or wire_scope.portfolio_ref != config.wire_portfolio_ref
            or config.portfolio_ref != config.wire_portfolio_ref
        ):
            raise OwnerControlError("DEPLOYMENT_INVALID")
        communication = public_config.get("communication")
        profiles = communication.get("profiles") if type(communication) is dict else None
        if type(profiles) is not dict:
            raise OwnerControlError("DEPLOYMENT_INVALID")
        transport_ref = client_binding.get("transport_ref")
        profile = profiles.get(transport_ref)
        security_ref = profile.get("security_profile_ref") if type(profile) is dict else None
        if type(security_ref) is not str or set(config.curve_keys) != {security_ref}:
            raise OwnerControlError("DEPLOYMENT_INVALID")
        keys_config = config.curve_keys[security_ref]
        curves = {
            security_ref: sdk.ClientCurveKeys(
                _z85_bytes(keys_config.server_key_z85),
                _z85_bytes(keys_config.public_key_z85),
                _z85_bytes(keys_config.secret_key_z85),
            )
        }
    except OwnerControlError:
        raise
    except Exception:
        raise OwnerControlError("DEPLOYMENT_INVALID") from None
    binding_id = _sha256_json(
        {
            "account_id": config.account_id,
            "allowed_actions": sorted(config.allowed_actions),
            "afi_account_id": config.afi_account_id,
            "issuer": config.issuer,
            "portfolio_ref": config.portfolio_ref,
            "scope_ref": config.scope_ref,
            "subject": config.subject,
            "wire_scope": scope_values,
        }
    )
    return OwnerControlBinding(
        config=config,
        binding_id=binding_id,
        wire_scope=wire_scope,
        client_identity=identity,
        peer_identity=peer,
        client_config=client_config,
        curve_keys=curves,
    )


def _parse_identity(value: Mapping[str, str], sdk: Any, *, role: Any) -> Any:
    if type(value) is not dict or set(value) != {"principal_ref", "actor_ref", "delegate_ref"}:
        raise OwnerControlError("DEPLOYMENT_INVALID")
    if any(type(item) is not str or not item or item != item.strip() for item in value.values()):
        raise OwnerControlError("DEPLOYMENT_INVALID")
    try:
        return sdk.WireIdentity(role, value["principal_ref"], value["actor_ref"], value["delegate_ref"])
    except Exception:
        raise OwnerControlError("DEPLOYMENT_INVALID") from None


def _validate_owner_projection(
    value: Mapping[str, Any],
    command_id: str,
    *,
    action: str,
) -> dict[str, Any]:
    fields = {
        "command_id",
        "status",
        "outcome",
        "effect_ref",
        "effect_result",
        "request_recorded",
        "owner_final",
        "reconciliation_required",
    }
    if (
        action not in {"FREEZE", "STOP_NEW"}
        or not isinstance(value, Mapping)
        or set(value) != fields
        or value.get("command_id") != command_id
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    status = value.get("status")
    if (
        value.get("request_recorded") is not True
        or type(value.get("owner_final")) is not bool
        or type(value.get("reconciliation_required")) is not bool
        or type(status) is not str
        or status not in {"pending", "claimed", "acknowledged", "rejected", "expired", "unknown"}
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    outcome = value.get("outcome")
    if status in {"pending", "claimed"}:
        expected_reconciliation = status == "claimed"
        if (
            value["owner_final"]
            or outcome is not None
            or value.get("effect_ref") is not None
            or value.get("effect_result") is not None
            or value["reconciliation_required"] is not expected_reconciliation
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    elif status == "unknown":
        if (
            value["owner_final"]
            or outcome != "unknown"
            or value.get("effect_ref") is not None
            or value.get("effect_result") is not None
            or value["reconciliation_required"] is not True
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    elif status == "acknowledged":
        effect = value.get("effect_result")
        common_applied = (
            value["owner_final"] is True
            and outcome == "applied"
            and value["reconciliation_required"] is False
            and isinstance(effect, Mapping)
        )
        if action == "FREEZE":
            effect_fields = {
                "action",
                "cause_id",
                "activation_status",
                "cause_active",
                "has_other_active_freezes",
                "risk_state",
            }
            if (
                not common_applied
                or set(effect) != effect_fields
                or effect.get("action") != "freeze"
                or type(effect.get("cause_id")) is not str
                or not effect.get("cause_id")
                or value.get("effect_ref") != effect.get("cause_id")
                or type(effect.get("activation_status")) is not str
                or type(effect.get("cause_active")) is not bool
                or type(effect.get("has_other_active_freezes")) is not bool
            ):
                raise OwnerControlError("OWNER_RECEIPT_INVALID")
            expected_state = {
                "CREATED": (True, "active"),
                "ALREADY_ACTIVE": (True, "active"),
                "ALREADY_RESOLVED": (False, "resolved"),
            }.get(effect["activation_status"])
            if expected_state is None or (
                effect["cause_active"], effect["risk_state"]
            ) != expected_state:
                raise OwnerControlError("OWNER_RECEIPT_INVALID")
        else:
            effect_ref = value.get("effect_ref")
            if (
                not common_applied
                or set(effect) != {"action", "result"}
                or effect.get("action") != "stop_new"
                or type(effect.get("result")) is not str
                or effect.get("result") not in {"fenced", "already_fenced"}
                or type(effect_ref) is not str
                or _STOP_NEW_EFFECT_REF_RE.fullmatch(effect_ref) is None
            ):
                raise OwnerControlError("OWNER_RECEIPT_INVALID")
    elif status == "rejected":
        if (
            value["owner_final"] is not True
            or outcome != "rejected"
            or value["reconciliation_required"] is not False
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
        effect = value.get("effect_result")
        if action == "FREEZE":
            if value.get("effect_ref") is not None or effect is not None:
                raise OwnerControlError("OWNER_RECEIPT_INVALID")
        elif (
            value.get("effect_ref") is not None
            or not isinstance(effect, Mapping)
            or set(effect) != {"action", "result"}
            or effect.get("action") != "stop_new"
            or effect.get("result") not in {"run_not_active", "migration_write_disabled"}
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    elif status == "expired":
        # The durable Monitor ledger can expire an unclaimed command without
        # an owner effect. It is terminal for issuer sequencing, but it is not
        # an owner-applied result and must carry no effect receipt.
        if (
            value["owner_final"] is not False
            or outcome is not None
            or value.get("effect_ref") is not None
            or value.get("effect_result") is not None
            or value["reconciliation_required"] is not False
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
    projection = dict(value)
    if status == "acknowledged":
        projection["effect_result"] = dict(value["effect_result"])
    return projection


_CANCEL_REPLY_CODES = {
    "APPLIED": "OWNER_CANCEL_APPLIED",
    "ACKNOWLEDGED": "OWNER_CANCEL_ACKNOWLEDGED",
    "PARTIAL": "OWNER_CANCEL_PARTIAL",
    "PENDING": "OWNER_CANCEL_PENDING",
    "UNKNOWN": "OWNER_CANCEL_UNKNOWN",
    "NO_EFFECT": "OWNER_CANCEL_NO_EFFECT",
}
_CANCEL_STATES = {
    "PENDING_ADMISSION",
    "PENDING_DISPATCH",
    "DISPATCHING",
    "ACKED",
    "PARTIALLY_FILLED",
    "FILLED",
    "CANCELLED",
    "REJECTED",
    "BLOCKED",
    "UNKNOWN",
}
_CANCEL_DECISIONS = {
    "READY",
    "EXISTING_CANCEL",
    "UNKNOWN",
    "UNRESOLVED",
    "PENDING",
    "ALREADY_CANCELLED",
    "ALREADY_TERMINAL",
}
_CANCEL_ACTIVE_STATES = {
    "PENDING_ADMISSION",
    "PENDING_DISPATCH",
    "DISPATCHING",
    "ACKED",
    "PARTIALLY_FILLED",
    "UNKNOWN",
}


def _validate_owner_cancel_reply(
    value: Mapping[str, Any],
    command_id: str,
    *,
    binding: OwnerControlBinding,
    deployment_version: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"ok", "code", "result"}:
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    code = value.get("code")
    result = value.get("result")
    if (
        type(value.get("ok")) is not bool
        or type(code) is not str
        or code not in set(_CANCEL_REPLY_CODES.values())
        or not isinstance(result, Mapping)
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    required_result_fields = {
        "command_id",
        "batch_sha256",
        "scope_key",
        "account_ref",
        "portfolio_ref",
        "strategy_ref",
        "run_id",
        "total_count",
        "selected_count",
        "omitted_count",
        "state_counts",
        "outcome",
        "items",
    }
    if (
        set(result) != required_result_fields
        or result.get("command_id") != command_id
        or result.get("account_ref") != binding.wire_scope.account_ref
        or result.get("portfolio_ref") is not None
        or result.get("strategy_ref") != binding.wire_scope.strategy_ref
        or result.get("run_id") != binding.wire_scope.run_id
        or type(result.get("batch_sha256")) is not str
        or re.fullmatch(r"[0-9a-f]{64}", result["batch_sha256"]) is None
        or type(result.get("scope_key")) is not str
        or not result["scope_key"]
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    outcome = result.get("outcome")
    if type(outcome) is not str or _CANCEL_REPLY_CODES.get(outcome) != code:
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    if value["ok"] is not (outcome in {"APPLIED", "ACKNOWLEDGED", "PARTIAL", "NO_EFFECT"}):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    total = _cancel_count(result.get("total_count"), maximum=10_000)
    selected = _cancel_count(result.get("selected_count"), maximum=128)
    omitted = _cancel_count(result.get("omitted_count"), maximum=10_000)
    items = result.get("items")
    counts = result.get("state_counts")
    if (
        total is None
        or selected is None
        or omitted is None
        or selected + omitted != total
        # WireEnvelope recursively freezes JSON arrays as tuples before a
        # ServiceClientRuntime exposes the reply. Direct component calls may
        # still provide lists, so accept both supported representations while
        # projecting a fresh mutable list below.
        or type(items) not in (list, tuple)
        or len(items) != selected
        or not isinstance(counts, Mapping)
        or any(type(key) is not str or key not in _CANCEL_STATES for key in counts)
        or any(_cancel_count(count, maximum=128) is None for count in counts.values())
    ):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    copied_items: list[dict[str, Any]] = []
    observed_counts: dict[str, int] = {}
    unresolved = False
    for item in items:
        item_fields = {
            "intent_id",
            "instrument_ref",
            "record_state",
            "decision",
            "cancel_id",
            "cancel_state",
            "unknown_reason",
            "review_required",
            "dispatch_attempts",
        }
        if not isinstance(item, Mapping) or set(item) != item_fields:
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
        if (
            not _cancel_text(item.get("intent_id"), max_bytes=256)
            or not _cancel_text(item.get("instrument_ref"), max_bytes=256)
            or item.get("record_state") not in _CANCEL_STATES
            or item.get("decision") not in _CANCEL_DECISIONS
            or (
                item.get("cancel_id") is not None
                and not _cancel_text(item.get("cancel_id"), max_bytes=256)
            )
            or (
                item.get("cancel_state") is not None
                and item.get("cancel_state") not in _CANCEL_STATES
            )
            or (
                item.get("unknown_reason") is not None
                and not _cancel_text(item.get("unknown_reason"), max_bytes=128)
            )
            or type(item.get("review_required")) is not bool
            or _cancel_count(item.get("dispatch_attempts"), maximum=10_000) is None
        ):
            raise OwnerControlError("OWNER_RECEIPT_INVALID")
        state = item.get("cancel_state")
        if state is not None:
            observed_counts[state] = observed_counts.get(state, 0) + 1
        if item.get("decision") in {"UNKNOWN", "UNRESOLVED", "PENDING"}:
            unresolved = True
        if state in _CANCEL_ACTIVE_STATES:
            unresolved = True
        copied = dict(item)
        # Owner/provider diagnostics are internal text. Expose only a finite
        # summary so an exception or adapter detail cannot leak through HTTP.
        copied["unknown_reason"] = (
            "outcome_unknown"
            if item.get("unknown_reason") is not None
            or item.get("decision") in {"UNKNOWN", "UNRESOLVED"}
            or state == "UNKNOWN"
            else None
        )
        copied_items.append(copied)
    if observed_counts != dict(counts):
        raise OwnerControlError("OWNER_RECEIPT_INVALID")
    if outcome in {"UNKNOWN", "PENDING"}:
        unresolved = True
    if outcome == "ACKNOWLEDGED":
        unresolved = True
    owner_final = not unresolved and outcome in {"APPLIED", "PARTIAL", "NO_EFFECT"}
    status_value = {
        "APPLIED": "applied",
        "ACKNOWLEDGED": "acknowledged",
        "PARTIAL": "partial",
        "PENDING": "pending",
        "UNKNOWN": "unknown",
        "NO_EFFECT": "no_effect",
    }[outcome]
    effect_result = {
        "action": "cancel",
        "batch_sha256": result["batch_sha256"],
        "total_count": total,
        "selected_count": selected,
        "omitted_count": omitted,
        "state_counts": dict(counts),
        "items": copied_items,
    }
    return {
        "action": "cancel",
        "command_id": command_id,
        "deployment_version": deployment_version,
        "status": status_value,
        "outcome": outcome.lower(),
        "effect_ref": result["batch_sha256"],
        "effect_result": effect_result,
        "request_recorded": True,
        "owner_final": owner_final,
        "reconciliation_required": not owner_final,
    }


def _cancel_unknown_projection(
    command_id: str, *, action: str, deployment_version: str
) -> dict[str, Any]:
    return {
        "action": action,
        "command_id": command_id,
        "deployment_version": deployment_version,
        "status": "unknown",
        "outcome": "unknown",
        "effect_ref": None,
        "effect_result": {
            "action": "cancel",
            "batch_state": "UNKNOWN",
            "items": [],
        },
        "request_recorded": True,
        "owner_final": False,
        "reconciliation_required": True,
    }


def _cancel_rejected_projection(
    command_id: str,
    *,
    action: str,
    deployment_version: str,
    owner_code: str,
) -> dict[str, Any]:
    return {
        "action": action,
        "command_id": command_id,
        "deployment_version": deployment_version,
        "status": "rejected",
        "outcome": "rejected",
        "effect_ref": None,
        "effect_result": {
            "action": "cancel",
            "result": "not_authorized",
            "owner_code": owner_code,
        },
        "request_recorded": True,
        "owner_final": True,
        "reconciliation_required": False,
    }


def _decode_persisted_projection(value: Any, command_id: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not str or not value or len(value) > 1_000_000:
        raise OwnerControlError("ISSUER_STATE_UNAVAILABLE")
    try:
        decoded = json.loads(
            value,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except (TypeError, ValueError, json.JSONDecodeError, RecursionError):
        raise OwnerControlError("ISSUER_STATE_UNAVAILABLE") from None
    required = {
        "action",
        "command_id",
        "deployment_version",
        "status",
        "outcome",
        "effect_ref",
        "effect_result",
        "request_recorded",
        "owner_final",
        "reconciliation_required",
    }
    if (
        type(decoded) is not dict
        or set(decoded) != required
        or decoded.get("action") != "cancel"
        or decoded.get("command_id") != command_id
        or type(decoded.get("owner_final")) is not bool
        or type(decoded.get("reconciliation_required")) is not bool
        or decoded.get("request_recorded") is not True
        or decoded.get("reconciliation_required") is decoded.get("owner_final")
        or decoded.get("status")
        not in {
            "applied",
            "acknowledged",
            "partial",
            "pending",
            "unknown",
            "no_effect",
            "rejected",
        }
        or decoded.get("outcome")
        not in {
            "applied",
            "acknowledged",
            "partial",
            "pending",
            "unknown",
            "no_effect",
            "rejected",
        }
        or type(decoded.get("deployment_version")) is not str
        or type(decoded.get("effect_result")) is not dict
    ):
        raise OwnerControlError("ISSUER_STATE_UNAVAILABLE")
    return decoded


def _cancel_count(value: Any, *, maximum: int) -> int | None:
    if type(value) is not int or value < 0 or value > maximum:
        return None
    return value


def _cancel_text(value: Any, *, max_bytes: int) -> bool:
    if type(value) is not str or not value or value != value.strip():
        return False
    try:
        return len(value.encode("utf-8", errors="strict")) <= max_bytes and value.isprintable()
    except UnicodeEncodeError:
        return False


def _validate_timestamp(value: float) -> float:
    if isinstance(value, bool) or type(value) not in (int, float) or not math.isfinite(value):
        raise OwnerControlError("DEPLOYMENT_INVALID")
    return float(value)


def _validate_idempotency_key(value: str) -> None:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise OwnerControlError("IDEMPOTENCY_KEY_INVALID")
    try:
        if len(value.encode("utf-8", errors="strict")) > _MAX_IDEMPOTENCY_KEY_BYTES:
            raise OwnerControlError("IDEMPOTENCY_KEY_INVALID")
    except UnicodeEncodeError:
        raise OwnerControlError("IDEMPOTENCY_KEY_INVALID") from None


def _decode_secret(value: SecretStr, *, minimum: int) -> bytes:
    try:
        decoded = base64.b64decode(value.get_secret_value(), validate=True)
    except (ValueError, TypeError):
        raise OwnerControlError("DEPLOYMENT_INVALID") from None
    if len(decoded) < minimum:
        raise OwnerControlError("DEPLOYMENT_INVALID")
    return decoded


def _z85_bytes(value: SecretStr) -> bytes:
    """Return the 40-byte Z85 spelling expected by the SDK transport adapter."""

    encoded = value.get_secret_value()
    if len(encoded) != 40 or any(char not in _Z85_ALPHABET for char in encoded):
        raise OwnerControlError("DEPLOYMENT_INVALID")
    try:
        return encoded.encode("ascii", errors="strict")
    except UnicodeError:
        raise OwnerControlError("DEPLOYMENT_INVALID") from None


def _fixed_lookup(mapping: Mapping[str, Any], key: str) -> Any:
    try:
        return mapping[key]
    except (KeyError, TypeError):
        raise KeyError("unconfigured fixed owner-control reference") from None


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise ValueError("invalid JSON constant: " + value)


__all__ = [
    "OwnerControlBinding",
    "OwnerControlDeployment",
    "OwnerControlError",
    "OwnerControlRequest",
    "control_implementation_status",
    "get_deployment_setting",
]
