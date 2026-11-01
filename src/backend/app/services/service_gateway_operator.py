"""AFI's deployment-owned control surface for SDK Gateway operator profiles.

Launch factories, authority, endpoint and secret resolution remain registered
local code in the service deployment. This module stores only exact account,
subject, operation and legacy-owner assignments; user requests can select only
one already configured profile.
"""

from __future__ import annotations

import json
import math
import re
import threading
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from app.services.live_trading.service_gateway_operator_guard import (
    legacy_gateway_owner_operation,
    register_legacy_gateway_exclusions,
    unregister_legacy_gateway_exclusions,
)

_MAX_DEPLOYMENT_BYTES = 262_144
_MAX_PROFILES = 128
_MAX_SUBJECTS_PER_PROFILE = 256
_MAX_LEGACY_KEYS_PER_PROFILE = 128
_SAFE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STATUS_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_OPERATIONS = frozenset({"status", "start", "stop", "recover", "cleanup"})
_ROLES = frozenset({"account_session_worker", "market_hub"})
_STATUS_STATES = frozenset(
    {"new", "starting", "running", "stopping", "uncertain", "closed", "failed"}
)
_OPERATION_NAMES = frozenset({"start", "recover", "cleanup", "stop", "serve"})
_OPERATION_STATES = frozenset({"idle", "running", "succeeded", "failed", "outcome_uncertain"})


class ServiceGatewayOperatorError(RuntimeError):
    """Finite, value-free failure from trusted operator deployment wiring."""

    _CODES = frozenset(
        {
            "INVALID_DEPLOYMENT",
            "DEPLOYMENT_TOO_LARGE",
            "SDK_OPERATOR_UNAVAILABLE",
            "PROFILE_NOT_REGISTERED",
            "INVALID_PROFILE",
            "DUPLICATE_PROFILE",
            "DUPLICATE_ACCOUNT",
            "DUPLICATE_LEGACY_KEY",
            "INVALID_GRANT",
            "PROFILE_NOT_CONFIGURED",
            "OPERATION_NOT_GRANTED",
            "OWNER_NOT_AUTHORIZED",
            "OPERATOR_NOT_CONFIGURED",
            "OPERATOR_CONTROL_CLOSED",
            "LEGACY_MANAGER_UNAVAILABLE",
            "LEGACY_MANAGER_RESTORE_IN_PROGRESS",
            "LEGACY_GATEWAY_OWNER_ACTIVE",
            "OPERATOR_START_FAILED",
            "OPERATOR_RECOVERY_FAILED",
            "OPERATOR_STOP_UNCERTAIN",
            "OPERATOR_CLOSE_UNCERTAIN",
            "AUTO_START_FAILED",
            "INVALID_LAUNCH_CONFIG",
            "INVALID_POLL_INTERVAL",
            "PROFILE_DUPLICATE",
            "PROFILE_ENTRY_POINT_INVALID",
            "APPLICATION_START_TIMEOUT",
            "APPLICATION_START_FAILED",
            "APPLICATION_RECOVERY_FAILED",
            "APPLICATION_RECOVERY_TIMEOUT",
            "APPLICATION_STOP_TIMEOUT",
            "APPLICATION_CLEANUP_UNCERTAIN",
            "APPLICATION_CLOSE_UNCERTAIN",
            "APPLICATION_SERVE_FAILED",
            "APPLICATION_DEPLOYMENT_INVALID",
            "APPLICATION_NOT_RUNNING",
            "APPLICATION_NOT_RESTARTABLE",
            "APPLICATION_OPERATION_IN_PROGRESS",
            "DEPLOYMENT_STATUS_UNAVAILABLE",
            "INVALID_TIMEOUT",
        }
    )

    def __init__(self, code: str) -> None:
        self.code = code if type(code) is str and code in self._CODES else "OPERATOR_FAILED"
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class _ProfileGrant:
    profile_ref: str
    account_ref: str | None
    authorized_subjects: frozenset[str]
    operations: frozenset[str]
    auto_start: bool
    legacy_gateway_keys: tuple[str, ...]
    profile: Any = field(repr=False, compare=False)

    @property
    def role(self) -> str:
        return str(self.profile.role)


class ServiceGatewayOperatorControl:
    """Per-ASGI-application owner of explicitly configured SDK profiles."""

    def __init__(self, grants: Mapping[str, _ProfileGrant]) -> None:
        self._grants = dict(grants)
        self._applications: dict[str, Any] = {}
        self._exclusion_owners: dict[str, object] = {}
        self._lock = threading.RLock()
        self._operation_lock = threading.RLock()
        self._closed = False

    @classmethod
    def from_value(
        cls,
        value: object,
        *,
        profile_registry: Any | None = None,
    ) -> ServiceGatewayOperatorControl | None:
        """Parse exact server-owned grants; empty input disables the feature."""

        if value is None or value == "":
            return None
        if type(value) is not str:
            raise ServiceGatewayOperatorError("INVALID_DEPLOYMENT")
        try:
            encoded = value.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ServiceGatewayOperatorError("INVALID_DEPLOYMENT") from None
        if len(encoded) > _MAX_DEPLOYMENT_BYTES:
            raise ServiceGatewayOperatorError("DEPLOYMENT_TOO_LARGE")
        try:
            document = json.loads(
                value,
                object_pairs_hook=_unique_object,
                parse_constant=_reject_constant,
            )
        except (ValueError, TypeError, RecursionError):
            raise ServiceGatewayOperatorError("INVALID_DEPLOYMENT") from None
        if (
            type(document) is not dict
            or set(document) != {"schema_version", "operators"}
            or type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or type(document["operators"]) is not list
            or not document["operators"]
            or len(document["operators"]) > _MAX_PROFILES
        ):
            raise ServiceGatewayOperatorError("INVALID_DEPLOYMENT")

        registry = profile_registry
        if registry is None:
            try:
                from bt_api_py.gateway_operator_application import (
                    GatewayOperatorProfileRegistry,
                )
            except ImportError:
                raise ServiceGatewayOperatorError("SDK_OPERATOR_UNAVAILABLE") from None
            try:
                registry = GatewayOperatorProfileRegistry.from_entry_points()
            except Exception:
                raise ServiceGatewayOperatorError("SDK_OPERATOR_UNAVAILABLE") from None

        grants: dict[str, _ProfileGrant] = {}
        accounts: set[str] = set()
        legacy_keys: set[str] = set()
        for raw in document["operators"]:
            grant = _parse_grant(raw, registry)
            if grant.profile_ref in grants:
                raise ServiceGatewayOperatorError("DUPLICATE_PROFILE")
            if grant.account_ref is not None:
                if grant.account_ref in accounts:
                    raise ServiceGatewayOperatorError("DUPLICATE_ACCOUNT")
                accounts.add(grant.account_ref)
            if legacy_keys.intersection(grant.legacy_gateway_keys):
                raise ServiceGatewayOperatorError("DUPLICATE_LEGACY_KEY")
            legacy_keys.update(grant.legacy_gateway_keys)
            grants[grant.profile_ref] = grant
        return cls(grants)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def authorized_profiles(self, owner_subject: str) -> list[dict[str, Any]]:
        """List only profiles explicitly granted to this persisted subject."""

        with self._lock:
            if self._closed:
                raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
            return [
                {
                    "profile_ref": grant.profile_ref,
                    "role": grant.role,
                    "account_ref": grant.account_ref,
                    "operations": sorted(grant.operations),
                    "auto_start": grant.auto_start,
                }
                for grant in self._grants.values()
                if owner_subject in grant.authorized_subjects
            ]

    def authorized_legacy_gateway_mapping(
        self,
        legacy_gateway_key: str | None,
        owner_subject: str,
    ) -> dict[str, str | None] | None:
        """Return a safe start target only for an exact, owner-authorized key.

        This is a read-only migration hint. It does not resolve credentials,
        construct a profile application, or start the service.
        """
        if (
            type(legacy_gateway_key) is not str
            or not legacy_gateway_key
            or len(legacy_gateway_key) > 256
            or type(owner_subject) is not str
            or not owner_subject
        ):
            return None
        with self._lock:
            if self._closed:
                raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
            grant = next(
                (
                    item
                    for item in self._grants.values()
                    if item.role == "account_session_worker"
                    if legacy_gateway_key in item.legacy_gateway_keys
                    and owner_subject in item.authorized_subjects
                    and "start" in item.operations
                ),
                None,
            )
        if grant is None:
            return None
        return {
            "profile_ref": grant.profile_ref,
            "role": grant.role,
            "account_ref": grant.account_ref,
        }

    def authorized_legacy_gateway_mappings(
        self,
        owner_subject: str,
    ) -> list[dict[str, str]]:
        """List only migration keys explicitly granted to this owner.

        Legacy credential records have no persisted owner field and are never
        read here. A key is visible only when the trusted deployment binds it
        to a profile that authorizes this exact owner.
        """
        if type(owner_subject) is not str or not owner_subject:
            return []
        with self._lock:
            if self._closed:
                raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
            mappings = [
                {
                    "gateway_key": key,
                    "profile_ref": grant.profile_ref,
                }
                for grant in self._grants.values()
                if grant.role == "account_session_worker"
                and owner_subject in grant.authorized_subjects
                and "status" in grant.operations
                and "start" in grant.operations
                for key in grant.legacy_gateway_keys
            ]
        return sorted(mappings, key=lambda item: (item["profile_ref"], item["gateway_key"]))

    def status(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        grant = self._authorized_grant(profile_ref, owner_subject, "status")
        with self._lock:
            application = self._applications.get(profile_ref)
        if application is None:
            snapshot: Mapping[str, object] = {
                "state": "new",
                "role": grant.role,
                "ready": False,
                "error_code": None,
                "operation": {"name": None, "state": "idle", "error_code": None},
                "account_session": None,
                "cleanup": {"unclaimed_provider_count": 0, "last_cleanup_code": None},
            }
        else:
            snapshot = application.status
        return _public_status(grant, snapshot)

    def start(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        with self._operation_lock:
            return self._start_profile(profile_ref, owner_subject)

    def _start_profile(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        grant = self._authorized_grant(profile_ref, owner_subject, "start")
        lock = (
            legacy_gateway_owner_operation()
            if grant.role == "account_session_worker"
            else nullcontext()
        )
        with lock:
            self._install_legacy_exclusion(grant)
            try:
                application = self._application_for(grant)
                snapshot = application.start(timeout_seconds=30.0)
            except Exception as error:
                code = _error_code(error, "OPERATOR_START_FAILED")
                raise ServiceGatewayOperatorError(code) from None
        return _public_status(grant, snapshot)

    def recover(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        with self._operation_lock:
            return self._recover_profile(profile_ref, owner_subject)

    def _recover_profile(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        grant = self._authorized_grant(profile_ref, owner_subject, "recover")
        if grant.role != "account_session_worker":
            raise ServiceGatewayOperatorError("OPERATION_NOT_GRANTED")
        with self._lock:
            application = self._applications.get(profile_ref)
        if application is None:
            raise ServiceGatewayOperatorError("PROFILE_NOT_CONFIGURED")
        try:
            snapshot = application.recover_account_session(timeout_seconds=30.0)
        except Exception as error:
            code = _error_code(error, "OPERATOR_RECOVERY_FAILED")
            raise ServiceGatewayOperatorError(code) from None
        return _public_status(grant, snapshot)

    def stop(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        with self._operation_lock:
            return self._stop_profile(profile_ref, owner_subject)

    def _stop_profile(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        grant = self._authorized_grant(profile_ref, owner_subject, "stop")
        with self._lock:
            application = self._applications.get(profile_ref)
        if application is None:
            return self.status(profile_ref, owner_subject)
        try:
            snapshot = application.stop(timeout_seconds=30.0)
        except Exception as error:
            code = _error_code(error, "OPERATOR_STOP_UNCERTAIN")
            raise ServiceGatewayOperatorError(code) from None
        return _public_status(grant, snapshot)

    def cleanup(self, profile_ref: str, owner_subject: str) -> dict[str, Any]:
        """Retry owner-thread provider cleanup only when the server grants it."""

        with self._operation_lock:
            grant = self._authorized_grant(profile_ref, owner_subject, "cleanup")
            with self._lock:
                application = self._applications.get(profile_ref)
            if application is None:
                raise ServiceGatewayOperatorError("PROFILE_NOT_CONFIGURED")
            try:
                snapshot = application.retry_unclaimed_provider_cleanup(timeout_seconds=30.0)
            except Exception as error:
                code = _error_code(error, "APPLICATION_CLEANUP_UNCERTAIN")
                raise ServiceGatewayOperatorError(code) from None
            return _public_status(grant, snapshot)

    def start_auto_profiles(self) -> None:
        """Start only profiles whose server deployment explicitly sets true."""

        with self._operation_lock:
            self._start_auto_profiles()

    def _start_auto_profiles(self) -> None:

        with self._lock:
            if self._closed:
                raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
            selected = tuple(grant for grant in self._grants.values() if grant.auto_start)
        owner_lock = (
            legacy_gateway_owner_operation()
            if any(grant.role == "account_session_worker" for grant in selected)
            else nullcontext()
        )
        try:
            with owner_lock:
                for grant in selected:
                    self._install_legacy_exclusion(grant)
                for grant in selected:
                    self._start_configured(grant)
        except Exception:
            try:
                self.close()
            except ServiceGatewayOperatorError:
                pass
            raise ServiceGatewayOperatorError("AUTO_START_FAILED") from None

    def protect_configured_legacy_owners(self) -> None:
        """Install exclusions before AFI starts restoring legacy gateway owners."""

        with self._operation_lock:
            with legacy_gateway_owner_operation():
                with self._lock:
                    if self._closed:
                        raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
                    grants = tuple(self._grants.values())
                account_grants = tuple(
                    grant for grant in grants if grant.role == "account_session_worker"
                )
                try:
                    for grant in account_grants:
                        self._register_legacy_exclusion(grant)
                    for grant in account_grants:
                        _assert_legacy_gateway_owner_stopped(grant.legacy_gateway_keys)
                except Exception:
                    with self._lock:
                        owners = tuple(self._exclusion_owners.values())
                        self._exclusion_owners.clear()
                    for owner in owners:
                        unregister_legacy_gateway_exclusions(owner)
                    raise

    def close(self) -> None:
        with self._operation_lock:
            with legacy_gateway_owner_operation():
                self._close()

    def _close(self) -> None:
        """Close every created owner and preserve exclusions on uncertainty."""

        with self._lock:
            if self._closed:
                return
            applications = tuple(reversed(tuple(self._applications.values())))
        failures = False
        for application in applications:
            try:
                application.close(timeout_seconds=30.0)
            except Exception:
                failures = True
        if failures:
            raise ServiceGatewayOperatorError("OPERATOR_CLOSE_UNCERTAIN")
        with self._lock:
            self._closed = True
            exclusion_owners = tuple(self._exclusion_owners.values())
            self._exclusion_owners.clear()
        for owner in exclusion_owners:
            unregister_legacy_gateway_exclusions(owner)

    def _start_configured(self, grant: _ProfileGrant) -> None:
        application = self._application_for(grant)
        try:
            application.start(timeout_seconds=30.0)
        except Exception as error:
            raise ServiceGatewayOperatorError(_error_code(error, "OPERATOR_START_FAILED")) from None

    def _application_for(self, grant: _ProfileGrant) -> Any:
        with self._lock:
            if self._closed:
                raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
            application = self._applications.get(grant.profile_ref)
            if application is not None:
                snapshot = application.status
                state = snapshot.get("state")
                operation = snapshot.get("operation")
                operation_state = operation.get("state") if isinstance(operation, Mapping) else None
                cleanup = snapshot.get("cleanup")
                cleanup_certain = (
                    isinstance(cleanup, Mapping)
                    and type(cleanup.get("unclaimed_provider_count")) is int
                    and cleanup.get("unclaimed_provider_count") == 0
                    and cleanup.get("last_cleanup_code") is None
                )
                if (
                    state not in {"closed", "failed"}
                    or operation_state == "outcome_uncertain"
                    or not cleanup_certain
                ):
                    return application
            try:
                from bt_api_py.gateway_operator_application import GatewayOperatorApplication
            except ImportError:
                raise ServiceGatewayOperatorError("SDK_OPERATOR_UNAVAILABLE") from None
            application = GatewayOperatorApplication(grant.profile)
            self._applications[grant.profile_ref] = application
            return application

    def _install_legacy_exclusion(self, grant: _ProfileGrant) -> None:
        if grant.role != "account_session_worker":
            return
        self._register_legacy_exclusion(grant)
        _assert_legacy_gateway_owner_stopped(grant.legacy_gateway_keys)

    def _register_legacy_exclusion(self, grant: _ProfileGrant) -> None:
        if grant.role != "account_session_worker":
            return
        owner = self._exclusion_owners.get(grant.profile_ref)
        if owner is None:
            owner = object()
            register_legacy_gateway_exclusions(owner, grant.legacy_gateway_keys)
            with self._lock:
                existing = self._exclusion_owners.setdefault(grant.profile_ref, owner)
            if existing is not owner:
                unregister_legacy_gateway_exclusions(owner)
                owner = existing

    def _authorized_grant(
        self, profile_ref: str, owner_subject: str, operation: str
    ) -> _ProfileGrant:
        with self._lock:
            if self._closed:
                raise ServiceGatewayOperatorError("OPERATOR_CONTROL_CLOSED")
            grant = self._grants.get(profile_ref)
        if grant is None:
            raise ServiceGatewayOperatorError("PROFILE_NOT_CONFIGURED")
        if owner_subject not in grant.authorized_subjects:
            raise ServiceGatewayOperatorError("OWNER_NOT_AUTHORIZED")
        if operation not in grant.operations:
            raise ServiceGatewayOperatorError("OPERATION_NOT_GRANTED")
        return grant


def _parse_grant(raw: object, registry: Any) -> _ProfileGrant:
    required = {
        "profile_ref",
        "account_ref",
        "authorized_subjects",
        "operations",
        "auto_start",
        "legacy_gateway_keys",
    }
    if type(raw) is not dict or set(raw) != required:
        raise ServiceGatewayOperatorError("INVALID_GRANT")
    profile_ref = raw["profile_ref"]
    if type(profile_ref) is not str or _SAFE_REF.fullmatch(profile_ref) is None:
        raise ServiceGatewayOperatorError("INVALID_GRANT")
    try:
        profile = registry.resolve(profile_ref)
    except Exception:
        raise ServiceGatewayOperatorError("PROFILE_NOT_REGISTERED") from None
    if type(profile.role) is not str or profile.role not in _ROLES:
        raise ServiceGatewayOperatorError("INVALID_PROFILE")

    account_ref = raw["account_ref"]
    if account_ref is not None and not _valid_identifier(account_ref):
        raise ServiceGatewayOperatorError("INVALID_GRANT")
    subjects = raw["authorized_subjects"]
    operations = raw["operations"]
    legacy_keys = raw["legacy_gateway_keys"]
    if (
        type(subjects) is not list
        or not subjects
        or len(subjects) > _MAX_SUBJECTS_PER_PROFILE
        or any(not _valid_identifier(subject) for subject in subjects)
        or len(set(subjects)) != len(subjects)
        or type(operations) is not list
        or not operations
        or any(
            type(operation) is not str or operation not in _OPERATIONS for operation in operations
        )
        or len(set(operations)) != len(operations)
        or not {"status", "start", "stop"} <= set(operations)
        or type(raw["auto_start"]) is not bool
        or type(legacy_keys) is not list
        or len(legacy_keys) > _MAX_LEGACY_KEYS_PER_PROFILE
        or any(not _valid_legacy_key(key) for key in legacy_keys)
        or len(set(legacy_keys)) != len(legacy_keys)
    ):
        raise ServiceGatewayOperatorError("INVALID_GRANT")

    if profile.role == "account_session_worker":
        if account_ref is None or not legacy_keys:
            raise ServiceGatewayOperatorError("INVALID_GRANT")
    elif account_ref is not None or legacy_keys or "recover" in operations:
        raise ServiceGatewayOperatorError("INVALID_GRANT")

    return _ProfileGrant(
        profile_ref=profile_ref,
        account_ref=account_ref,
        authorized_subjects=frozenset(subjects),
        operations=frozenset(operations),
        auto_start=raw["auto_start"],
        legacy_gateway_keys=tuple(legacy_keys),
        profile=profile,
    )


def _assert_legacy_gateway_owner_stopped(keys: tuple[str, ...]) -> None:
    """Fail closed when the old AFI manager has a matching live owner."""

    try:
        from app.services.live_trading.manager import get_existing_live_trading_manager
    except ImportError:
        raise ServiceGatewayOperatorError("LEGACY_MANAGER_UNAVAILABLE") from None
    manager = get_existing_live_trading_manager()
    if manager is None:
        return
    if manager.is_gateway_restore_in_progress():
        raise ServiceGatewayOperatorError("LEGACY_MANAGER_RESTORE_IN_PROGRESS")
    with manager._gateway_lock:
        active = set(keys).intersection(manager._gateways)
    if active:
        raise ServiceGatewayOperatorError("LEGACY_GATEWAY_OWNER_ACTIVE")


def _public_status(grant: _ProfileGrant, snapshot: Mapping[str, object]) -> dict[str, Any]:
    state = snapshot.get("state")
    account_session = _account_session_status(snapshot.get("account_session"))
    ready = snapshot.get("ready") is True
    if grant.role == "account_session_worker" and account_session is None:
        ready = False
    return {
        "profile_ref": grant.profile_ref,
        "account_ref": grant.account_ref,
        "role": grant.role,
        "state": state if type(state) is str and state in _STATUS_STATES else "unknown",
        "ready": ready,
        "error_code": _status_code(snapshot.get("error_code")),
        "operation": _operation_status(snapshot.get("operation")),
        "account_session": account_session,
        "cleanup": _cleanup_status(snapshot.get("cleanup")),
    }


def _operation_status(value: object) -> dict[str, object]:
    operation = value if isinstance(value, Mapping) else {}
    name = operation.get("name")
    state = operation.get("state")
    return {
        "name": name if name is None or (type(name) is str and name in _OPERATION_NAMES) else None,
        "state": state if type(state) is str and state in _OPERATION_STATES else "failed",
        "error_code": _status_code(operation.get("error_code")),
    }


def _account_session_status(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    state = value.get("state")
    generation = value.get("session_generation")
    ready = value.get("ready")
    fresh = value.get("fresh_for_seconds")
    if (
        type(state) is not str
        or not state
        or len(state) > 64
        or not state.isprintable()
        or (generation is not None and not _valid_identifier(generation))
        or type(ready) is not bool
        or isinstance(fresh, bool)
        or not isinstance(fresh, (int, float))
        or not math.isfinite(float(fresh))
        or float(fresh) < 0
    ):
        return None
    return {
        "state": state,
        "session_generation": generation,
        "ready": ready,
        "fresh_for_seconds": float(fresh),
    }


def _cleanup_status(value: object) -> dict[str, object]:
    cleanup = value if isinstance(value, Mapping) else {}
    count = cleanup.get("unclaimed_provider_count")
    code = cleanup.get("last_cleanup_code")
    if type(count) is not int or count < 0:
        return {
            "unclaimed_provider_count": None,
            "last_cleanup_code": "DEPLOYMENT_STATUS_UNAVAILABLE",
        }
    return {
        "unclaimed_provider_count": count,
        "last_cleanup_code": _status_code(code),
    }


def _status_code(value: object) -> str | None:
    return value if type(value) is str and _STATUS_CODE.fullmatch(value) is not None else None


def _valid_identifier(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value.encode("utf-8", errors="ignore")) <= 128
        and value.isprintable()
    )


def _valid_legacy_key(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and len(value.encode("utf-8", errors="ignore")) <= 256
        and value.isprintable()
    )


def _unique_object(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _error_code(error: Exception, fallback: str) -> str:
    code = getattr(error, "code", None)
    if type(code) is str and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", code):
        return code
    return fallback
