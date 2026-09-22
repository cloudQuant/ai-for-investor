"""Secure access to signed market-data binding artifacts."""

from __future__ import annotations

import errno
import hashlib
import os
import stat
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, BinaryIO

_MARKET_DATA_BINDING_CONFIG_KEY = "market_data_binding"


class MarketDataBindingRuntimeError(ValueError):
    """Stable, fail-closed error for a bound research backtest runtime."""


def _market_data_binding_artifact_root() -> Path:
    """Return the configured server-owned research artifact root without creating it."""
    from app.config import get_settings

    settings = get_settings()
    raw_root = str(getattr(settings, "MARKET_DATA_RESEARCH_ARTIFACT_ROOT", "") or "").strip()
    root = Path(raw_root).expanduser()
    if not raw_root or not root.is_absolute():
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    try:
        resolved = root.resolve(strict=True)
    except OSError as exc:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_MISSING") from exc
    if not resolved.is_dir():
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    return resolved


def _validated_market_data_binding_payload(data: Mapping[str, Any]) -> dict[str, object]:
    """Return the HMAC-authenticated artifact payload without touching its path."""
    if not isinstance(data, Mapping):
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_RUNTIME_CONFIG_INVALID")
    raw_metadata = data.get(_MARKET_DATA_BINDING_CONFIG_KEY)
    if not isinstance(raw_metadata, Mapping):
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_RUNTIME_CONFIG_INVALID")
    metadata = dict(raw_metadata)
    expected_metadata_keys = {
        "binding_id",
        "binding_hash",
        "owner_user_id",
        "signature",
        "artifact_relative_path",
        "artifact_sha256",
        "artifact_size_bytes",
        "manifest_hash",
        "query_semantics",
        "runtime_capability_context",
    }
    if "runtime_capability_context" not in metadata:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_CAPABILITY_CONTEXT_REQUIRED")
    if set(metadata) != expected_metadata_keys:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_RUNTIME_CONFIG_INVALID")

    try:
        from app.config import get_settings
        from app.services.market_data.research_binding import (
            build_market_data_binding_signature_payload,
            verify_market_data_binding_signature,
            verify_market_data_runtime_capability_context,
        )

        settings = get_settings()
        signing_key = str(getattr(settings, "MARKET_DATA_RESEARCH_ARTIFACT_SIGNING_KEY", "") or "")
        expected_payload = build_market_data_binding_signature_payload(
            binding_id=str(metadata["binding_id"]),
            binding_hash=str(metadata["binding_hash"]),
            owner_user_id=str(metadata["owner_user_id"]),
            artifact_relative_path=str(metadata["artifact_relative_path"]),
            artifact_sha256=str(metadata["artifact_sha256"]),
            artifact_size_bytes=metadata["artifact_size_bytes"],
            query_semantics=metadata["query_semantics"],
        )
        signed_payload = verify_market_data_binding_signature(
            str(metadata["signature"]),
            signing_key,
        )
        verify_market_data_runtime_capability_context(
            metadata["runtime_capability_context"],
            signing_key,
            binding_id=str(expected_payload["binding_id"]),
            binding_hash=str(expected_payload["binding_hash"]),
            owner_user_id=str(expected_payload["owner_user_id"]),
        )
    except MarketDataBindingRuntimeError:
        raise
    except Exception as exc:
        message = str(exc).strip()
        if message.startswith("MARKET_DATA_BINDING_"):
            raise MarketDataBindingRuntimeError(message) from exc
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_SIGNATURE_INVALID") from exc

    if dict(signed_payload) != expected_payload:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_SIGNATURE_INVALID")
    return expected_payload


def _binding_open_flags(*, directory: bool) -> int:
    """Return fail-closed POSIX descriptor flags for a sealed artifact chain."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if os.name != "posix" or not nofollow or os.open not in os.supports_dir_fd:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    flags = os.O_RDONLY | nofollow | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    if directory:
        directory_flag = getattr(os, "O_DIRECTORY", 0)
        if not directory_flag:
            raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
        flags |= directory_flag
    return flags


def _raise_binding_artifact_open_error(exc: OSError) -> None:
    """Normalize descriptor-open failures without exposing filesystem detail."""
    if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID") from exc
    raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_MISSING") from exc


def _close_binding_fd(fd: int | None) -> None:
    if fd is None:
        return
    try:
        os.close(fd)
    except OSError:
        pass


def _open_binding_directory_at(parent_fd: int, part: str) -> int:
    """Open one direct directory child while refusing symlinks and files."""
    if not part or part in {".", ".."} or "/" in part:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    try:
        descriptor = os.open(part, _binding_open_flags(directory=True), dir_fd=parent_fd)
    except OSError as exc:
        _raise_binding_artifact_open_error(exc)
        raise AssertionError("unreachable") from exc
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
        return descriptor
    except Exception:
        _close_binding_fd(descriptor)
        raise


def _open_secure_binding_root(root: Path) -> int:
    """Anchor an artifact root through a no-symlink descriptor chain from `/`."""
    if not root.is_absolute() or root.anchor != os.path.sep:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    try:
        descriptor = os.open(root.anchor, _binding_open_flags(directory=True))
    except OSError as exc:
        _raise_binding_artifact_open_error(exc)
        raise AssertionError("unreachable") from exc
    try:
        for part in root.parts:
            if part == root.anchor:
                continue
            next_descriptor = _open_binding_directory_at(descriptor, part)
            _close_binding_fd(descriptor)
            descriptor = next_descriptor
        return descriptor
    except Exception:
        _close_binding_fd(descriptor)
        raise


def _open_verified_market_data_binding_descriptor(
    root: Path,
    binding_hash: str,
) -> tuple[int, Path]:
    """Open the exact `bindings/<hash>/data.csv` inode from a secure root fd."""
    root_fd = _open_secure_binding_root(root)
    current_fd: int = root_fd
    try:
        for part in ("bindings", binding_hash):
            next_fd = _open_binding_directory_at(current_fd, part)
            _close_binding_fd(current_fd)
            current_fd = next_fd
        try:
            artifact_fd = os.open(
                "data.csv",
                _binding_open_flags(directory=False),
                dir_fd=current_fd,
            )
        except OSError as exc:
            _raise_binding_artifact_open_error(exc)
            raise AssertionError("unreachable") from exc
        artifact_path = root / "bindings" / binding_hash / "data.csv"
        return artifact_fd, artifact_path
    finally:
        _close_binding_fd(current_fd)


def _sha256_open_file(handle: BinaryIO) -> str:
    """Hash an already-open descriptor and rewind it for its sole consumer."""
    digest = hashlib.sha256()
    try:
        handle.seek(0)
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
        handle.seek(0)
    except (OSError, ValueError) as exc:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_MISSING") from exc
    return digest.hexdigest()


def _artifact_stat_fingerprint(artifact_stat: os.stat_result) -> tuple[int, int, int, int, int]:
    """Capture descriptor identity metadata around the digest read."""
    return (
        artifact_stat.st_dev,
        artifact_stat.st_ino,
        artifact_stat.st_size,
        getattr(artifact_stat, "st_mtime_ns", 0),
        getattr(artifact_stat, "st_ctime_ns", 0),
    )


def _verify_open_market_data_binding_artifact(
    handle: BinaryIO,
    expected_payload: Mapping[str, object],
) -> None:
    """Verify one opened inode before it is handed to pandas for the only read."""
    try:
        before = os.fstat(handle.fileno())
    except (OSError, ValueError) as exc:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_MISSING") from exc
    if not stat.S_ISREG(before.st_mode):
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    expected_size_value = expected_payload.get("artifact_size_bytes")
    if (
        isinstance(expected_size_value, bool)
        or not isinstance(expected_size_value, int)
        or expected_size_value < 1
    ):
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_RUNTIME_CONFIG_INVALID")
    expected_size = expected_size_value
    if before.st_size != expected_size:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_SIZE_MISMATCH")
    actual_sha256 = _sha256_open_file(handle)
    try:
        after = os.fstat(handle.fileno())
    except (OSError, ValueError) as exc:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_MISSING") from exc
    if after.st_size != expected_size:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_SIZE_MISMATCH")
    if _artifact_stat_fingerprint(before) != _artifact_stat_fingerprint(after):
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_DIGEST_MISMATCH")
    if actual_sha256 != expected_payload["artifact_sha256"]:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_DIGEST_MISMATCH")


@contextmanager
def open_verified_market_data_binding_file(
    data: Mapping[str, Any],
    *,
    artifact_root_resolver: Callable[[], Path] | None = None,
) -> Iterator[tuple[BinaryIO, Path]]:
    """Yield the one HMAC-verified CSV descriptor for a bound research run.

    The descriptor is rooted at the deployment-owned artifact directory and
    is opened through every path component with ``O_NOFOLLOW``.  Hashing and
    the caller's CSV read share that descriptor, so a rename or symlink swap
    after validation cannot make pandas reopen a different pathname.
    """
    expected_payload = _validated_market_data_binding_payload(data)

    binding_hash = str(expected_payload["binding_hash"])
    relative_path = str(expected_payload["artifact_relative_path"])
    expected_relative_path = f"bindings/{binding_hash}/data.csv"
    if relative_path != expected_relative_path:
        raise MarketDataBindingRuntimeError("MARKET_DATA_BINDING_ARTIFACT_PATH_INVALID")
    root = (artifact_root_resolver or _market_data_binding_artifact_root)()
    artifact_fd: int | None = None
    try:
        artifact_fd, artifact_path = _open_verified_market_data_binding_descriptor(
            root, binding_hash
        )
        with os.fdopen(artifact_fd, "rb", closefd=True) as handle:
            artifact_fd = None
            _verify_open_market_data_binding_artifact(handle, expected_payload)
            yield handle, artifact_path
    finally:
        _close_binding_fd(artifact_fd)


def resolve_verified_market_data_binding_file(data: Mapping[str, Any]) -> Path:
    """Return a verified diagnostic path for compatibility; never use it for I/O.

    Backtest execution must use :func:`open_verified_market_data_binding_file`
    so the verified descriptor, rather than this path value, reaches pandas.
    """
    with open_verified_market_data_binding_file(data) as (_handle, artifact_path):
        return artifact_path
