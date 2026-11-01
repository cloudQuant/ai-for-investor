"""Process-local exclusion set for accounts owned by service-v2 Gateway.

The mapping is installed from trusted application deployment configuration.
It contains exact legacy gateway runtime keys and never accepts request data.
Keeping it separate from manager construction lets ASGI startup install the
barrier before a lazy ``LiveTradingManager`` can restore an old session.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager

_lock = threading.RLock()
_legacy_owner_operation_lock = threading.RLock()
_owners: dict[object, frozenset[str]] = {}


@contextmanager
def legacy_gateway_owner_operation() -> Iterator[None]:
    """Serialize a legacy owner transition against service-v2 startup/close.

    Callers must perform the exclusion check and any legacy connect/disconnect
    while holding this lock. Operator code holds it from the exclusion check
    through SDK owner startup, so no legacy connection can slip between the
    check and the first service-v2 write-capable owner.
    """

    with _legacy_owner_operation_lock:
        yield


def register_legacy_gateway_exclusions(owner: object, gateway_keys: Iterable[str]) -> None:
    """Install exact keys while an operator deployment may own its account."""

    keys = frozenset(gateway_keys)
    if not keys or any(type(key) is not str or not key or key != key.strip() for key in keys):
        raise ValueError("invalid legacy gateway exclusion set")
    with _lock:
        previous = _owners.get(owner)
        if previous is not None and previous != keys:
            raise RuntimeError("legacy gateway exclusion owner changed its key set")
        _owners[owner] = keys


def unregister_legacy_gateway_exclusions(owner: object) -> None:
    """Release exclusions only after the owning operator has closed cleanly."""

    with _lock:
        _owners.pop(owner, None)


def is_legacy_gateway_excluded(gateway_key: str) -> bool:
    if type(gateway_key) is not str:
        return False
    with _lock:
        return any(gateway_key in keys for keys in _owners.values())


def is_legacy_manual_gateway_excluded(exchange_type: str, account_id: str | None) -> bool:
    """Check a manual owner without resolving credentials or reading secrets.

    When the request does not name an account, fail closed for that exchange
    if any configured manual key exists. The legacy connector may otherwise
    fill its account from local settings after this guard runs.
    """

    exchange = str(exchange_type or "").strip().upper()
    if not exchange:
        return False
    prefix = f"manual:{exchange}:"
    with _lock:
        keys = tuple(key for values in _owners.values() for key in values)
    if account_id:
        return f"{prefix}{account_id}" in keys
    return any(key.startswith(prefix) for key in keys)


def legacy_gateway_exclusions() -> frozenset[str]:
    with _lock:
        return frozenset(key for keys in _owners.values() for key in keys)
