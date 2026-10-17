"""Trusted deployment composition for optional application service access.

The JSON input is deployment-owned configuration. It maps exact JWT subjects
to separately authorized application identities, read bindings, and narrowly
scoped write bindings. This module never consults request data to build an
identity and does no work when the deployment value is empty.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from pydantic import SecretStr

from app.services.service_read.access import (
    ReadAccess,
    ServiceReadAccessDirectory,
    StrategyBookBinding,
)
from app.services.service_read.client import (
    AccountBinding,
    AccountBookBinding,
    ApprovedTargetSubmitBinding,
    MonitorBinding,
    OrderBinding,
    OrderSubmitBinding,
    PortfolioAnalyticsBinding,
    PaperLegacyImportBinding,
    PaperSubmitBinding,
    PAPER_CONTROL_MODES,
    RiskPolicyBudgetBinding,
    _MAX_ORDER_INSTRUMENT_METADATA_VERSIONS,
    PAPER_LEGACY_IMPORT_OPERATIONS,
)
from app.services.service_read.session import SdkServiceReadSession
from app.services.service_read.worker import ServiceReadWorker

__all__ = [
    "ServiceReadDeployment",
    "ServiceReadDeploymentError",
    "start_service_read_deployment",
]

_MAX_DEPLOYMENT_BYTES = 262_144
_MAX_SUBJECTS = 256
_MAX_BINDINGS_PER_SUBJECT = 128
_MAX_SELECTORS = 4096
_MAX_QUEUE_SIZE = 256
_MAX_MAINTENANCE_INTERVAL = 300.0
_Z85_ALPHABET = frozenset(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#"
)
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
_READ_MOUNTS = frozenset(
    {"application.account", "application.order_query", "application.monitor", "application.risk_analysis"}
)
_DEPLOYMENT_MOUNTS = _READ_MOUNTS | {
    "application.orders",
    "application.risk_policy",
    "application.paper_legacy_import",
}


class ServiceReadDeploymentError(RuntimeError):
    """Finite startup or cleanup failure without configuration values."""

    def __init__(
        self,
        code: str,
        *,
        cause_type: str | None = None,
        failures: tuple[BaseException, ...] = (),
        deployment: ServiceReadDeployment | None = None,
    ) -> None:
        self.code = code
        self.cause_type = cause_type
        self.failures = failures
        self.deployment = deployment
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class _SubjectProfile:
    subject: str
    identity: Any
    client_config: Any = field(repr=False, compare=False)
    scopes: Mapping[str, Any] = field(repr=False, compare=False)
    peer_identities: Mapping[str, Any] = field(repr=False, compare=False)
    curve_keys: Mapping[str, tuple[bytes, bytes, bytes]] = field(repr=False, compare=False)
    account_bindings: Mapping[str, AccountBinding] = field(repr=False, compare=False)
    account_book_bindings: Mapping[str, AccountBookBinding] = field(repr=False, compare=False)
    strategy_book_bindings: Mapping[str, StrategyBookBinding] = field(repr=False, compare=False)
    order_bindings: Mapping[str, OrderBinding] = field(repr=False, compare=False)
    order_submit_bindings: Mapping[str, OrderSubmitBinding] = field(repr=False, compare=False)
    paper_submit_bindings: Mapping[str, PaperSubmitBinding] = field(repr=False, compare=False)
    paper_legacy_import_bindings: Mapping[str, PaperLegacyImportBinding] = field(
        repr=False, compare=False
    )
    approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding] = field(
        repr=False, compare=False
    )
    monitor_bindings: Mapping[str, MonitorBinding] = field(repr=False, compare=False)
    portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding] = field(
        repr=False, compare=False
    )
    risk_policy_budget_bindings: Mapping[str, RiskPolicyBudgetBinding] = field(
        repr=False, compare=False
    )
    account_grants: frozenset[str]
    account_book_grants: frozenset[str]
    strategy_book_grants: frozenset[str]
    order_grants: frozenset[str]
    order_submit_grants: frozenset[str]
    paper_submit_grants: frozenset[str]
    paper_legacy_import_grants: frozenset[str]
    approved_target_grants: frozenset[str]
    monitor_grants: frozenset[str]
    portfolio_grants: frozenset[str]
    risk_policy_budget_grants: frozenset[str]
    max_queue_size: int
    maintenance_interval_seconds: float


class ServiceReadDeployment:
    """Started owner workers and the immutable directory for configured service access."""

    def __init__(
        self,
        workers: tuple[ServiceReadWorker, ...],
        directory: ServiceReadAccessDirectory,
    ) -> None:
        self._workers = workers
        self.directory = directory
        self._close_failures: tuple[BaseException, ...] = ()
        self._closed = False

    @property
    def close_failures(self) -> tuple[BaseException, ...]:
        """Original worker close errors retained for startup diagnostics."""

        return self._close_failures

    @property
    def closed(self) -> bool:
        """Whether every owned worker closed without reporting uncertainty."""

        return self._closed

    async def aclose(self) -> None:
        """Close every worker on its owner thread, even when one close fails."""

        failures: list[BaseException] = []
        for worker in reversed(self._workers):
            try:
                await worker.aclose()
            except BaseException as error:
                failures.append(error)
        self._close_failures = tuple(failures)
        self._closed = not failures
        if failures:
            raise ServiceReadDeploymentError("CLOSE_FAILED", failures=tuple(failures)) from None


async def start_service_read_deployment(
    value: SecretStr | str | None,
) -> ServiceReadDeployment | None:
    """Parse trusted configuration and start one SDK owner worker per subject.

    An empty value returns ``None`` without importing any SDK package, creating
    workers, or opening a transport.  The access directory is returned only
    after every worker has completed startup.
    """

    profiles = _parse_deployment(value)
    if not profiles:
        return None

    workers: list[ServiceReadWorker] = []
    subject_access: dict[str, ReadAccess] = {}
    try:
        for profile in profiles:
            worker = _build_worker(profile)
            workers.append(worker)
            await worker.start()
            subject_access[profile.subject] = ReadAccess(
                worker,
                allow_account_refs=profile.account_grants,
                allow_account_book_refs=profile.account_book_grants,
                allow_order_scope_refs=profile.order_grants,
                allow_order_submit_scope_refs=profile.order_submit_grants,
                allow_paper_submit_account_ids=profile.paper_submit_grants,
                allow_paper_legacy_import_account_ids=profile.paper_legacy_import_grants,
                allow_approved_target_scope_refs=profile.approved_target_grants,
                allow_monitor_scope_refs=profile.monitor_grants,
                allow_portfolio_refs=profile.portfolio_grants,
                portfolio_analytics_bindings=profile.portfolio_analytics_bindings,
                allow_risk_policy_budget_refs=profile.risk_policy_budget_grants,
                risk_policy_budget_bindings=profile.risk_policy_budget_bindings,
                strategy_book_bindings=profile.strategy_book_bindings,
                order_submit_bindings=profile.order_submit_bindings,
                paper_submit_bindings=profile.paper_submit_bindings,
                paper_legacy_import_bindings=profile.paper_legacy_import_bindings,
                approved_target_bindings=profile.approved_target_bindings,
                application_identity=profile.identity,
            )
        directory = ServiceReadAccessDirectory(subject_access)
        return ServiceReadDeployment(tuple(workers), directory)
    except BaseException as error:
        partial = ServiceReadDeployment(tuple(workers), ServiceReadAccessDirectory({}))
        try:
            await partial.aclose()
        except BaseException:
            pass
        raise ServiceReadDeploymentError(
            "START_FAILED",
            cause_type=type(error).__name__,
            failures=partial.close_failures,
            deployment=partial,
        ) from None


def _build_worker(profile: _SubjectProfile) -> ServiceReadWorker:
    """Build the default fixed-thread worker for one fully validated profile."""

    def create_session() -> SdkServiceReadSession:
        return SdkServiceReadSession(
            lambda: _create_runtime(profile),
            profile.identity,
            account_bindings=profile.account_bindings,
            account_book_bindings=profile.account_book_bindings,
            order_bindings=profile.order_bindings,
            order_submit_bindings=profile.order_submit_bindings,
            paper_submit_bindings=profile.paper_submit_bindings,
            paper_legacy_import_bindings=profile.paper_legacy_import_bindings,
            approved_target_bindings=profile.approved_target_bindings,
            monitor_bindings=profile.monitor_bindings,
            portfolio_analytics_bindings=profile.portfolio_analytics_bindings,
            risk_policy_budget_bindings=profile.risk_policy_budget_bindings,
        )

    stable_name = hashlib.sha256(profile.subject.encode("utf-8")).hexdigest()[:12]
    return ServiceReadWorker(
        create_session,
        max_queue_size=profile.max_queue_size,
        maintenance_interval_seconds=profile.maintenance_interval_seconds,
        name=f"afi-service-read-{stable_name}",
    )


def _create_runtime(profile: _SubjectProfile) -> Any:
    """Create the SDK runtime from deployment-held identity and key material."""

    try:
        from bt_api_py.service_runtime import (
            ClientCurveKeys,
            ServiceClientRuntime,
            ZmqTransportFactory,
        )
    except ImportError:
        raise ServiceReadDeploymentError("SDK_NOT_INSTALLED") from None

    transport_keys = {
        security_ref: ClientCurveKeys(server_key, public_key, secret_key)
        for security_ref, (server_key, public_key, secret_key) in profile.curve_keys.items()
    }
    requested_operations: dict[str, frozenset[str]] = {}
    if profile.account_bindings:
        requested_operations["application.account"] = frozenset(
            {"account.snapshot", "account.head"}
        )
    if profile.order_bindings or profile.account_book_bindings:
        operations: set[str] = set()
        if profile.order_bindings:
            operations.add("orders.query")
        if profile.account_book_bindings:
            operations.add("execution.account_books.query")
        requested_operations["application.order_query"] = frozenset(operations)
    has_submit = bool(profile.order_submit_bindings or profile.paper_submit_bindings)
    if has_submit and profile.approved_target_bindings:
        # Runtime requests operations per mount, so a mixed write profile would
        # widen each selector to both operations. Keep the trusted selectors
        # in separate application identities instead.
        raise ServiceReadDeploymentError("MIXED_ORDER_WRITE_PROFILE")
    if has_submit:
        requested_operations["application.orders"] = frozenset({"orders.submit"})
    if profile.approved_target_bindings:
        requested_operations["application.orders"] = frozenset(
            {"orders.submit_approved_target"}
        )
    if profile.portfolio_analytics_bindings:
        requested_operations["application.risk_analysis"] = frozenset(
            {
                "analysis.input_upload",
                "analysis.submit",
                "analysis.query",
                "analysis.cancel",
            }
        )
    if profile.risk_policy_budget_bindings:
        budget_operation_sets = {
            binding.operations for binding in profile.risk_policy_budget_bindings.values()
        }
        if len(budget_operation_sets) != 1:
            raise ServiceReadDeploymentError("MIXED_RISK_POLICY_BUDGET_ACTOR_ROLES")
        requested_operations["application.risk_policy"] = next(iter(budget_operation_sets))
    if profile.paper_legacy_import_bindings:
        requested_operations["application.paper_legacy_import"] = (
            PAPER_LEGACY_IMPORT_OPERATIONS
        )
    return ServiceClientRuntime(
        profile.client_config,
        identity=profile.identity,
        scope_resolver=lambda scope_ref: _lookup(profile.scopes, scope_ref),
        peer_resolver=lambda service_id: _lookup(profile.peer_identities, service_id),
        transport_factory=ZmqTransportFactory(transport_keys),
        requested_operations=requested_operations or None,
    )


def _lookup(mapping: Mapping[str, Any], key: str) -> Any:
    try:
        return mapping[key]
    except KeyError:
        raise KeyError("unconfigured trusted service reference") from None


def _parse_deployment(value: SecretStr | str | None) -> tuple[_SubjectProfile, ...]:
    if value is None:
        return ()
    if isinstance(value, SecretStr):
        raw_text = value.get_secret_value()
    elif type(value) is str:
        raw_text = value
    else:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")
    if not raw_text:
        return ()
    try:
        raw_bytes = raw_text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT") from None
    if len(raw_bytes) > _MAX_DEPLOYMENT_BYTES:
        raise ServiceReadDeploymentError("DEPLOYMENT_TOO_LARGE")
    try:
        decoded = json.loads(
            raw_text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, TypeError, RecursionError):
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT") from None
    if type(decoded) is not dict or set(decoded) != {"schema_version", "subjects"}:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")
    if type(decoded["schema_version"]) is not int or decoded["schema_version"] != 1:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")
    subjects = decoded["subjects"]
    if type(subjects) is not list or not subjects or len(subjects) > _MAX_SUBJECTS:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")

    has_paper_bindings = any(
        type(profile) is dict and "paper_submit_bindings" in profile for profile in subjects
    )
    has_paper_import_bindings = any(
        type(profile) is dict and "paper_legacy_import_bindings" in profile
        for profile in subjects
    )
    sdk = _load_sdk_types(
        include_paper=has_paper_bindings or has_paper_import_bindings,
        include_paper_import=has_paper_import_bindings,
    )
    profiles: list[_SubjectProfile] = []
    seen_subjects: set[str] = set()
    seen_identities: set[tuple[str, str, str | None]] = set()
    try:
        for raw_profile in subjects:
            profile = _parse_profile(raw_profile, sdk)
            if profile.subject in seen_subjects:
                raise ServiceReadDeploymentError("DUPLICATE_SUBJECT")
            identity_key = (
                profile.identity.principal_ref,
                profile.identity.actor_ref,
                profile.identity.delegate_ref,
            )
            if identity_key in seen_identities:
                raise ServiceReadDeploymentError("IDENTITY_SHARED")
            seen_subjects.add(profile.subject)
            seen_identities.add(identity_key)
            profiles.append(profile)
    except ServiceReadDeploymentError:
        raise
    except Exception:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT") from None
    return tuple(sorted(profiles, key=lambda item: item.subject))


def _load_sdk_types(
    *, include_paper: bool = False, include_paper_import: bool = False
) -> Mapping[str, Any]:
    """Import optional SDK schemas only when an explicit deployment is present."""

    try:
        from bt_api_base.account_protocol import AccountKey, AccountResourceKey
        from bt_api_base.service_protocol import WireIdentity, WireRole, WireScope
        from bt_api_py.service_config import parse_client_config
    except ImportError:
        raise ServiceReadDeploymentError("SDK_NOT_INSTALLED") from None
    result = {
        "AccountKey": AccountKey,
        "AccountResourceKey": AccountResourceKey,
        "WireIdentity": WireIdentity,
        "WireRole": WireRole,
        "WireScope": WireScope,
        "parse_client_config": parse_client_config,
    }
    if include_paper:
        try:
            from bt_api_execution import ExecutionScope, PaperOwnerDomainV1
            from bt_api_execution.paper_execution import PAPER_ENVIRONMENT, PAPER_PROVIDER
        except ImportError:
            raise ServiceReadDeploymentError("PAPER_EXECUTION_NOT_INSTALLED") from None
        result.update(
            {
                "ExecutionScope": ExecutionScope,
                "PaperOwnerDomainV1": PaperOwnerDomainV1,
                "PAPER_ENVIRONMENT": PAPER_ENVIRONMENT,
                "PAPER_PROVIDER": PAPER_PROVIDER,
            }
        )
    if include_paper_import:
        try:
            from bt_api_execution.paper_legacy_import import LegacyPaperSymbolBindingV1
        except ImportError:
            raise ServiceReadDeploymentError("PAPER_EXECUTION_NOT_INSTALLED") from None
        result["LegacyPaperSymbolBindingV1"] = LegacyPaperSymbolBindingV1
    return result


def _parse_profile(raw: object, sdk: Mapping[str, Any]) -> _SubjectProfile:
    required_fields = {
        "subject",
        "identity",
        "client_config",
        "scope_claims",
        "peer_identities",
        "curve_keys",
        "grants",
        "account_bindings",
        "order_bindings",
        "monitor_bindings",
        "worker",
    }
    optional_fields = {
        "account_book_bindings",
        "strategy_book_bindings",
        "order_submit_bindings",
        "approved_target_bindings",
        "portfolio_analytics_bindings",

        "paper_submit_bindings",
        "paper_legacy_import_bindings",
        "risk_policy_budget_bindings",
    }
    if (
        type(raw) is not dict
        or not required_fields <= set(raw)
        or set(raw) - required_fields - optional_fields
    ):
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")
    profile = raw
    subject = _identifier(profile["subject"])
    identity_raw = _exact_mapping(
        profile["identity"], {"principal_ref", "actor_ref", "delegate_ref"}
    )
    if identity_raw["delegate_ref"] is not None:
        delegate_ref = _identifier(identity_raw["delegate_ref"])
    else:
        delegate_ref = None
    identity = sdk["WireIdentity"](
        sdk["WireRole"].APPLICATION_CLIENT,
        _identifier(identity_raw["principal_ref"]),
        _identifier(identity_raw["actor_ref"]),
        delegate_ref,
    )

    client_raw = profile["client_config"]
    if type(client_raw) is not dict:
        raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
    try:
        client_config = sdk["parse_client_config"](client_raw)
        client_public = client_config.to_public_dict()
    except Exception:
        raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG") from None
    if (
        client_config.process_role != "application_client"
        or client_config.registration.get("application_ref") != identity.actor_ref
    ):
        raise ServiceReadDeploymentError("CLIENT_IDENTITY_MISMATCH")

    scopes_raw = profile["scope_claims"]
    if (
        type(scopes_raw) is not dict
        or not scopes_raw
        or len(scopes_raw) > _MAX_BINDINGS_PER_SUBJECT
    ):
        raise ServiceReadDeploymentError("INVALID_SCOPES")
    scopes: dict[str, Any] = {}
    for scope_ref, scope_raw in scopes_raw.items():
        scope_ref = _identifier(scope_ref)
        if type(scope_raw) is not dict or set(scope_raw) - _SCOPE_FIELDS:
            raise ServiceReadDeploymentError("INVALID_SCOPES")
        scope_arguments = dict(scope_raw)
        if "execution_domain_ref" not in scope_arguments:
            raise ServiceReadDeploymentError("INVALID_SCOPES")
        if "account_refs" in scope_arguments:
            if type(scope_arguments["account_refs"]) is not list:
                raise ServiceReadDeploymentError("INVALID_SCOPES")
            scope_arguments["account_refs"] = tuple(scope_arguments["account_refs"])
        scopes[scope_ref] = sdk["WireScope"](**scope_arguments)

    peers_raw = profile["peer_identities"]
    if type(peers_raw) is not dict or not peers_raw or len(peers_raw) > _MAX_BINDINGS_PER_SUBJECT:
        raise ServiceReadDeploymentError("INVALID_PEERS")
    peers: dict[str, Any] = {}
    for service_id, peer_raw in peers_raw.items():
        service_id = _identifier(service_id)
        peer = _exact_mapping(peer_raw, {"principal_ref", "actor_ref"})
        actor_ref = _identifier(peer["actor_ref"])
        if actor_ref != service_id:
            raise ServiceReadDeploymentError("INVALID_PEERS")
        peers[service_id] = sdk["WireIdentity"](
            sdk["WireRole"].SERVICE,
            _identifier(peer["principal_ref"]),
            actor_ref,
        )

    key_raw = profile["curve_keys"]
    if type(key_raw) is not dict or not key_raw or len(key_raw) > _MAX_BINDINGS_PER_SUBJECT:
        raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
    curve_keys: dict[str, tuple[bytes, bytes, bytes]] = {}
    for security_ref, raw_keys in key_raw.items():
        security_ref = _identifier(security_ref)
        keys = _exact_mapping(raw_keys, {"server_key", "public_key", "secret_key"})
        encoded = tuple(
            _curve_key(keys[name]) for name in ("server_key", "public_key", "secret_key")
        )
        curve_keys[security_ref] = encoded  # type: ignore[assignment]

    account_bindings = _parse_account_bindings(profile["account_bindings"], sdk)
    account_book_bindings = _parse_account_book_bindings(
        profile.get("account_book_bindings", {}), sdk
    )
    strategy_book_bindings = _parse_strategy_book_bindings(
        profile.get("strategy_book_bindings", {}), account_book_bindings
    )
    order_bindings = _parse_order_bindings(profile["order_bindings"])
    order_submit_bindings = _parse_order_submit_bindings(
        profile.get("order_submit_bindings", {}), scopes
    )
    approved_target_bindings = _parse_approved_target_bindings(
        profile.get("approved_target_bindings", {}), scopes
    )
    paper_submit_bindings = _parse_paper_submit_bindings(
        profile.get("paper_submit_bindings", {}), scopes, order_bindings, sdk
    )
    paper_legacy_import_bindings = _parse_paper_legacy_import_bindings(
        profile.get("paper_legacy_import_bindings", {}),
        subject,
        paper_submit_bindings,
        sdk,
    )
    if set(order_submit_bindings) & set(approved_target_bindings):
        raise ServiceReadDeploymentError("DUPLICATE_ORDER_WRITE_SCOPE")
    if paper_submit_bindings and (order_submit_bindings or approved_target_bindings):
        raise ServiceReadDeploymentError("MIXED_PAPER_ORDER_WRITE_PROFILE")
    if set(binding.scope_ref for binding in paper_submit_bindings.values()) & set(
        order_submit_bindings
    ):
        raise ServiceReadDeploymentError("DUPLICATE_ORDER_WRITE_SCOPE")
    monitor_bindings = _parse_monitor_bindings(profile["monitor_bindings"])
    portfolio_analytics_bindings = _parse_portfolio_analytics_bindings(
        profile.get("portfolio_analytics_bindings", {}), scopes
    )
    risk_policy_budget_bindings = _parse_risk_policy_budget_bindings(
        profile.get("risk_policy_budget_bindings", {}),
        scopes,
        subject=subject,
        principal_ref=identity.principal_ref,
    )
    grants_fields = {"account_refs", "order_scope_refs", "monitor_scope_refs"}
    book_grant_fields = {"account_book_refs", "strategy_book_refs"}
    optional_grant_fields = book_grant_fields | {
        "order_submit_scope_refs",
        "approved_target_scope_refs",
        "portfolio_refs",

        "paper_submit_account_ids",
        "paper_legacy_import_account_ids",
        "risk_policy_budget_refs",
    }
    grants_raw = profile["grants"]
    if (
        type(grants_raw) is not dict
        or not grants_fields <= set(grants_raw)
        or set(grants_raw) - grants_fields - optional_grant_fields
        or (bool(set(grants_raw) & book_grant_fields) and not book_grant_fields <= set(grants_raw))
    ):
        raise ServiceReadDeploymentError("INVALID_GRANTS")
    account_grants = frozenset(_string_list(grants_raw["account_refs"]))
    account_book_grants = frozenset(_string_list(grants_raw.get("account_book_refs", [])))
    strategy_book_grants = frozenset(_string_list(grants_raw.get("strategy_book_refs", [])))
    order_grants = frozenset(_string_list(grants_raw["order_scope_refs"]))
    order_submit_grants = frozenset(
        _string_list(grants_raw.get("order_submit_scope_refs", []))
    )
    approved_target_grants = frozenset(
        _string_list(grants_raw.get("approved_target_scope_refs", []))
    )
    paper_submit_grants = frozenset(
        _string_list(grants_raw.get("paper_submit_account_ids", []))
    )
    paper_legacy_import_grants = frozenset(
        _string_list(grants_raw.get("paper_legacy_import_account_ids", []))
    )
    monitor_grants = frozenset(_string_list(grants_raw["monitor_scope_refs"]))
    portfolio_grants = frozenset(_string_list(grants_raw.get("portfolio_refs", [])))
    risk_policy_budget_grants = frozenset(
        _string_list(grants_raw.get("risk_policy_budget_refs", []))
    )
    if (
        account_grants != frozenset(account_bindings)
        or account_book_grants != frozenset(account_book_bindings)
        or strategy_book_grants != frozenset(strategy_book_bindings)
        or order_grants != frozenset(order_bindings)
        or order_submit_grants != frozenset(order_submit_bindings)
        or approved_target_grants != frozenset(approved_target_bindings)
        or paper_submit_grants != frozenset(paper_submit_bindings)
        or paper_legacy_import_grants != frozenset(paper_legacy_import_bindings)
        or monitor_grants != frozenset(monitor_bindings)
        or portfolio_grants != frozenset(portfolio_analytics_bindings)
        or risk_policy_budget_grants != frozenset(risk_policy_budget_bindings)
        or not (
            account_grants
            or account_book_grants
            or strategy_book_grants
            or order_grants
            or order_submit_grants
            or approved_target_grants
            or paper_submit_grants
            or paper_legacy_import_grants
            or monitor_grants
            or portfolio_grants
            or risk_policy_budget_grants
        )
    ):
        raise ServiceReadDeploymentError("GRANT_BINDING_MISMATCH")
    if any(
        binding.account_ref not in account_book_grants
        for binding in strategy_book_bindings.values()
    ):
        raise ServiceReadDeploymentError("STRATEGY_BOOK_ACCOUNT_NOT_GRANTED")

    worker_raw = profile["worker"]
    if type(worker_raw) is not dict or set(worker_raw) - {
        "max_queue_size",
        "maintenance_interval_seconds",
    }:
        raise ServiceReadDeploymentError("INVALID_WORKER_OPTIONS")
    max_queue_size = worker_raw.get("max_queue_size", 32)
    interval = worker_raw.get("maintenance_interval_seconds", 1.0)
    if type(max_queue_size) is not int or not 1 <= max_queue_size <= _MAX_QUEUE_SIZE:
        raise ServiceReadDeploymentError("INVALID_WORKER_OPTIONS")
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not math.isfinite(interval)
        or interval <= 0
        or interval > _MAX_MAINTENANCE_INTERVAL
    ):
        raise ServiceReadDeploymentError("INVALID_WORKER_OPTIONS")

    _validate_profile_bindings(
        client_public,
        identity,
        subject,
        scopes,
        peers,
        curve_keys,
        account_bindings,
        account_book_bindings,
        order_bindings,
        order_submit_bindings,
        approved_target_bindings,
        paper_submit_bindings,
        paper_legacy_import_bindings,
        monitor_bindings,
        portfolio_analytics_bindings,
        risk_policy_budget_bindings,
    )
    return _SubjectProfile(
        subject=subject,
        identity=identity,
        client_config=client_config,
        scopes=MappingProxyType(scopes),
        peer_identities=MappingProxyType(peers),
        curve_keys=MappingProxyType(curve_keys),
        account_bindings=MappingProxyType(account_bindings),
        account_book_bindings=MappingProxyType(account_book_bindings),
        strategy_book_bindings=MappingProxyType(strategy_book_bindings),
        order_bindings=MappingProxyType(order_bindings),
        order_submit_bindings=MappingProxyType(order_submit_bindings),
        paper_submit_bindings=MappingProxyType(paper_submit_bindings),
        paper_legacy_import_bindings=MappingProxyType(paper_legacy_import_bindings),
        approved_target_bindings=MappingProxyType(approved_target_bindings),
        monitor_bindings=MappingProxyType(monitor_bindings),
        portfolio_analytics_bindings=MappingProxyType(portfolio_analytics_bindings),
        risk_policy_budget_bindings=MappingProxyType(risk_policy_budget_bindings),
        account_grants=account_grants,
        account_book_grants=account_book_grants,
        strategy_book_grants=strategy_book_grants,
        order_grants=order_grants,
        order_submit_grants=order_submit_grants,
        paper_submit_grants=paper_submit_grants,
        paper_legacy_import_grants=paper_legacy_import_grants,
        approved_target_grants=approved_target_grants,
        monitor_grants=monitor_grants,
        portfolio_grants=portfolio_grants,
        risk_policy_budget_grants=risk_policy_budget_grants,
        max_queue_size=max_queue_size,
        maintenance_interval_seconds=float(interval),
    )


def _parse_account_bindings(raw: object, sdk: Mapping[str, Any]) -> dict[str, AccountBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_ACCOUNT_BINDINGS")
    result: dict[str, AccountBinding] = {}
    for account_ref, raw_binding in raw.items():
        account_ref = _identifier(account_ref)
        binding = _exact_mapping(
            raw_binding,
            {"mount", "scope_ref", "currency", "account_key", "coverage", "require_open_orders"},
        )
        coverage_raw = binding["coverage"]
        if type(coverage_raw) is not list or not coverage_raw:
            raise ServiceReadDeploymentError("INVALID_ACCOUNT_BINDINGS")
        try:
            account_key = sdk["AccountKey"].from_dict(binding["account_key"])
            coverage = tuple(sdk["AccountResourceKey"].from_dict(row) for row in coverage_raw)
            result[account_ref] = AccountBinding(
                mount=_identifier(binding["mount"]),
                scope_ref=_identifier(binding["scope_ref"]),
                currency=_identifier(binding["currency"]),
                account_key=account_key,
                coverage=coverage,
                require_open_orders=binding["require_open_orders"],
            )
        except Exception:
            raise ServiceReadDeploymentError("INVALID_ACCOUNT_BINDINGS") from None
    return result


def _parse_account_book_bindings(
    raw: object, sdk: Mapping[str, Any]
) -> dict[str, AccountBookBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_ACCOUNT_BOOK_BINDINGS")
    result: dict[str, AccountBookBinding] = {}
    for account_ref, raw_binding in raw.items():
        account_ref = _identifier(account_ref)
        binding = _exact_mapping(raw_binding, {"mount", "scope_ref", "account_key"})
        try:
            account_key = sdk["AccountKey"].from_dict(binding["account_key"])
            result[account_ref] = AccountBookBinding(
                mount=_identifier(binding["mount"]),
                scope_ref=_identifier(binding["scope_ref"]),
                account_key=account_key,
            )
        except Exception:
            raise ServiceReadDeploymentError("INVALID_ACCOUNT_BOOK_BINDINGS") from None
    return result


def _parse_strategy_book_bindings(
    raw: object,
    account_book_bindings: Mapping[str, AccountBookBinding],
) -> dict[str, StrategyBookBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_STRATEGY_BOOK_BINDINGS")
    result: dict[str, StrategyBookBinding] = {}
    for strategy_ref, raw_binding in raw.items():
        strategy_ref = _identifier(strategy_ref)
        binding = _exact_mapping(raw_binding, {"account_ref", "owner_ref"})
        try:
            account_ref = _identifier(binding["account_ref"])
            owner_ref = _identifier(binding["owner_ref"])
            if account_ref not in account_book_bindings:
                raise ServiceReadDeploymentError("STRATEGY_BOOK_ACCOUNT_NOT_GRANTED")
            result[strategy_ref] = StrategyBookBinding(account_ref, owner_ref)
        except ServiceReadDeploymentError:
            raise
        except Exception:
            raise ServiceReadDeploymentError("INVALID_STRATEGY_BOOK_BINDINGS") from None
    targets = [
        (
            account_book_bindings[binding.account_ref].account_key.account_key_id,
            binding.owner_ref,
        )
        for binding in result.values()
    ]
    if len(targets) != len(set(targets)):
        raise ServiceReadDeploymentError("DUPLICATE_STRATEGY_BOOK_OWNER")
    return result


def _parse_order_bindings(raw: object) -> dict[str, OrderBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_ORDER_BINDINGS")
    result: dict[str, OrderBinding] = {}
    for scope_ref, raw_binding in raw.items():
        scope_ref = _identifier(scope_ref)
        binding = _exact_mapping(raw_binding, {"mount"})
        try:
            result[scope_ref] = OrderBinding(
                mount=_identifier(binding["mount"]),
                scope_ref=scope_ref,
            )
        except Exception:
            raise ServiceReadDeploymentError("INVALID_ORDER_BINDINGS") from None
    return result


def _parse_order_submit_bindings(
    raw: object, scopes: Mapping[str, Any]
) -> dict[str, OrderSubmitBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_ORDER_SUBMIT_BINDINGS")
    result: dict[str, OrderSubmitBinding] = {}
    for scope_ref, raw_binding in raw.items():
        scope_ref = _identifier(scope_ref)
        base_fields = {"mount", "account_ref", "manual_book_ref"}
        fields_with_metadata = base_fields | {"instrument_metadata_versions"}
        if type(raw_binding) is not dict or set(raw_binding) not in (
            base_fields,
            fields_with_metadata,
        ):
            raise ServiceReadDeploymentError("INVALID_ORDER_SUBMIT_BINDINGS")
        binding = raw_binding
        try:
            raw_versions = binding.get("instrument_metadata_versions", {})
            if (
                type(raw_versions) is not dict
                or len(raw_versions) > _MAX_ORDER_INSTRUMENT_METADATA_VERSIONS
            ):
                raise ServiceReadDeploymentError("INVALID_ORDER_SUBMIT_BINDINGS")
            metadata_versions = {
                _identifier(instrument): _identifier(version)
                for instrument, version in raw_versions.items()
            }
            parsed = OrderSubmitBinding(
                mount=_identifier(binding["mount"]),
                scope_ref=scope_ref,
                account_ref=_identifier(binding["account_ref"]),
                manual_book_ref=_identifier(binding["manual_book_ref"]),
                instrument_metadata_versions=metadata_versions,
            )
            scope = scopes.get(scope_ref)
            if (
                parsed.mount != "application.orders"
                or scope is None
                or not _is_manual_order_scope(scope, parsed.account_ref, parsed.manual_book_ref)
            ):
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            result[scope_ref] = parsed
        except ServiceReadDeploymentError:
            raise
        except Exception:
            raise ServiceReadDeploymentError("INVALID_ORDER_SUBMIT_BINDINGS") from None
    return result


def _parse_paper_submit_bindings(
    raw: object,
    scopes: Mapping[str, Any],
    order_bindings: Mapping[str, OrderBinding],
    sdk: Mapping[str, Any],
) -> dict[str, PaperSubmitBinding]:
    """Parse only server-owned paper domains and exact authenticated scopes."""

    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_PAPER_SUBMIT_BINDINGS")
    result: dict[str, PaperSubmitBinding] = {}
    for legacy_account_id, raw_binding in raw.items():
        if type(raw_binding) is dict and _paper_risk_monitor_selected(raw_binding):
            raise ServiceReadDeploymentError("PAPER_RISK_MONITOR_UNSUPPORTED")
        if type(raw_binding) is dict and "control_mode" not in raw_binding:
            raise ServiceReadDeploymentError("PAPER_CONTROL_MODE_REQUIRED")
        legacy_account_id = _identifier(legacy_account_id)
        binding = _exact_mapping(
            raw_binding,
            {
                "control_mode",
                "mount",
                "scope_ref",
                "query_scope_ref",
                "account_ref",
                "execution_domain_ref",
                "strategy_ref",
                "paper_owner_domain",
                "execution_scope",
            },
        )
        try:
            if type(binding["control_mode"]) is not str:
                raise ServiceReadDeploymentError("INVALID_PAPER_CONTROL_MODE")
            control_mode = _identifier(binding["control_mode"])
            if control_mode not in PAPER_CONTROL_MODES:
                if "risk" in control_mode.lower() or "monitor" in control_mode.lower():
                    raise ServiceReadDeploymentError("PAPER_RISK_MONITOR_UNSUPPORTED")
                raise ServiceReadDeploymentError("INVALID_PAPER_CONTROL_MODE")
            mount = _identifier(binding["mount"])
            scope_ref = _identifier(binding["scope_ref"])
            query_scope_ref = _identifier(binding["query_scope_ref"])
            account_ref = _identifier(binding["account_ref"])
            execution_domain_ref = _identifier(binding["execution_domain_ref"])
            strategy_ref = _identifier(binding["strategy_ref"])
            if mount != "application.orders" or query_scope_ref not in order_bindings:
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            domain = sdk["PaperOwnerDomainV1"].from_payload(binding["paper_owner_domain"])
            wire_scope = scopes.get(scope_ref)
            query_scope = scopes.get(query_scope_ref)
            if wire_scope is None or query_scope is None:
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            execution_fields = _exact_mapping(
                binding["execution_scope"],
                {"provider", "environment", "account_ref", "strategy_id", "trading_day"},
            )
            execution_scope = sdk["ExecutionScope"](
                _identifier(execution_fields["provider"]),
                _identifier(execution_fields["environment"]),
                _identifier(execution_fields["account_ref"]),
                _identifier(execution_fields["strategy_id"]),
                None
                if execution_fields["trading_day"] is None
                else _identifier(execution_fields["trading_day"]),
            )
            parsed = PaperSubmitBinding(
                control_mode=control_mode,
                mount=mount,
                scope_ref=scope_ref,
                query_scope_ref=query_scope_ref,
                legacy_account_id=legacy_account_id,
                account_ref=account_ref,
                execution_domain_ref=execution_domain_ref,
                strategy_ref=strategy_ref,
                paper_owner_domain=domain,
                wire_scope=wire_scope,
                execution_scope=execution_scope,
            )
            if (
                execution_scope.provider != sdk["PAPER_PROVIDER"]
                or execution_scope.environment != sdk["PAPER_ENVIRONMENT"]
                or query_scope.execution_domain_ref != execution_domain_ref
                or query_scope.account_ref != account_ref
                or query_scope.account_refs
                or query_scope.strategy_ref != strategy_ref
                or query_scope.run_id is not None
                or query_scope.manual_book_ref is not None
                or query_scope.portfolio_ref is not None
                or query_scope.group_id is not None
                or query_scope.leg_id is not None
            ):
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            result[legacy_account_id] = parsed
        except ServiceReadDeploymentError:
            raise
        except Exception:
            raise ServiceReadDeploymentError("INVALID_PAPER_SUBMIT_BINDINGS") from None
    if len({item.account_ref for item in result.values()}) != len(result):
        raise ServiceReadDeploymentError("DUPLICATE_PAPER_OWNER_DOMAIN")
    return result


def _parse_paper_legacy_import_bindings(
    raw: object,
    owner_subject: str,
    paper_bindings: Mapping[str, PaperSubmitBinding],
    sdk: Mapping[str, Any],
) -> dict[str, PaperLegacyImportBinding]:
    """Parse separately granted import scopes and server-owned symbol maps."""

    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_PAPER_LEGACY_IMPORT_BINDINGS")
    result: dict[str, PaperLegacyImportBinding] = {}
    for legacy_account_id, raw_binding in raw.items():
        legacy_account_id = _identifier(legacy_account_id)
        paper_binding = paper_bindings.get(legacy_account_id)
        if paper_binding is None:
            raise ServiceReadDeploymentError("PAPER_LEGACY_IMPORT_BINDING_MISMATCH")
        fields = _exact_mapping(raw_binding, {"mount", "scope_ref", "symbol_bindings"})
        mount = _identifier(fields["mount"])
        scope_ref = _identifier(fields["scope_ref"])
        raw_symbols = fields["symbol_bindings"]
        if (
            mount != "application.paper_legacy_import"
            or scope_ref != paper_binding.scope_ref
            or type(raw_symbols) is not list
            or len(raw_symbols) > _MAX_BINDINGS_PER_SUBJECT
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        symbols: list[Any] = []
        for raw_symbol in raw_symbols:
            symbol = _exact_mapping(raw_symbol, {"legacy_symbol", "target_instrument"})
            try:
                symbols.append(
                    sdk["LegacyPaperSymbolBindingV1"](
                        _identifier(symbol["legacy_symbol"]),
                        _identifier(symbol["target_instrument"]),
                    )
                )
            except Exception:
                raise ServiceReadDeploymentError(
                    "INVALID_PAPER_LEGACY_SYMBOL_BINDINGS"
                ) from None
        try:
            result[legacy_account_id] = PaperLegacyImportBinding(
                mount=mount,
                owner_subject=owner_subject,
                legacy_account_id=legacy_account_id,
                scope_ref=scope_ref,
                paper_binding=paper_binding,
                symbol_bindings=tuple(symbols),
            )
        except Exception:
            raise ServiceReadDeploymentError(
                "INVALID_PAPER_LEGACY_IMPORT_BINDINGS"
            ) from None
    return result


def _paper_risk_monitor_selected(binding: Mapping[str, Any]) -> bool:
    for key, value in binding.items():
        if type(key) is str and (
            key in {"risk", "monitor"}
            or key.startswith(("risk_", "monitor_"))
        ):
            return True
        if key in {"controls", "required_controls", "enabled_components"}:
            if type(value) is list and any(
                type(item) is str and item.lower() in {"risk", "monitor"}
                for item in value
            ):
                return True
    return False


def _parse_approved_target_bindings(
    raw: object, scopes: Mapping[str, Any]
) -> dict[str, ApprovedTargetSubmitBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_APPROVED_TARGET_BINDINGS")
    result: dict[str, ApprovedTargetSubmitBinding] = {}
    for scope_ref, raw_binding in raw.items():
        scope_ref = _identifier(scope_ref)
        binding = _exact_mapping(
            raw_binding,
            {"mount", "account_ref", "strategy_ref", "expected_scope_ref"},
        )
        try:
            mount = _identifier(binding["mount"])
            account_ref = _identifier(binding["account_ref"])
            strategy_ref = _identifier(binding["strategy_ref"])
            expected_scope_ref = _identifier(binding["expected_scope_ref"])
            wire_scope = scopes.get(scope_ref)
            if (
                mount != "application.orders"
                or wire_scope is None
                or not _is_approved_target_scope(wire_scope, account_ref, strategy_ref)
            ):
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            result[scope_ref] = ApprovedTargetSubmitBinding(
                mount=mount,
                scope_ref=scope_ref,
                account_ref=account_ref,
                strategy_ref=strategy_ref,
                expected_scope_ref=expected_scope_ref,
                wire_scope=wire_scope,
            )
        except ServiceReadDeploymentError:
            raise
        except Exception:
            raise ServiceReadDeploymentError("INVALID_APPROVED_TARGET_BINDINGS") from None
    return result


def _parse_monitor_bindings(raw: object) -> dict[str, MonitorBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_MONITOR_BINDINGS")
    result: dict[str, MonitorBinding] = {}
    for scope_ref, raw_binding in raw.items():
        scope_ref = _identifier(scope_ref)
        binding = _exact_mapping(raw_binding, {"mount", "strategy_ref"})
        try:
            result[scope_ref] = MonitorBinding(
                mount=_identifier(binding["mount"]),
                scope_ref=scope_ref,
                strategy_ref=_identifier(binding["strategy_ref"]),
            )
        except Exception:
            raise ServiceReadDeploymentError("INVALID_MONITOR_BINDINGS") from None
    return result


def _parse_portfolio_analytics_bindings(
    raw: object, scopes: Mapping[str, Any]
) -> dict[str, PortfolioAnalyticsBinding]:
    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_PORTFOLIO_ANALYTICS_BINDINGS")
    result: dict[str, PortfolioAnalyticsBinding] = {}
    for raw_portfolio_ref, raw_binding in raw.items():
        portfolio_ref = _identifier(raw_portfolio_ref)
        binding = _exact_mapping(raw_binding, {"mount", "scope_ref"})
        try:
            configured = PortfolioAnalyticsBinding(
                mount=_identifier(binding["mount"]),
                scope_ref=_identifier(binding["scope_ref"]),
                portfolio_ref=portfolio_ref,
            )
        except Exception:
            raise ServiceReadDeploymentError("INVALID_PORTFOLIO_ANALYTICS_BINDINGS") from None
        scope = scopes.get(configured.scope_ref)
        if not _is_portfolio_analytics_scope(scope, portfolio_ref):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        result[portfolio_ref] = configured
    return result


def _parse_risk_policy_budget_bindings(
    raw: object,
    scopes: Mapping[str, Any],
    *,
    subject: str,
    principal_ref: str,
) -> dict[str, RiskPolicyBudgetBinding]:
    """Parse trusted actor assignment and exact pool/member scopes."""

    if type(raw) is not dict or len(raw) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_RISK_POLICY_BUDGET_BINDINGS")
    result: dict[str, RiskPolicyBudgetBinding] = {}
    for raw_portfolio_ref, raw_binding in raw.items():
        portfolio_ref = _identifier(raw_portfolio_ref)
        base_fields = {
            "mount",
            "pool_ref",
            "management_scope_ref",
            "member_scope_refs",
        }
        actor_fields = base_fields | {
            "owner_subject",
            "actor_role",
            "maker_principal_ref",
            "checker_principal_ref",
        }
        if type(raw_binding) is not dict:
            raise ServiceReadDeploymentError("INVALID_RISK_POLICY_BUDGET_BINDINGS")
        if set(raw_binding) == base_fields:
            fields = raw_binding
            owner_subject = subject
            actor_role = "maker"
            maker_principal_ref = principal_ref
            checker_principal_ref = None
        elif set(raw_binding) == actor_fields:
            fields = raw_binding
            owner_subject = _identifier(fields["owner_subject"])
            actor_role = _identifier(fields["actor_role"])
            maker_principal_ref = _identifier(fields["maker_principal_ref"])
            checker_principal_ref = _identifier(fields["checker_principal_ref"])
        else:
            raise ServiceReadDeploymentError("INVALID_RISK_POLICY_BUDGET_BINDINGS")
        if (
            actor_role not in {"maker", "checker"}
            or maker_principal_ref == checker_principal_ref
            or (
                actor_role == "maker"
                and (subject != owner_subject or principal_ref != maker_principal_ref)
            )
            or (
                actor_role == "checker"
                and (subject == owner_subject or principal_ref != checker_principal_ref)
            )
        ):
            raise ServiceReadDeploymentError("RISK_POLICY_BUDGET_ACTOR_MISMATCH")
        mount = _identifier(fields["mount"])
        pool_ref = _identifier(fields["pool_ref"])
        management_scope_ref = _identifier(fields["management_scope_ref"])
        raw_members = fields["member_scope_refs"]
        if type(raw_members) is not dict or not raw_members or len(raw_members) > _MAX_SELECTORS:
            raise ServiceReadDeploymentError("INVALID_RISK_POLICY_BUDGET_BINDINGS")
        member_scope_refs = {
            _identifier(account_ref): _identifier(scope_ref)
            for account_ref, scope_ref in raw_members.items()
        }
        if len(set(member_scope_refs.values())) != len(member_scope_refs):
            raise ServiceReadDeploymentError("INVALID_RISK_POLICY_BUDGET_BINDINGS")
        management = scopes.get(management_scope_ref)
        if (
            mount != "application.risk_policy"
            or not _is_budget_management_scope(
                management, portfolio_ref, frozenset(member_scope_refs)
            )
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        execution_domain_ref = management.execution_domain_ref
        for account_ref, scope_ref in member_scope_refs.items():
            if not _is_budget_member_scope(
                scopes.get(scope_ref),
                portfolio_ref,
                account_ref,
                execution_domain_ref,
            ):
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        try:
            result[portfolio_ref] = RiskPolicyBudgetBinding(
                mount=mount,
                pool_ref=pool_ref,
                portfolio_ref=portfolio_ref,
                management_scope_ref=management_scope_ref,
                member_scope_refs=member_scope_refs,
                owner_subject=owner_subject,
                actor_role=actor_role,
                maker_principal_ref=maker_principal_ref,
                checker_principal_ref=checker_principal_ref,
            )
        except Exception:
            raise ServiceReadDeploymentError("INVALID_RISK_POLICY_BUDGET_BINDINGS") from None
    return result


def _validate_profile_bindings(
    client_config: Mapping[str, Any],
    identity: Any,
    subject: str,
    scopes: Mapping[str, Any],
    peers: Mapping[str, Any],
    curve_keys: Mapping[str, Any],
    account_bindings: Mapping[str, AccountBinding],
    account_book_bindings: Mapping[str, AccountBookBinding],
    order_bindings: Mapping[str, OrderBinding],
    order_submit_bindings: Mapping[str, OrderSubmitBinding],
    approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding],
    paper_submit_bindings: Mapping[str, PaperSubmitBinding],
    paper_legacy_import_bindings: Mapping[str, PaperLegacyImportBinding],
    monitor_bindings: Mapping[str, MonitorBinding],
    portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding],
    risk_policy_budget_bindings: Mapping[str, RiskPolicyBudgetBinding],
) -> None:
    declared: dict[tuple[str, str], tuple[str, str | None]] = {}
    budget_management_portfolios: dict[tuple[str, str], str] = {}
    for account_ref, binding in account_bindings.items():
        scope = scopes.get(binding.scope_ref)
        if (
            binding.mount != "application.account"
            or scope is None
            or scope.account_ref != account_ref
            or scope.account_refs
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        _add_declared(declared, binding.mount, binding.scope_ref, account_ref)
    for account_ref, binding in account_book_bindings.items():
        scope = scopes.get(binding.scope_ref)
        if (
            binding.mount != "application.order_query"
            or scope is None
            or scope.account_ref != account_ref
            or not _is_account_scope(scope)
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        snapshot_binding = account_bindings.get(account_ref)
        if (
            snapshot_binding is not None
            and snapshot_binding.account_key.account_key_id != binding.account_key.account_key_id
        ):
            raise ServiceReadDeploymentError("ACCOUNT_BOOK_KEY_MISMATCH")
        _add_declared(declared, binding.mount, binding.scope_ref, account_ref)
    for scope_ref, binding in order_bindings.items():
        if binding.mount != "application.order_query" or scope_ref not in scopes:
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        scope = scopes[scope_ref]
        _add_declared(declared, binding.mount, scope_ref, scope.account_ref)
    for scope_ref, binding in order_submit_bindings.items():
        scope = scopes.get(scope_ref)
        if (
            binding.mount != "application.orders"
            or scope is None
            or not _is_manual_order_scope(scope, binding.account_ref, binding.manual_book_ref)
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        _add_declared(declared, binding.mount, scope_ref, binding.account_ref)
    for legacy_account_id, binding in paper_submit_bindings.items():
        scope = scopes.get(binding.scope_ref)
        query = scopes.get(binding.query_scope_ref)
        if (
            legacy_account_id != binding.legacy_account_id
            or binding.mount != "application.orders"
            or scope is None
            or query is None
            or scope != binding.wire_scope
            or scope.account_ref != binding.account_ref
            or scope.execution_domain_ref != binding.execution_domain_ref
            or scope.strategy_ref != binding.strategy_ref
            or scope.account_refs
            or scope.run_id is not None
            or scope.manual_book_ref is not None
            or scope.portfolio_ref is not None
            or scope.group_id is not None
            or scope.leg_id is not None
            or query.execution_domain_ref != binding.execution_domain_ref
            or query.account_ref != binding.account_ref
            or query.account_refs
            or query.strategy_ref != binding.strategy_ref
            or query.run_id is not None
            or query.manual_book_ref is not None
            or query.portfolio_ref is not None
            or query.group_id is not None
            or query.leg_id is not None
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        _add_declared(declared, binding.mount, binding.scope_ref, binding.account_ref)
    for legacy_account_id, binding in paper_legacy_import_bindings.items():
        paper = paper_submit_bindings.get(legacy_account_id)
        scope = scopes.get(binding.scope_ref)
        if (
            binding.mount != "application.paper_legacy_import"
            or binding.legacy_account_id != legacy_account_id
            or binding.owner_subject != subject
            or paper is None
            or binding.paper_binding is not paper
            or binding.scope_ref != paper.scope_ref
            or scope is None
            or scope != paper.wire_scope
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        paper.paper_owner_domain.validate_binding(paper.wire_scope, paper.execution_scope)
        _add_declared(declared, binding.mount, binding.scope_ref, paper.account_ref)
    for scope_ref, binding in approved_target_bindings.items():
        scope = scopes.get(scope_ref)
        if (
            binding.mount != "application.orders"
            or scope is None
            or not _is_approved_target_scope(scope, binding.account_ref, binding.strategy_ref)
            or scope != binding.wire_scope
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        _add_declared(declared, binding.mount, scope_ref, binding.account_ref)
    for scope_ref, binding in monitor_bindings.items():
        scope = scopes.get(binding.scope_ref)
        if (
            binding.mount != "application.monitor"
            or scope is None
            or scope.strategy_ref != binding.strategy_ref
            or scope.account_refs
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        _add_declared(declared, binding.mount, scope_ref, None)
    for portfolio_ref, binding in portfolio_analytics_bindings.items():
        scope = scopes.get(binding.scope_ref)
        if (
            binding.mount != "application.risk_analysis"
            or not _is_portfolio_analytics_scope(scope, portfolio_ref)
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        _add_declared(declared, binding.mount, binding.scope_ref, portfolio_ref)
    for portfolio_ref, binding in risk_policy_budget_bindings.items():
        management_scope = scopes.get(binding.management_scope_ref)
        member_refs = frozenset(binding.member_scope_refs)
        if (
            binding.mount != "application.risk_policy"
            or binding.portfolio_ref != portfolio_ref
            or not _is_budget_management_scope(
                management_scope, portfolio_ref, member_refs
            )
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        management_pair = (binding.mount, binding.management_scope_ref)
        _add_declared(
            declared, binding.mount, binding.management_scope_ref, None
        )
        previous_portfolio = budget_management_portfolios.get(management_pair)
        if previous_portfolio is not None and previous_portfolio != portfolio_ref:
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        budget_management_portfolios[management_pair] = portfolio_ref
        for account_ref, scope_ref in binding.member_scope_refs.items():
            member_scope = scopes.get(scope_ref)
            if not _is_budget_member_scope(
                member_scope,
                portfolio_ref,
                account_ref,
                management_scope.execution_domain_ref,
            ):
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            _add_declared(declared, binding.mount, scope_ref, account_ref)

    if set(scopes) != {scope_ref for _, scope_ref in declared}:
        raise ServiceReadDeploymentError("UNUSED_SCOPE")

    bindings_by_alias = client_config.get("clients")
    if type(bindings_by_alias) is not dict:
        raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
    observed: dict[tuple[str, str], tuple[str, str | None]] = {}
    used_services: set[str] = set()
    used_transports: set[str] = set()
    for client in bindings_by_alias.values():
        if type(client) is not dict or type(client.get("settings")) is not dict:
            raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
        bindings = client["settings"].get("bindings")
        if type(bindings) is not list:
            raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
        for binding in bindings:
            if type(binding) is not dict:
                raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
            mount = binding.get("mount")
            scope_ref = binding.get("scope_ref")
            if mount not in _DEPLOYMENT_MOUNTS or type(scope_ref) is not str:
                raise ServiceReadDeploymentError("WRITABLE_BINDING_FORBIDDEN")
            pair = (mount, scope_ref)
            if pair in observed or pair not in declared:
                raise ServiceReadDeploymentError("GRANT_BINDING_MISMATCH")
            account_ref = declared[pair][1]
            if mount == "application.risk_analysis":
                if (
                    binding.get("portfolio_ref") != account_ref
                    or binding.get("account_ref") is not None
                ):
                    raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            elif mount == "application.risk_policy" and pair in budget_management_portfolios:
                if (
                    binding.get("portfolio_ref") != budget_management_portfolios[pair]
                    or binding.get("account_ref") is not None
                ):
                    raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            elif mount == "application.risk_policy":
                if (
                    binding.get("account_ref") != account_ref
                    or binding.get("portfolio_ref") is not None
                ):
                    raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            elif binding.get("account_ref") != account_ref:
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            service_id = binding.get("service_id")
            transport_ref = binding.get("transport_ref")
            if type(service_id) is not str or service_id not in peers:
                raise ServiceReadDeploymentError("INVALID_PEERS")
            if type(transport_ref) is not str:
                raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
            observed[pair] = declared[pair]
            used_services.add(service_id)
            used_transports.add(transport_ref)

    if set(observed) != set(declared):
        raise ServiceReadDeploymentError("GRANT_BINDING_MISMATCH")
    if used_services != set(peers):
        raise ServiceReadDeploymentError("INVALID_PEERS")

    communication = client_config.get("communication")
    if type(communication) is not dict:
        raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
    profiles = communication.get("profiles")
    if type(profiles) is not dict or set(profiles) != used_transports:
        raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
    used_security_refs: set[str] = set()
    for transport in profiles.values():
        if type(transport) is not dict:
            raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
        endpoints = transport.get("endpoints")
        security_ref = transport.get("security_profile_ref")
        if type(endpoints) is not dict or "rpc_connect" not in endpoints:
            raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
        if type(security_ref) is not str:
            raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
        used_security_refs.add(security_ref)
    if used_security_refs != set(curve_keys):
        raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
    if identity.role.value != "application_client":
        raise ServiceReadDeploymentError("CLIENT_IDENTITY_MISMATCH")


def _add_declared(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    mount: str,
    scope_ref: str,
    account_ref: str | None,
) -> None:
    pair = (mount, scope_ref)
    previous = declared.get(pair)
    if previous is not None:
        if previous != (mount, account_ref):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        return
    declared[pair] = (mount, account_ref)


def _is_account_scope(scope: Any) -> bool:
    return (
        scope.account_ref is not None
        and not scope.account_refs
        and scope.strategy_ref is None
        and scope.run_id is None
        and scope.manual_book_ref is None
        and scope.portfolio_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _is_portfolio_analytics_scope(scope: Any, portfolio_ref: str) -> bool:
    return (
        scope is not None
        and getattr(scope, "portfolio_ref", None) == portfolio_ref
        and getattr(scope, "run_id", None) is None
        and getattr(scope, "account_ref", None) is None
        and not getattr(scope, "account_refs", ())
        and getattr(scope, "strategy_ref", None) is None
        and getattr(scope, "manual_book_ref", None) is None
        and getattr(scope, "group_id", None) is None
        and getattr(scope, "leg_id", None) is None
    )


def _is_budget_management_scope(
    scope: Any, portfolio_ref: str, account_refs: frozenset[str]
) -> bool:
    return (
        scope is not None
        and getattr(scope, "portfolio_ref", None) == portfolio_ref
        and getattr(scope, "account_ref", None) is None
        and frozenset(getattr(scope, "account_refs", ())) == account_refs
        and bool(getattr(scope, "execution_domain_ref", None))
        and getattr(scope, "run_id", None) is None
        and getattr(scope, "strategy_ref", None) is None
        and getattr(scope, "manual_book_ref", None) is None
        and getattr(scope, "group_id", None) is None
        and getattr(scope, "leg_id", None) is None
    )


def _is_budget_member_scope(
    scope: Any, portfolio_ref: str, account_ref: str, execution_domain_ref: str
) -> bool:
    return (
        scope is not None
        and getattr(scope, "portfolio_ref", None) == portfolio_ref
        and getattr(scope, "account_ref", None) == account_ref
        and not getattr(scope, "account_refs", ())
        and getattr(scope, "execution_domain_ref", None) == execution_domain_ref
        and getattr(scope, "run_id", None) is None
        and getattr(scope, "strategy_ref", None) is None
        and getattr(scope, "manual_book_ref", None) is None
        and getattr(scope, "group_id", None) is None
        and getattr(scope, "leg_id", None) is None
    )


def _is_manual_order_scope(scope: Any, account_ref: str, manual_book_ref: str) -> bool:
    return (
        scope.account_ref == account_ref
        and not scope.account_refs
        and scope.strategy_ref is None
        and scope.manual_book_ref == manual_book_ref
        and scope.run_id is None
        and scope.portfolio_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _is_approved_target_scope(scope: Any, account_ref: str, strategy_ref: str) -> bool:
    return (
        scope.account_ref == account_ref
        and not scope.account_refs
        and scope.strategy_ref == strategy_ref
        and scope.manual_book_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _curve_key(value: object) -> bytes:
    if (
        type(value) is not str
        or len(value) != 40
        or any(character not in _Z85_ALPHABET for character in value)
    ):
        raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
    return value.encode("ascii")


def _identifier(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or value == "*"
        or len(value) > 256
        or not value.isprintable()
    ):
        raise ServiceReadDeploymentError("INVALID_IDENTIFIER")
    return value


def _string_list(value: object) -> tuple[str, ...]:
    if type(value) is not list or len(value) > _MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_GRANTS")
    result = tuple(_identifier(item) for item in value)
    if len(set(result)) != len(result):
        raise ServiceReadDeploymentError("INVALID_GRANTS")
    return result


def _exact_mapping(value: object, keys: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")
