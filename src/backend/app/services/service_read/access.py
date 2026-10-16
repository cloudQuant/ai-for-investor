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
    PortfolioAnalyticsBinding,

    PaperSubmitBinding,
)

__all__ = [
    "ReadAccess",
    "StrategyBookBinding",
    "PortfolioAnalyticsBinding",
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
    allow_approved_target_scope_refs: frozenset[str] = frozenset()
    allow_monitor_scope_refs: frozenset[str] = frozenset()
    allow_portfolio_refs: frozenset[str] = frozenset()
    portfolio_analytics_bindings: Mapping[str, PortfolioAnalyticsBinding] = field(
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
    application_identity: Any = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        required_methods = ("read_account", "read_order", "read_strategy_health")
        if any(
            not inspect.iscoroutinefunction(getattr(self.worker, name, None))
            for name in required_methods
        ):
            raise ServiceReadAccessError("INVALID_WORKER")
        for name in (
            "allow_account_refs",
            "allow_account_book_refs",
            "allow_order_scope_refs",
            "allow_order_submit_scope_refs",
            "allow_paper_submit_account_ids",
            "allow_approved_target_scope_refs",
            "allow_monitor_scope_refs",
            "allow_portfolio_refs",
        ):
            object.__setattr__(self, name, _immutable_selectors(getattr(self, name)))
        if self.allow_account_book_refs and not inspect.iscoroutinefunction(
            getattr(self.worker, "read_account_book", None)
        ):
            raise ServiceReadAccessError("INVALID_WORKER")
        bindings = self.strategy_book_bindings
        if not isinstance(bindings, Mapping) or len(bindings) > 4096:
            raise ServiceReadAccessError("INVALID_STRATEGY_BOOK_BINDINGS")
        normalized: dict[str, StrategyBookBinding] = {}
        for selector, binding in bindings.items():
            if not _valid_identifier(selector) or type(binding) is not StrategyBookBinding:
                raise ServiceReadAccessError("INVALID_STRATEGY_BOOK_BINDINGS")
            normalized[selector] = binding
        if normalized and not inspect.iscoroutinefunction(
            getattr(self.worker, "read_account_book", None)
        ):
            raise ServiceReadAccessError("INVALID_WORKER")
        target_keys = [(item.account_ref, item.owner_ref) for item in normalized.values()]
        if len(target_keys) != len(set(target_keys)):
            raise ServiceReadAccessError("DUPLICATE_STRATEGY_BOOK_OWNER")
        if any(
            item.account_ref not in self.allow_account_book_refs for item in normalized.values()
        ):
            raise ServiceReadAccessError("STRATEGY_BOOK_ACCOUNT_NOT_GRANTED")
        object.__setattr__(self, "strategy_book_bindings", MappingProxyType(normalized))
        submit_bindings = self.order_submit_bindings
        if not isinstance(submit_bindings, Mapping) or len(submit_bindings) > 4096:
            raise ServiceReadAccessError("INVALID_ORDER_SUBMIT_BINDINGS")
        normalized_submit: dict[str, OrderSubmitBinding] = {}
        for selector, binding in submit_bindings.items():
            if (
                not _valid_identifier(selector)
                or type(binding) is not OrderSubmitBinding
                or binding.scope_ref != selector
            ):
                raise ServiceReadAccessError("INVALID_ORDER_SUBMIT_BINDINGS")
            normalized_submit[selector] = binding
        if set(normalized_submit) != set(self.allow_order_submit_scope_refs):
            raise ServiceReadAccessError("ORDER_SUBMIT_BINDING_MISMATCH")
        if normalized_submit:
            if not inspect.iscoroutinefunction(
                getattr(self.worker, "submit_manual_order", None)
            ):
                raise ServiceReadAccessError("INVALID_WORKER")
            identity = self.application_identity
            role_value = getattr(getattr(identity, "role", None), "value", None)
            if (
                role_value != "application_client"
                or not _valid_identifier(getattr(identity, "principal_ref", None))
                or not _valid_identifier(getattr(identity, "actor_ref", None))
                or (
                    getattr(identity, "delegate_ref", None) is not None
                    and not _valid_identifier(identity.delegate_ref)
                )
            ):
                raise ServiceReadAccessError("INVALID_APPLICATION_IDENTITY")
        object.__setattr__(self, "order_submit_bindings", MappingProxyType(normalized_submit))

        paper_bindings = self.paper_submit_bindings
        if not isinstance(paper_bindings, Mapping) or len(paper_bindings) > 4096:
            raise ServiceReadAccessError("INVALID_PAPER_SUBMIT_BINDINGS")
        normalized_paper: dict[str, PaperSubmitBinding] = {}
        for selector, binding in paper_bindings.items():
            if (
                not _valid_identifier(selector)
                or type(binding) is not PaperSubmitBinding
                or binding.legacy_account_id != selector
                or binding.scope_ref in self.allow_order_submit_scope_refs
            ):
                raise ServiceReadAccessError("INVALID_PAPER_SUBMIT_BINDINGS")
            normalized_paper[selector] = binding
        if set(normalized_paper) != set(self.allow_paper_submit_account_ids):
            raise ServiceReadAccessError("PAPER_SUBMIT_BINDING_MISMATCH")
        if normalized_paper:
            if not inspect.iscoroutinefunction(getattr(self.worker, "submit_paper_order", None)):
                raise ServiceReadAccessError("INVALID_WORKER")
            if not inspect.iscoroutinefunction(getattr(self.worker, "read_order", None)):
                raise ServiceReadAccessError("INVALID_WORKER")
            if any(
                binding.query_scope_ref not in self.allow_order_scope_refs
                for binding in normalized_paper.values()
            ):
                raise ServiceReadAccessError("PAPER_QUERY_SCOPE_NOT_GRANTED")
            if (
                len({binding.scope_ref for binding in normalized_paper.values()})
                != len(normalized_paper)
                or len({binding.account_ref for binding in normalized_paper.values()})
                != len(normalized_paper)
            ):
                raise ServiceReadAccessError("DUPLICATE_PAPER_OWNER_DOMAIN")
            identity = self.application_identity
            role_value = getattr(getattr(identity, "role", None), "value", None)
            if (
                role_value != "application_client"
                or not _valid_identifier(getattr(identity, "principal_ref", None))
                or not _valid_identifier(getattr(identity, "actor_ref", None))
                or (
                    getattr(identity, "delegate_ref", None) is not None
                    and not _valid_identifier(identity.delegate_ref)
                )
            ):
                raise ServiceReadAccessError("INVALID_APPLICATION_IDENTITY")
        object.__setattr__(self, "paper_submit_bindings", MappingProxyType(normalized_paper))

        approved_bindings = self.approved_target_bindings
        if not isinstance(approved_bindings, Mapping) or len(approved_bindings) > 4096:
            raise ServiceReadAccessError("INVALID_APPROVED_TARGET_BINDINGS")
        normalized_approved: dict[str, ApprovedTargetSubmitBinding] = {}
        for selector, binding in approved_bindings.items():
            if (
                not _valid_identifier(selector)
                or type(binding) is not ApprovedTargetSubmitBinding
                or binding.scope_ref != selector
            ):
                raise ServiceReadAccessError("INVALID_APPROVED_TARGET_BINDINGS")
            normalized_approved[selector] = binding
        if normalized_approved:
            if set(normalized_approved) != set(self.allow_approved_target_scope_refs):
                raise ServiceReadAccessError("APPROVED_TARGET_BINDING_MISMATCH")
            if set(normalized_approved) & set(self.allow_order_submit_scope_refs):
                raise ServiceReadAccessError("GRANT_BINDING_MISMATCH")
            if not inspect.iscoroutinefunction(
                getattr(self.worker, "submit_approved_target", None)
            ):
                raise ServiceReadAccessError("INVALID_WORKER")
            identity = self.application_identity
            role_value = getattr(getattr(identity, "role", None), "value", None)
            if (
                role_value != "application_client"
                or not _valid_identifier(getattr(identity, "principal_ref", None))
                or not _valid_identifier(getattr(identity, "actor_ref", None))
                or (
                    getattr(identity, "delegate_ref", None) is not None
                    and not _valid_identifier(identity.delegate_ref)
                )
            ):
                raise ServiceReadAccessError("INVALID_APPLICATION_IDENTITY")
        object.__setattr__(
            self, "approved_target_bindings", MappingProxyType(normalized_approved)
        )
        if set(normalized_approved) != set(self.allow_approved_target_scope_refs):
            raise ServiceReadAccessError("APPROVED_TARGET_BINDING_MISMATCH")

        analytics_bindings = self.portfolio_analytics_bindings
        if not isinstance(analytics_bindings, Mapping) or len(analytics_bindings) > 4096:
            raise ServiceReadAccessError("INVALID_PORTFOLIO_ANALYTICS_BINDINGS")
        normalized_analytics: dict[str, PortfolioAnalyticsBinding] = {}
        for portfolio_ref, binding in analytics_bindings.items():
            if (
                not _valid_identifier(portfolio_ref)
                or type(binding) is not PortfolioAnalyticsBinding
                or binding.portfolio_ref != portfolio_ref
            ):
                raise ServiceReadAccessError("INVALID_PORTFOLIO_ANALYTICS_BINDINGS")
            normalized_analytics[portfolio_ref] = binding
        if set(normalized_analytics) != set(self.allow_portfolio_refs):
            raise ServiceReadAccessError("PORTFOLIO_ANALYTICS_BINDING_MISMATCH")
        if normalized_analytics:
            required_analytics_methods = (
                "upload_portfolio_analytics_input",
                "submit_portfolio_analytics_task",
                "query_portfolio_analytics_task",
                "cancel_portfolio_analytics_task",
            )
            if any(
                not inspect.iscoroutinefunction(getattr(self.worker, name, None))
                for name in required_analytics_methods
            ):
                raise ServiceReadAccessError("INVALID_WORKER")
            identity = self.application_identity
            role_value = getattr(getattr(identity, "role", None), "value", None)
            if (
                role_value != "application_client"
                or not _valid_identifier(getattr(identity, "principal_ref", None))
                or not _valid_identifier(getattr(identity, "actor_ref", None))
                or (
                    getattr(identity, "delegate_ref", None) is not None
                    and not _valid_identifier(identity.delegate_ref)
                )
            ):
                raise ServiceReadAccessError("INVALID_APPLICATION_IDENTITY")
        object.__setattr__(
            self, "portfolio_analytics_bindings", MappingProxyType(normalized_analytics)
        )


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

    def _resolve(self, subject: str, selector: str, grant_field: str) -> ReadAccess:
        if not _valid_identifier(subject) or not _valid_identifier(selector):
            raise ServiceReadAccessError("ACCESS_DENIED")
        access = self._access_by_subject.get(subject)
        if access is None or selector not in getattr(access, grant_field):
            raise ServiceReadAccessError("ACCESS_DENIED")
        return access


def _immutable_selectors(value: object) -> frozenset[str]:
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
