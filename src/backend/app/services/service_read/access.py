"""Trusted user-to-worker selectors for HTTP service-read access.

The directory is deployment configuration, not an identity provider. A
composition root builds each worker from an exact ``WireIdentity`` already
granted by the service host, then binds the verified JWT subject to that
worker and its exact resource selectors here. This module never derives an
actor, principal, delegate, or service identity from a user-supplied value and
never starts or closes a worker.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from app.services.service_read.client import (
    ApprovedTargetSubmitBinding,
    OrderSubmitBinding,
    PaperLegacyImportBinding,
    PaperSubmitBinding,
    PortfolioAnalyticsBinding,
    RiskAccountPolicyBinding,
    RiskPolicyBudgetBinding,
)

__all__ = [
    "ReadAccess",
    "StrategyBookBinding",
    "PortfolioAnalyticsBinding",
    "RiskAccountPolicyBinding",
    "RiskPolicyBudgetBinding",
    "PaperLegacyImportBinding",
    "ServiceReadAccessDirectory",
    "ServiceReadAccessError",
]


class ServiceReadAccessError(RuntimeError):
    """A finite configuration or authorization failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class StrategyBookBinding:
    """Server-owned mapping from a composition selector to one account owner."""

    account_ref: str
    owner_ref: str

    def __post_init__(self) -> None:
        if not _valid_identifier(self.account_ref) or not _valid_identifier(self.owner_ref):
            raise ServiceReadAccessError("INVALID_STRATEGY_BOOK_BINDING")


@dataclass(frozen=True, slots=True)
class ReadAccess:
    """One preassembled async worker and its exact permitted selectors.

    Selectors are copied to immutable sets during construction. The worker
    must be distinct for each subject; its session factory is responsible for
    binding the exact server-granted service identity.
    """

    worker: Any
    allow_account_refs: frozenset[str] = frozenset()
    allow_account_book_refs: frozenset[str] = frozenset()
    allow_order_scope_refs: frozenset[str] = frozenset()
    allow_order_submit_scope_refs: frozenset[str] = frozenset()
    allow_paper_submit_account_ids: frozenset[str] = frozenset()
    allow_paper_legacy_import_account_ids: frozenset[str] = frozenset()
    allow_approved_target_scope_refs: frozenset[str] = frozenset()
    allow_monitor_scope_refs: frozenset[str] = frozenset()
    allow_portfolio_refs: frozenset[str] = frozenset()
    allow_risk_policy_budget_refs: frozenset[str] = frozenset()
    allow_risk_account_policy_refs: frozenset[str] = frozenset()
    portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding] = field(
        default_factory=dict, repr=False
    )
    risk_policy_budget_bindings: Mapping[str, RiskPolicyBudgetBinding] = field(
        default_factory=dict, repr=False
    )
    risk_account_policy_bindings: Mapping[str, RiskAccountPolicyBinding] = field(
        default_factory=dict, repr=False
    )
    strategy_book_bindings: Mapping[str, StrategyBookBinding] = field(
        default_factory=dict, repr=False
    )
    order_submit_bindings: Mapping[str, OrderSubmitBinding] = field(
        default_factory=dict, repr=False
    )
    approved_target_bindings: Mapping[str, ApprovedTargetSubmitBinding] = field(
        default_factory=dict, repr=False
    )
    paper_submit_bindings: Mapping[str, PaperSubmitBinding] = field(
        default_factory=dict, repr=False
    )
    paper_legacy_import_bindings: Mapping[str, PaperLegacyImportBinding] = field(
        default_factory=dict, repr=False
    )
    application_identity: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_async_methods(self.worker, "read_account", "read_order", "read_strategy_health")
        for name in (
            "allow_account_refs",
            "allow_account_book_refs",
            "allow_order_scope_refs",
            "allow_order_submit_scope_refs",
            "allow_paper_submit_account_ids",
            "allow_paper_legacy_import_account_ids",
            "allow_approved_target_scope_refs",
            "allow_monitor_scope_refs",
            "allow_portfolio_refs",
            "allow_risk_policy_budget_refs",
            "allow_risk_account_policy_refs",
        ):
            object.__setattr__(self, name, _immutable_selectors(getattr(self, name)))
        if self.allow_account_book_refs:
            _require_async_methods(self.worker, "read_account_book")

        strategy_bindings = _normalize_strategy_book_bindings(
            self.strategy_book_bindings, self.allow_account_book_refs, self.worker
        )
        object.__setattr__(self, "strategy_book_bindings", strategy_bindings)

        submit_bindings = _normalize_keyed_bindings(
            self.order_submit_bindings,
            type_cls=OrderSubmitBinding,
            key_attr="scope_ref",
            invalid_code="INVALID_ORDER_SUBMIT_BINDINGS",
            allow_refs=self.allow_order_submit_scope_refs,
            mismatch_code="ORDER_SUBMIT_BINDING_MISMATCH",
            worker=self.worker,
            required_methods=("submit_manual_order",),
            identity=self.application_identity,
        )
        object.__setattr__(self, "order_submit_bindings", submit_bindings)

        paper_bindings = _normalize_paper_submit_bindings(
            self.paper_submit_bindings,
            allow_ids=self.allow_paper_submit_account_ids,
            order_submit_scopes=self.allow_order_submit_scope_refs,
            order_query_scopes=self.allow_order_scope_refs,
            worker=self.worker,
            identity=self.application_identity,
        )
        object.__setattr__(self, "paper_submit_bindings", paper_bindings)

        import_bindings = _normalize_paper_legacy_import_bindings(
            self.paper_legacy_import_bindings,
            paper_bindings=paper_bindings,
            allow_ids=self.allow_paper_legacy_import_account_ids,
            order_query_scopes=self.allow_order_scope_refs,
            worker=self.worker,
            identity=self.application_identity,
        )
        object.__setattr__(self, "paper_legacy_import_bindings", import_bindings)

        approved_bindings = _normalize_keyed_bindings(
            self.approved_target_bindings,
            type_cls=ApprovedTargetSubmitBinding,
            key_attr="scope_ref",
            invalid_code="INVALID_APPROVED_TARGET_BINDINGS",
            allow_refs=self.allow_approved_target_scope_refs,
            mismatch_code="APPROVED_TARGET_BINDING_MISMATCH",
            disjoint_refs=self.allow_order_submit_scope_refs,
            worker=self.worker,
            required_methods=("submit_approved_target",),
            identity=self.application_identity,
        )
        object.__setattr__(self, "approved_target_bindings", approved_bindings)

        analytics_bindings = _normalize_keyed_bindings(
            self.portfolio_analytics_bindings,
            type_cls=PortfolioAnalyticsBinding,
            key_attr="portfolio_ref",
            invalid_code="INVALID_PORTFOLIO_ANALYTICS_BINDINGS",
            allow_refs=self.allow_portfolio_refs,
            mismatch_code="PORTFOLIO_ANALYTICS_BINDING_MISMATCH",
            worker=self.worker,
            required_methods=(
                "upload_portfolio_analytics_input",
                "submit_portfolio_analytics_task",
                "query_portfolio_analytics_task",
                "cancel_portfolio_analytics_task",
            ),
            identity=self.application_identity,
        )
        object.__setattr__(self, "portfolio_analytics_bindings", analytics_bindings)

        budget_bindings = _normalize_keyed_bindings(
            self.risk_policy_budget_bindings,
            type_cls=RiskPolicyBudgetBinding,
            key_attr="portfolio_ref",
            invalid_code="INVALID_RISK_POLICY_BUDGET_BINDINGS",
            allow_refs=self.allow_risk_policy_budget_refs,
            mismatch_code="RISK_POLICY_BUDGET_BINDING_MISMATCH",
            worker=self.worker,
            required_methods=("call_risk_policy_budget",),
            identity=self.application_identity,
        )
        object.__setattr__(self, "risk_policy_budget_bindings", budget_bindings)

        account_policy_bindings = _normalize_keyed_bindings(
            self.risk_account_policy_bindings,
            type_cls=RiskAccountPolicyBinding,
            key_attr="account_ref",
            invalid_code="INVALID_RISK_ACCOUNT_POLICY_BINDINGS",
            allow_refs=self.allow_risk_account_policy_refs,
            mismatch_code="RISK_ACCOUNT_POLICY_BINDING_MISMATCH",
            worker=self.worker,
            required_methods=("call_risk_account_policy",),
            identity=self.application_identity,
        )
        object.__setattr__(self, "risk_account_policy_bindings", account_policy_bindings)


@dataclass(frozen=True, slots=True, init=False)
class ServiceReadAccessDirectory:
    """An immutable exact-subject directory for independently owned workers.

    Unknown subjects and disallowed selectors intentionally produce the same
    error so callers cannot probe another subject's configured resources.
    """

    _access_by_subject: Mapping[str, ReadAccess] = field(repr=False, compare=False)

    def __init__(self, subject_access: Mapping[str, ReadAccess]) -> None:
        if not isinstance(subject_access, Mapping) or len(subject_access) > 4096:
            raise ServiceReadAccessError("INVALID_ACCESS_DIRECTORY")

        frozen: dict[str, ReadAccess] = {}
        worker_ids: set[int] = set()
        for subject, access in subject_access.items():
            if not _valid_identifier(subject):
                raise ServiceReadAccessError("INVALID_SUBJECT")
            if type(access) is not ReadAccess:
                raise ServiceReadAccessError("INVALID_READ_ACCESS")
            if any(
                binding.owner_subject != subject
                for binding in access.paper_legacy_import_bindings.values()
            ):
                raise ServiceReadAccessError("PAPER_LEGACY_IMPORT_OWNER_MISMATCH")
            worker_id = id(access.worker)
            if worker_id in worker_ids:
                raise ServiceReadAccessError("WORKER_SHARED")
            worker_ids.add(worker_id)
            frozen[subject] = access

        object.__setattr__(
            self,
            "_access_by_subject",
            MappingProxyType(dict(sorted(frozen.items()))),
        )

    def resolve_account(self, subject: str, account_ref: str) -> ReadAccess:
        """Resolve one account selector for an exact authenticated subject."""

        return self._resolve(subject, account_ref, "allow_account_refs")

    def account_refs_for(self, subject: str) -> tuple[str, ...]:
        """List only the account selectors granted to one exact subject."""

        if not _valid_identifier(subject):
            return ()
        access = self._access_by_subject.get(subject)
        return () if access is None else tuple(sorted(access.allow_account_refs))

    def resolve_account_book(self, subject: str, account_ref: str) -> ReadAccess:
        """Resolve an exact server-configured account-book selector."""

        return self._resolve(subject, account_ref, "allow_account_book_refs")

    def resolve_account_member(self, subject: str, account_ref: str) -> ReadAccess:
        """Resolve a composition account member covered by either read grant."""

        if not _valid_identifier(subject) or not _valid_identifier(account_ref):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or not (
            account_ref in access.allow_account_refs
            or account_ref in access.allow_account_book_refs
        ):
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_strategy_book(self, subject: str, strategy_ref: str) -> ReadAccess:
        """Resolve a composition selector to its deployment-owned book target."""

        if not _valid_identifier(subject) or not _valid_identifier(strategy_ref):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or strategy_ref not in access.strategy_book_bindings:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_order_scope(self, subject: str, scope_ref: str) -> ReadAccess:
        """Resolve one order-query scope for an exact authenticated subject."""

        return self._resolve(subject, scope_ref, "allow_order_scope_refs")

    def resolve_order_submit_scope(self, subject: str, scope_ref: str) -> ReadAccess:
        """Resolve one deployment-owned manual submit scope for an exact subject."""

        return self._resolve(subject, scope_ref, "allow_order_submit_scope_refs")

    def resolve_paper_submit_account(self, subject: str, legacy_account_id: str) -> ReadAccess:
        """Resolve a legacy account selector to one configured paper owner."""

        if not _valid_identifier(subject) or not _valid_identifier(legacy_account_id):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or legacy_account_id not in access.paper_submit_bindings:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_paper_legacy_import_account(
        self, subject: str, legacy_account_id: str
    ) -> ReadAccess:
        """Resolve the separately granted import operation for an exact owner."""

        if not _valid_identifier(subject) or not _valid_identifier(legacy_account_id):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        binding = (
            None if access is None else access.paper_legacy_import_bindings.get(legacy_account_id)
        )
        if access is None or binding is None or binding.owner_subject != subject:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_approved_target_scope(self, subject: str, scope_ref: str) -> ReadAccess:
        """Resolve one explicitly configured approved-target selector."""

        if not _valid_identifier(subject) or not _valid_identifier(scope_ref):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or scope_ref not in access.approved_target_bindings:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_monitor_scope(self, subject: str, scope_ref: str) -> ReadAccess:
        """Resolve one telemetry scope for an exact authenticated subject."""

        return self._resolve(subject, scope_ref, "allow_monitor_scope_refs")

    def resolve_portfolio_analytics(self, subject: str, portfolio_ref: str) -> ReadAccess:
        """Resolve one configured analytics portfolio for an exact JWT subject."""

        if not _valid_identifier(subject) or not _valid_identifier(portfolio_ref):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or portfolio_ref not in access.portfolio_analytics_bindings:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_risk_policy_budget(self, subject: str, portfolio_ref: str) -> ReadAccess:
        """Resolve one trusted budget-control portfolio for an exact subject."""

        if not _valid_identifier(subject) or not _valid_identifier(portfolio_ref):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or portfolio_ref not in access.risk_policy_budget_bindings:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def resolve_risk_account_policy(self, subject: str, account_ref: str) -> ReadAccess:
        """Resolve one exact ordinary policy account grant for a JWT subject."""

        if not _valid_identifier(subject) or not _valid_identifier(account_ref):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or account_ref not in access.risk_account_policy_bindings:
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access

    def _resolve(self, subject: str, selector: str, grant_field: str) -> ReadAccess:
        if not _valid_identifier(subject) or not _valid_identifier(selector):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or selector not in getattr(access, grant_field):
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access


def _require_async_methods(worker: Any, *method_names: str) -> None:
    if any(not inspect.iscoroutinefunction(getattr(worker, name, None)) for name in method_names):
        raise ServiceReadAccessError("INVALID_WORKER")


def _require_application_identity(identity: Any, *, check_delegate: bool = True) -> None:
    role_value = getattr(getattr(identity, "role", None), "value", None)
    invalid_delegate = (
        check_delegate
        and getattr(identity, "delegate_ref", None) is not None
        and not _valid_identifier(identity.delegate_ref)
    )
    if (
        role_value != "application_client"
        or not _valid_identifier(getattr(identity, "principal_ref", None))
        or not _valid_identifier(getattr(identity, "actor_ref", None))
        or invalid_delegate
    ):
        raise ServiceReadAccessError("INVALID_APPLICATION_IDENTITY")


def _normalize_strategy_book_bindings(
    bindings: Any, allow_account_book_refs: frozenset[str], worker: Any
) -> Mapping[str, StrategyBookBinding]:
    if not isinstance(bindings, Mapping) or len(bindings) > 4096:
        raise ServiceReadAccessError("INVALID_STRATEGY_BOOK_BINDINGS")
    normalized: dict[str, StrategyBookBinding] = {}
    for selector, strategy_binding in bindings.items():
        if not _valid_identifier(selector) or type(strategy_binding) is not StrategyBookBinding:
            raise ServiceReadAccessError("INVALID_STRATEGY_BOOK_BINDINGS")
        normalized[selector] = strategy_binding
    if normalized:
        _require_async_methods(worker, "read_account_book")
    target_keys = [(item.account_ref, item.owner_ref) for item in normalized.values()]
    if len(target_keys) != len(set(target_keys)):
        raise ServiceReadAccessError("DUPLICATE_STRATEGY_BOOK_OWNER")
    if any(item.account_ref not in allow_account_book_refs for item in normalized.values()):
        raise ServiceReadAccessError("STRATEGY_BOOK_ACCOUNT_NOT_GRANTED")
    return MappingProxyType(normalized)


def _normalize_keyed_bindings(
    bindings: Any,
    *,
    type_cls: type[Any],
    key_attr: str,
    invalid_code: str,
    allow_refs: frozenset[str],
    mismatch_code: str,
    worker: Any,
    required_methods: tuple[str, ...],
    identity: Any,
    disjoint_refs: frozenset[str] = frozenset(),
) -> Mapping[str, Any]:
    if not isinstance(bindings, Mapping) or len(bindings) > 4096:
        raise ServiceReadAccessError(invalid_code)
    normalized: dict[str, Any] = {}
    for selector, item in bindings.items():
        if (
            not _valid_identifier(selector)
            or type(item) is not type_cls
            or getattr(item, key_attr) != selector
        ):
            raise ServiceReadAccessError(invalid_code)
        normalized[selector] = item
    if set(normalized) != set(allow_refs):
        raise ServiceReadAccessError(mismatch_code)
    if normalized:
        if disjoint_refs and (set(normalized) & set(disjoint_refs)):
            raise ServiceReadAccessError("GRANT_BINDING_MISMATCH")
        _require_async_methods(worker, *required_methods)
        _require_application_identity(identity)
    return MappingProxyType(normalized)


def _normalize_paper_submit_bindings(
    bindings: Any,
    *,
    allow_ids: frozenset[str],
    order_submit_scopes: frozenset[str],
    order_query_scopes: frozenset[str],
    worker: Any,
    identity: Any,
) -> Mapping[str, PaperSubmitBinding]:
    if not isinstance(bindings, Mapping) or len(bindings) > 4096:
        raise ServiceReadAccessError("INVALID_PAPER_SUBMIT_BINDINGS")
    normalized: dict[str, PaperSubmitBinding] = {}
    for selector, binding in bindings.items():
        if (
            not _valid_identifier(selector)
            or type(binding) is not PaperSubmitBinding
            or binding.legacy_account_id != selector
            or binding.scope_ref in order_submit_scopes
        ):
            raise ServiceReadAccessError("INVALID_PAPER_SUBMIT_BINDINGS")
        normalized[selector] = binding
    if set(normalized) != set(allow_ids):
        raise ServiceReadAccessError("PAPER_SUBMIT_BINDING_MISMATCH")
    if normalized:
        _require_async_methods(worker, "submit_paper_order", "read_order")
        if any(b.query_scope_ref not in order_query_scopes for b in normalized.values()):
            raise ServiceReadAccessError("PAPER_QUERY_SCOPE_NOT_GRANTED")
        if len({b.scope_ref for b in normalized.values()}) != len(normalized) or len(
            {b.account_ref for b in normalized.values()}
        ) != len(normalized):
            raise ServiceReadAccessError("DUPLICATE_PAPER_OWNER_DOMAIN")
        _require_application_identity(identity)
    return MappingProxyType(normalized)


def _normalize_paper_legacy_import_bindings(
    bindings: Any,
    *,
    paper_bindings: Mapping[str, PaperSubmitBinding],
    allow_ids: frozenset[str],
    order_query_scopes: frozenset[str],
    worker: Any,
    identity: Any,
) -> Mapping[str, PaperLegacyImportBinding]:
    if not isinstance(bindings, Mapping) or len(bindings) > 4096:
        raise ServiceReadAccessError("INVALID_PAPER_LEGACY_IMPORT_BINDINGS")
    normalized: dict[str, PaperLegacyImportBinding] = {}
    for selector, binding in bindings.items():
        paper_binding = paper_bindings.get(selector)
        if (
            not _valid_identifier(selector)
            or type(binding) is not PaperLegacyImportBinding
            or binding.legacy_account_id != selector
            or paper_binding is None
            or binding.paper_binding is not paper_binding
        ):
            raise ServiceReadAccessError("PAPER_LEGACY_IMPORT_BINDING_MISMATCH")
        normalized[selector] = binding
    if set(normalized) != set(allow_ids):
        raise ServiceReadAccessError("PAPER_LEGACY_IMPORT_GRANT_MISMATCH")
    if normalized:
        _require_async_methods(worker, "call_paper_legacy_import")
        if any(
            b.paper_binding.query_scope_ref not in order_query_scopes for b in normalized.values()
        ):
            raise ServiceReadAccessError("PAPER_QUERY_SCOPE_NOT_GRANTED")
        _require_application_identity(identity, check_delegate=False)
    return MappingProxyType(normalized)


def _immutable_selectors(value: object) -> frozenset[str]:
    if not isinstance(value, (frozenset, set, tuple, list)):
        raise ServiceReadAccessError("INVALID_SELECTORS")
    # Reject subclasses and oversized inputs; keep the exact-type contract.
    if type(value) not in {frozenset, set, tuple, list} or len(value) > 4096:
        raise ServiceReadAccessError("INVALID_SELECTORS")
    selectors = frozenset(value)
    if any(not _valid_identifier(selector) for selector in selectors):
        raise ServiceReadAccessError("INVALID_SELECTORS")
    return selectors


def _valid_identifier(value: object) -> bool:
    return (
        type(value) is str
        and bool(value)
        and value == value.strip()
        and value != "*"
        and len(value) <= 256
        and value.isprintable()
    )
