"""Validation and profile-section parsing helpers for service-read deployment."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from app.services.service_read.access import StrategyBookBinding
from app.services.service_read.client import (
    AccountBinding,
    AccountBookBinding,
    ApprovedTargetSubmitBinding,
    MonitorBinding,
    OrderBinding,
    OrderSubmitBinding,
    PaperLegacyImportBinding,
    PaperSubmitBinding,
    PortfolioAnalyticsBinding,
    RiskAccountPolicyBinding,
    RiskPolicyBudgetBinding,
)
from app.utils.invariants import require_present

if TYPE_CHECKING:
    from app.services.service_read.deployment import ServiceReadDeployment

MAX_DEPLOYMENT_BYTES = 262_144
MAX_SUBJECTS = 256
MAX_BINDINGS_PER_SUBJECT = 128
MAX_SELECTORS = 4096
MAX_QUEUE_SIZE = 256
MAX_MAINTENANCE_INTERVAL = 300.0
Z85_ALPHABET = frozenset(
    "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ.-:+=^!/*?&<>()[]{}@%$#"
)
SCOPE_FIELDS = frozenset(
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
READ_MOUNTS = frozenset(
    {
        "application.account",
        "application.order_query",
        "application.monitor",
        "application.risk_analysis",
    }
)
DEPLOYMENT_MOUNTS = READ_MOUNTS | {
    "application.orders",
    "application.risk_policy",
    "application.paper_legacy_import",
}

_GRANT_BINDING_PAIRS: tuple[tuple[str, str], ...] = (
    ("account_refs", "account_bindings"),
    ("account_book_refs", "account_book_bindings"),
    ("strategy_book_refs", "strategy_book_bindings"),
    ("order_scope_refs", "order_bindings"),
    ("order_submit_scope_refs", "order_submit_bindings"),
    ("approved_target_scope_refs", "approved_target_bindings"),
    ("paper_submit_account_ids", "paper_submit_bindings"),
    ("paper_legacy_import_account_ids", "paper_legacy_import_bindings"),
    ("monitor_scope_refs", "monitor_bindings"),
    ("portfolio_refs", "portfolio_analytics_bindings"),
    ("risk_policy_budget_refs", "risk_policy_budget_bindings"),
    ("risk_account_policy_refs", "risk_account_policy_bindings"),
)
_REQUIRED_GRANT_FIELDS = frozenset({"account_refs", "order_scope_refs", "monitor_scope_refs"})
_BOOK_GRANT_FIELDS = frozenset({"account_book_refs", "strategy_book_refs"})
_OPTIONAL_GRANT_FIELDS = _BOOK_GRANT_FIELDS | {
    "order_submit_scope_refs",
    "approved_target_scope_refs",
    "paper_submit_account_ids",
    "paper_legacy_import_account_ids",
    "portfolio_refs",
    "risk_policy_budget_refs",
    "risk_account_policy_refs",
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


def identifier(value: object) -> str:
    """Validate and return a non-empty printable identifier string."""
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


def curve_key(value: object) -> bytes:
    """Validate and ASCII-encode one 40-char Z85 CurveZMQ key."""
    if (
        type(value) is not str
        or len(value) != 40
        or any(character not in Z85_ALPHABET for character in value)
    ):
        raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
    return value.encode("ascii")


def string_list(value: object) -> tuple[str, ...]:
    """Validate a bounded list of unique grant identifier strings."""
    if type(value) is not list or len(value) > MAX_SELECTORS:
        raise ServiceReadDeploymentError("INVALID_GRANTS")
    result = tuple(identifier(item) for item in value)
    if len(set(result)) != len(result):
        raise ServiceReadDeploymentError("INVALID_GRANTS")
    return result


def exact_mapping(value: object, keys: set[str]) -> dict[str, Any]:
    """Validate that a raw JSON object is a dict with the exact expected key set."""
    if type(value) is not dict or set(value) != keys:
        raise ServiceReadDeploymentError("INVALID_DEPLOYMENT")
    return value


def parse_profile_identity(raw_identity: object, sdk: Mapping[str, Any]) -> Any:
    """Parse the subject application client WireIdentity."""
    identity_raw = exact_mapping(raw_identity, {"principal_ref", "actor_ref", "delegate_ref"})
    delegate_ref = (
        identifier(identity_raw["delegate_ref"])
        if identity_raw["delegate_ref"] is not None
        else None
    )
    return sdk["WireIdentity"](
        sdk["WireRole"].APPLICATION_CLIENT,
        identifier(identity_raw["principal_ref"]),
        identifier(identity_raw["actor_ref"]),
        delegate_ref,
    )


def parse_profile_client_config(
    raw_client: object, identity: Any, sdk: Mapping[str, Any]
) -> tuple[Any, dict[str, Any]]:
    """Parse and verify SDK client configuration against the subject identity."""
    if type(raw_client) is not dict:
        raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG")
    try:
        client_config = sdk["parse_client_config"](raw_client)
        client_public = client_config.to_public_dict()
    except Exception:
        raise ServiceReadDeploymentError("INVALID_CLIENT_CONFIG") from None
    if (
        client_config.process_role != "application_client"
        or client_config.registration.get("application_ref") != identity.actor_ref
    ):
        raise ServiceReadDeploymentError("CLIENT_IDENTITY_MISMATCH")
    return client_config, client_public


def parse_profile_scopes(raw_scopes: object, sdk: Mapping[str, Any]) -> dict[str, Any]:
    """Parse declared WireScope objects keyed by scope reference."""
    if type(raw_scopes) is not dict or not raw_scopes or len(raw_scopes) > MAX_BINDINGS_PER_SUBJECT:
        raise ServiceReadDeploymentError("INVALID_SCOPES")
    scopes: dict[str, Any] = {}
    for scope_ref, scope_raw in raw_scopes.items():
        scope_ref = identifier(scope_ref)
        if type(scope_raw) is not dict or set(scope_raw) - SCOPE_FIELDS:
            raise ServiceReadDeploymentError("INVALID_SCOPES")
        scope_arguments = dict(scope_raw)
        if "execution_domain_ref" not in scope_arguments:
            raise ServiceReadDeploymentError("INVALID_SCOPES")
        if "account_refs" in scope_arguments:
            if type(scope_arguments["account_refs"]) is not list:
                raise ServiceReadDeploymentError("INVALID_SCOPES")
            scope_arguments["account_refs"] = tuple(scope_arguments["account_refs"])
        scopes[scope_ref] = sdk["WireScope"](**scope_arguments)
    return scopes


def parse_profile_peers(raw_peers: object, sdk: Mapping[str, Any]) -> dict[str, Any]:
    """Parse expected service peer WireIdentity entries."""
    if type(raw_peers) is not dict or not raw_peers or len(raw_peers) > MAX_BINDINGS_PER_SUBJECT:
        raise ServiceReadDeploymentError("INVALID_PEERS")
    peers: dict[str, Any] = {}
    for service_id, peer_raw in raw_peers.items():
        service_id = identifier(service_id)
        peer = exact_mapping(peer_raw, {"principal_ref", "actor_ref"})
        actor_ref = identifier(peer["actor_ref"])
        if actor_ref != service_id:
            raise ServiceReadDeploymentError("INVALID_PEERS")
        peers[service_id] = sdk["WireIdentity"](
            sdk["WireRole"].SERVICE,
            identifier(peer["principal_ref"]),
            actor_ref,
        )
    return peers


def parse_profile_curve_keys(raw_keys: object) -> dict[str, tuple[bytes, bytes, bytes]]:
    """Parse Z85 CurveZMQ transport key triples per security profile ref."""
    if type(raw_keys) is not dict or not raw_keys or len(raw_keys) > MAX_BINDINGS_PER_SUBJECT:
        raise ServiceReadDeploymentError("INVALID_TRANSPORT_KEYS")
    curve_keys: dict[str, tuple[bytes, bytes, bytes]] = {}
    for security_ref, entry_keys in raw_keys.items():
        security_ref = identifier(security_ref)
        keys = exact_mapping(entry_keys, {"server_key", "public_key", "secret_key"})
        encoded = (
            curve_key(keys["server_key"]),
            curve_key(keys["public_key"]),
            curve_key(keys["secret_key"]),
        )
        curve_keys[security_ref] = encoded
    return curve_keys


def validate_write_binding_exclusivity(
    order_submit_bindings: Mapping[str, OrderSubmitBinding],
    approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding],
    paper_submit_bindings: Mapping[str, PaperSubmitBinding],
) -> None:
    """Enforce mutual exclusion between manual, approved, and paper order write profiles."""
    if set(order_submit_bindings) & set(approved_target_bindings):
        raise ServiceReadDeploymentError("DUPLICATE_ORDER_WRITE_SCOPE")
    if paper_submit_bindings and (order_submit_bindings or approved_target_bindings):
        raise ServiceReadDeploymentError("MIXED_PAPER_ORDER_WRITE_PROFILE")
    if {binding.scope_ref for binding in paper_submit_bindings.values()} & set(
        order_submit_bindings
    ):
        raise ServiceReadDeploymentError("DUPLICATE_ORDER_WRITE_SCOPE")


def parse_and_verify_grants(
    grants_raw: object,
    bindings_by_kind: Mapping[str, Mapping[str, Any]],
    strategy_book_bindings: Mapping[str, StrategyBookBinding],
) -> dict[str, frozenset[str]]:
    """Parse subject grant sets and verify exact 1:1 agreement with bindings."""
    if (
        type(grants_raw) is not dict
        or not _REQUIRED_GRANT_FIELDS <= set(grants_raw)
        or set(grants_raw) - _REQUIRED_GRANT_FIELDS - _OPTIONAL_GRANT_FIELDS
        or (
            bool(set(grants_raw) & _BOOK_GRANT_FIELDS) and not _BOOK_GRANT_FIELDS <= set(grants_raw)
        )
    ):
        raise ServiceReadDeploymentError("INVALID_GRANTS")

    parsed: dict[str, frozenset[str]] = {}
    has_any_grant = False
    for grant_key, binding_key in _GRANT_BINDING_PAIRS:
        grant_set = frozenset(string_list(grants_raw.get(grant_key, [])))
        if grant_set != frozenset(bindings_by_kind[binding_key]):
            raise ServiceReadDeploymentError("GRANT_BINDING_MISMATCH")
        parsed[grant_key] = grant_set
        if grant_set:
            has_any_grant = True

    if not has_any_grant:
        raise ServiceReadDeploymentError("GRANT_BINDING_MISMATCH")
    if any(
        binding.account_ref not in parsed["account_book_refs"]
        for binding in strategy_book_bindings.values()
    ):
        raise ServiceReadDeploymentError("STRATEGY_BOOK_ACCOUNT_NOT_GRANTED")
    return parsed


def parse_worker_options(worker_raw: object) -> tuple[int, float]:
    """Parse bounded worker queue size and maintenance poll interval."""
    if type(worker_raw) is not dict or set(worker_raw) - {
        "max_queue_size",
        "maintenance_interval_seconds",
    }:
        raise ServiceReadDeploymentError("INVALID_WORKER_OPTIONS")
    max_queue_size = worker_raw.get("max_queue_size", 32)
    interval = worker_raw.get("maintenance_interval_seconds", 1.0)
    if type(max_queue_size) is not int or not 1 <= max_queue_size <= MAX_QUEUE_SIZE:
        raise ServiceReadDeploymentError("INVALID_WORKER_OPTIONS")
    if (
        isinstance(interval, bool)
        or not isinstance(interval, (int, float))
        or not math.isfinite(interval)
        or interval <= 0
        or interval > MAX_MAINTENANCE_INTERVAL
    ):
        raise ServiceReadDeploymentError("INVALID_WORKER_OPTIONS")
    return max_queue_size, float(interval)


def add_declared(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    mount: str,
    scope_ref: str,
    account_ref: str | None,
) -> None:
    """Register one `(mount, scope_ref)` declaration or reject conflicting owners."""
    pair = (mount, scope_ref)
    previous = declared.get(pair)
    if previous is not None:
        if previous != (mount, account_ref):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        return
    declared[pair] = (mount, account_ref)


def is_account_scope(scope: Any) -> bool:
    """Check whether a WireScope constrains exactly one account_ref."""
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


def is_portfolio_analytics_scope(scope: Any, portfolio_ref: str) -> bool:
    """Check whether a WireScope is an exact portfolio analytics scope."""
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


def is_budget_management_scope(
    scope: Any, portfolio_ref: str, account_refs: frozenset[str]
) -> bool:
    """Check whether a WireScope matches a risk-policy portfolio budget scope."""
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


def is_budget_member_scope(
    scope: Any, portfolio_ref: str, account_ref: str, execution_domain_ref: str
) -> bool:
    """Check whether a WireScope matches a single portfolio member account scope."""
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


def is_risk_account_policy_scope(scope: Any, account_ref: str) -> bool:
    """Accept only a manual-book scope identical in shape to a Risk target."""
    return (
        scope is not None
        and getattr(scope, "account_ref", None) == account_ref
        and not getattr(scope, "account_refs", ())
        and bool(getattr(scope, "execution_domain_ref", None))
        and bool(getattr(scope, "manual_book_ref", None))
        and getattr(scope, "strategy_ref", None) is None
        and getattr(scope, "run_id", None) is None
        and getattr(scope, "portfolio_ref", None) is None
        and getattr(scope, "group_id", None) is None
        and getattr(scope, "leg_id", None) is None
    )


def is_manual_order_scope(scope: Any, account_ref: str, manual_book_ref: str) -> bool:
    """Check whether a WireScope targets a manual order book for one account."""
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


def is_approved_target_scope(scope: Any, account_ref: str, strategy_ref: str) -> bool:
    """Check whether a WireScope targets an approved strategy execution target."""
    return (
        scope.account_ref == account_ref
        and not scope.account_refs
        and scope.strategy_ref == strategy_ref
        and scope.manual_book_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _is_exact_paper_wire_scope(
    scope: Any,
    *,
    execution_domain_ref: str,
    account_ref: str,
    strategy_ref: str,
) -> bool:
    return (
        scope.execution_domain_ref == execution_domain_ref
        and scope.account_ref == account_ref
        and not scope.account_refs
        and scope.strategy_ref == strategy_ref
        and scope.run_id is None
        and scope.manual_book_ref is None
        and scope.portfolio_ref is None
        and scope.group_id is None
        and scope.leg_id is None
    )


def _validate_account_and_book_bindings(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    scopes: Mapping[str, Any],
    account_bindings: Mapping[str, AccountBinding],
    account_book_bindings: Mapping[str, AccountBookBinding],
) -> None:
    for account_ref, account_binding in account_bindings.items():
        scope = scopes.get(account_binding.scope_ref)
        if (
            account_binding.mount != "application.account"
            or scope is None
            or scope.account_ref != account_ref
            or scope.account_refs
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(declared, account_binding.mount, account_binding.scope_ref, account_ref)

    for account_ref, book_binding in account_book_bindings.items():
        scope = scopes.get(book_binding.scope_ref)
        if (
            book_binding.mount != "application.order_query"
            or scope is None
            or scope.account_ref != account_ref
            or not is_account_scope(scope)
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        snapshot_binding = account_bindings.get(account_ref)
        if (
            snapshot_binding is not None
            and snapshot_binding.account_key.account_key_id
            != book_binding.account_key.account_key_id
        ):
            raise ServiceReadDeploymentError("ACCOUNT_BOOK_KEY_MISMATCH")
        add_declared(declared, book_binding.mount, book_binding.scope_ref, account_ref)


def _validate_order_and_target_bindings(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    scopes: Mapping[str, Any],
    order_bindings: Mapping[str, OrderBinding],
    order_submit_bindings: Mapping[str, OrderSubmitBinding],
    approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding],
) -> None:
    for order_scope_ref, order_binding in order_bindings.items():
        if order_binding.mount != "application.order_query" or order_scope_ref not in scopes:
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        scope = scopes[order_scope_ref]
        add_declared(declared, order_binding.mount, order_scope_ref, scope.account_ref)

    for submit_scope_ref, submit_binding in order_submit_bindings.items():
        scope = scopes.get(submit_scope_ref)
        if (
            submit_binding.mount != "application.orders"
            or scope is None
            or not is_manual_order_scope(
                scope, submit_binding.account_ref, submit_binding.manual_book_ref
            )
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(declared, submit_binding.mount, submit_scope_ref, submit_binding.account_ref)

    for approved_scope_ref, approved_binding in approved_target_bindings.items():
        scope = scopes.get(approved_scope_ref)
        if (
            approved_binding.mount != "application.orders"
            or scope is None
            or not is_approved_target_scope(
                scope, approved_binding.account_ref, approved_binding.strategy_ref
            )
            or scope != approved_binding.wire_scope
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(
            declared, approved_binding.mount, approved_scope_ref, approved_binding.account_ref
        )


def _validate_paper_bindings(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    scopes: Mapping[str, Any],
    subject: str,
    paper_submit_bindings: Mapping[str, PaperSubmitBinding],
    paper_legacy_import_bindings: Mapping[str, PaperLegacyImportBinding],
) -> None:
    for legacy_account_id, paper_binding in paper_submit_bindings.items():
        scope = scopes.get(paper_binding.scope_ref)
        query = scopes.get(paper_binding.query_scope_ref)
        if (
            legacy_account_id != paper_binding.legacy_account_id
            or paper_binding.mount != "application.orders"
            or scope is None
            or query is None
            or scope != paper_binding.wire_scope
            or not _is_exact_paper_wire_scope(
                scope,
                execution_domain_ref=paper_binding.execution_domain_ref,
                account_ref=paper_binding.account_ref,
                strategy_ref=paper_binding.strategy_ref,
            )
            or not _is_exact_paper_wire_scope(
                query,
                execution_domain_ref=paper_binding.execution_domain_ref,
                account_ref=paper_binding.account_ref,
                strategy_ref=paper_binding.strategy_ref,
            )
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(
            declared, paper_binding.mount, paper_binding.scope_ref, paper_binding.account_ref
        )

    for legacy_account_id, legacy_import_binding in paper_legacy_import_bindings.items():
        paper = paper_submit_bindings.get(legacy_account_id)
        scope = scopes.get(legacy_import_binding.scope_ref)
        if (
            legacy_import_binding.mount != "application.paper_legacy_import"
            or legacy_import_binding.legacy_account_id != legacy_account_id
            or legacy_import_binding.owner_subject != subject
            or paper is None
            or legacy_import_binding.paper_binding is not paper
            or legacy_import_binding.scope_ref != paper.scope_ref
            or scope is None
            or scope != paper.wire_scope
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        paper.paper_owner_domain.validate_binding(paper.wire_scope, paper.execution_scope)
        add_declared(
            declared,
            legacy_import_binding.mount,
            legacy_import_binding.scope_ref,
            paper.account_ref,
        )


def _validate_monitor_and_analytics_bindings(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    scopes: Mapping[str, Any],
    monitor_bindings: Mapping[str, MonitorBinding],
    portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding],
) -> None:
    for monitor_scope_ref, monitor_binding in monitor_bindings.items():
        scope = scopes.get(monitor_binding.scope_ref)
        if (
            monitor_binding.mount != "application.monitor"
            or scope is None
            or scope.strategy_ref != monitor_binding.strategy_ref
            or scope.account_refs
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(declared, monitor_binding.mount, monitor_scope_ref, None)

    for analytics_portfolio_ref, analytics_binding in portfolio_analytics_bindings.items():
        scope = scopes.get(analytics_binding.scope_ref)
        if analytics_binding.mount != "application.risk_analysis" or (
            not is_portfolio_analytics_scope(scope, analytics_portfolio_ref)
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(
            declared,
            analytics_binding.mount,
            analytics_binding.scope_ref,
            analytics_portfolio_ref,
        )


def _validate_risk_bindings(
    declared: dict[tuple[str, str], tuple[str, str | None]],
    scopes: Mapping[str, Any],
    risk_policy_budget_bindings: Mapping[str, RiskPolicyBudgetBinding],
    risk_account_policy_bindings: Mapping[str, RiskAccountPolicyBinding],
) -> dict[tuple[str, str], str]:
    budget_management_portfolios: dict[tuple[str, str], str] = {}
    for budget_portfolio_ref, budget_binding in risk_policy_budget_bindings.items():
        management_scope = scopes.get(budget_binding.management_scope_ref)
        member_refs = frozenset(budget_binding.member_scope_refs)
        if (
            budget_binding.mount != "application.risk_policy"
            or budget_binding.portfolio_ref != budget_portfolio_ref
            or not is_budget_management_scope(management_scope, budget_portfolio_ref, member_refs)
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        management_pair = (budget_binding.mount, budget_binding.management_scope_ref)
        add_declared(declared, budget_binding.mount, budget_binding.management_scope_ref, None)
        previous_portfolio = budget_management_portfolios.get(management_pair)
        if previous_portfolio is not None and previous_portfolio != budget_portfolio_ref:
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        budget_management_portfolios[management_pair] = budget_portfolio_ref
        domain_ref = require_present(management_scope).execution_domain_ref
        for account_ref, member_scope_ref in budget_binding.member_scope_refs.items():
            member_scope = scopes.get(member_scope_ref)
            if not is_budget_member_scope(
                member_scope, budget_portfolio_ref, account_ref, domain_ref
            ):
                raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
            add_declared(declared, budget_binding.mount, member_scope_ref, account_ref)

    budget_scope_refs = {
        binding.management_scope_ref for binding in risk_policy_budget_bindings.values()
    } | {
        scope_ref
        for binding in risk_policy_budget_bindings.values()
        for scope_ref in binding.member_scope_refs.values()
    }
    for account_ref, binding in risk_account_policy_bindings.items():
        scope = scopes.get(binding.scope_ref)
        if (
            binding.mount != "application.risk_policy"
            or binding.account_ref != account_ref
            or not is_risk_account_policy_scope(scope, account_ref)
            or binding.scope_ref in budget_scope_refs
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
        add_declared(declared, binding.mount, binding.scope_ref, account_ref)
    return budget_management_portfolios


def _validate_client_binding_target(
    binding: Mapping[str, Any],
    mount: Any,
    pair: tuple[str, str],
    declared_account_ref: str | None,
    budget_management_portfolios: Mapping[tuple[str, str], str],
) -> None:
    if mount == "application.risk_analysis":
        if (
            binding.get("portfolio_ref") != declared_account_ref
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
            binding.get("account_ref") != declared_account_ref
            or binding.get("portfolio_ref") is not None
        ):
            raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")
    elif binding.get("account_ref") != declared_account_ref:
        raise ServiceReadDeploymentError("SCOPE_BINDING_MISMATCH")


def _validate_client_runtime_bindings(
    client_config: Mapping[str, Any],
    declared: Mapping[tuple[str, str], tuple[str, str | None]],
    budget_management_portfolios: Mapping[tuple[str, str], str],
    peers: Mapping[str, Any],
) -> set[str]:
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
            if mount not in DEPLOYMENT_MOUNTS or type(scope_ref) is not str:
                raise ServiceReadDeploymentError("WRITABLE_BINDING_FORBIDDEN")
            pair = (mount, scope_ref)
            if pair in observed or pair not in declared:
                raise ServiceReadDeploymentError("GRANT_BINDING_MISMATCH")
            _validate_client_binding_target(
                binding, mount, pair, declared[pair][1], budget_management_portfolios
            )
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
    return used_transports


def _validate_client_communication(
    client_config: Mapping[str, Any],
    used_transports: set[str],
    curve_keys: Mapping[str, Any],
    identity: Any,
) -> None:
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


def validate_profile_bindings(
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
    risk_account_policy_bindings: Mapping[str, RiskAccountPolicyBinding],
) -> None:
    """Validate that declared scopes, domain bindings, client bindings, and keys match 1:1."""
    declared: dict[tuple[str, str], tuple[str, str | None]] = {}
    _validate_account_and_book_bindings(declared, scopes, account_bindings, account_book_bindings)
    _validate_order_and_target_bindings(
        declared, scopes, order_bindings, order_submit_bindings, approved_target_bindings
    )
    _validate_paper_bindings(
        declared, scopes, subject, paper_submit_bindings, paper_legacy_import_bindings
    )
    _validate_monitor_and_analytics_bindings(
        declared, scopes, monitor_bindings, portfolio_analytics_bindings
    )
    budget_management_portfolios = _validate_risk_bindings(
        declared, scopes, risk_policy_budget_bindings, risk_account_policy_bindings
    )
    if set(scopes) != {scope_ref for _, scope_ref in declared}:
        raise ServiceReadDeploymentError("UNUSED_SCOPE")
    used_transports = _validate_client_runtime_bindings(
        client_config, declared, budget_management_portfolios, peers
    )
    _validate_client_communication(client_config, used_transports, curve_keys, identity)
