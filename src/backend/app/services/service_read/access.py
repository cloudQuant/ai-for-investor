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

__all__ = [
    "ReadAccess",
    "ServiceReadAccessDirectory",
    "ServiceReadAccessError",
]


class ServiceReadAccessError(RuntimeError):
    """A finite configuration or authorization failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ReadAccess:
    """One preassembled async worker and its exact permitted selectors.

    Selectors are copied to immutable sets during construction. The worker
    must be distinct for each subject; its session factory is responsible for
    binding the exact server-granted service identity.
    """

    worker: Any
    allow_account_refs: frozenset[str] = frozenset()
    allow_order_scope_refs: frozenset[str] = frozenset()
    allow_monitor_scope_refs: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        required_methods = ("read_account", "read_order", "read_strategy_health")
        if any(
            not inspect.iscoroutinefunction(getattr(self.worker, name, None))
            for name in required_methods
        ):
            raise ServiceReadAccessError("INVALID_WORKER")
        for name in (
            "allow_account_refs",
            "allow_order_scope_refs",
            "allow_monitor_scope_refs",
        ):
            object.__setattr__(self, name, _immutable_selectors(getattr(self, name)))


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

    def resolve_order_scope(self, subject: str, scope_ref: str) -> ReadAccess:
        """Resolve one order-query scope for an exact authenticated subject."""

        return self._resolve(subject, scope_ref, "allow_order_scope_refs")

    def resolve_monitor_scope(self, subject: str, scope_ref: str) -> ReadAccess:
        """Resolve one telemetry scope for an exact authenticated subject."""

        return self._resolve(subject, scope_ref, "allow_monitor_scope_refs")

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
