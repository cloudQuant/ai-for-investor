"""Capture one raw Sina ``sh000001`` index-history HTTP response for review.

This helper deliberately does not import the AkShare producer, a database
configuration module, or any decoder.  The default plan is offline; one exact
request requires ``--capture``.  Captured bytes are immutable content-addressed
artifacts and the manifest records only transport facts.  No wrapper parsing is
performed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import stat
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SOURCE_URL = "https://finance.sina.com.cn/realstock/company/sh000001/hisdata/klc_kl.js"
SOURCE_PARAMS = {"d": "2020_2_4"}
MAX_BODY_BYTES = 24 * 1024 * 1024
HTTP_TIMEOUT = (5.0, 12.0)
OUTER_TIMEOUT_SECONDS = 45.0
CHUNK_BYTES = 64 * 1024


class ProbeError(RuntimeError):
    """The bounded raw-response capture could not be completed."""


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _artifact_root() -> Path:
    return _backend_root() / "var" / "source-artifacts" / "sina-index-daily"


def _manifest_root() -> Path:
    return _backend_root() / "var" / "reports" / "iteration203" / "sina-index-wire-probe"


def _ensure_private_directory(path: Path) -> None:
    root = _backend_root()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise ProbeError("fixed probe output escaped the backend root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if current.exists() and (current.is_symlink() or not current.is_dir()):
            raise ProbeError("probe output path contains a symlink or non-directory")
        current.mkdir(mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_body(body: bytes) -> str:
    digest = hashlib.sha256(body).hexdigest()
    root = _artifact_root()
    _ensure_private_directory(root)
    path = root / f"{digest}.body"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or metadata.st_size != len(body)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or _sha256_file(path) != digest
        ):
            raise ProbeError("existing content-addressed body failed verification") from None
        return digest

    try:
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(body)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return digest


def _write_manifest(manifest: dict[str, Any]) -> Path:
    root = _manifest_root()
    _ensure_private_directory(root)
    stamp = str(manifest["captured_at_utc"]).replace(":", "").replace("-", "")
    path = root / f"{stamp}-{uuid.uuid4().hex}.json"
    encoded = (json.dumps(manifest, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return path


def _capture_one_response(*, get: Any, captured_at_utc: str | None = None) -> dict[str, Any]:
    """Perform exactly one fixed request and persist its undecoded response body."""
    response = get(
        SOURCE_URL,
        params=dict(SOURCE_PARAMS),
        timeout=HTTP_TIMEOUT,
        stream=True,
        allow_redirects=False,
    )
    try:
        status = int(response.status_code)
        final_url = str(getattr(response, "url", ""))
        headers = {str(key): str(value) for key, value in response.headers.items()}
        body = bytearray()
        for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
            if not chunk:
                continue
            if len(body) + len(chunk) > MAX_BODY_BYTES:
                raise ProbeError(f"response exceeded {MAX_BODY_BYTES} byte cap")
            body.extend(chunk)
    finally:
        response.close()

    raw_body = bytes(body)
    sha256 = _write_body(raw_body)
    captured_at = captured_at_utc or datetime.now(timezone.utc).isoformat()
    manifest = {
        "capture_status": "raw_captured_pending_review",
        "source": "sina",
        "requested_symbol": "sh000001",
        "request_url": SOURCE_URL,
        "request_params": dict(SOURCE_PARAMS),
        "request_count": 1,
        "redirects_allowed": False,
        "final_url": final_url,
        "http_status": status,
        "response_headers": headers,
        "response_bytes": len(raw_body),
        "response_sha256": sha256,
        "artifact_id": sha256,
        "artifact_path": str(_artifact_root() / f"{sha256}.body"),
        "body_representation": "requests.iter_content application body bytes; HTTP content decoding may apply",
        "wrapper_inspection": "not_parsed",
        "captured_at_utc": captured_at,
    }
    manifest_path = _write_manifest(manifest)
    return {**manifest, "manifest_path": str(manifest_path)}


def _capture_worker(send: Any) -> None:
    try:
        import requests

        result = _capture_one_response(get=requests.get)
        send.send_bytes(json.dumps({"ok": True, "result": result}).encode("utf-8"))
    except BaseException as exc:
        try:
            send.send_bytes(
                json.dumps(
                    {"ok": False, "error_type": type(exc).__name__, "error": str(exc)[:300]}
                ).encode("utf-8")
            )
        except Exception:
            pass
    finally:
        send.close()


def _terminate(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=2.0)
    if process.is_alive():
        process.kill()
        process.join(timeout=2.0)


def capture_once(*, timeout_seconds: float = OUTER_TIMEOUT_SECONDS) -> dict[str, Any]:
    if timeout_seconds <= 0 or timeout_seconds > OUTER_TIMEOUT_SECONDS:
        raise ValueError(f"timeout_seconds must be in (0, {OUTER_TIMEOUT_SECONDS}] ")
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_capture_worker, args=(send,), name="sina-index-wire-probe")
    deadline = time.monotonic() + timeout_seconds
    process.start()
    send.close()
    try:
        remaining = max(0.0, deadline - time.monotonic())
        if remaining == 0.0 or not receive.poll(remaining):
            _terminate(process)
            raise TimeoutError("Sina raw probe exceeded its outer wall deadline")
        encoded = receive.recv_bytes(MAX_BODY_BYTES + 64 * 1024)
        process.join(timeout=max(0.0, deadline - time.monotonic()))
        if process.is_alive():
            _terminate(process)
            raise TimeoutError("Sina raw probe worker did not stop before its wall deadline")
        if process.exitcode != 0:
            raise ProbeError(f"Sina raw probe worker exited with status {process.exitcode}")
        payload = json.loads(encoded.decode("utf-8"))
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            if isinstance(payload, dict):
                raise ProbeError(
                    f"{payload.get('error_type', 'ProbeError')}: {payload.get('error', '')}"
                )
            raise ProbeError("Sina raw probe worker returned an invalid result")
        return payload["result"]
    finally:
        receive.close()
        if process.is_alive():
            _terminate(process)
        process.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true", help="show the fixed route; do no network I/O")
    mode.add_argument(
        "--capture", action="store_true", help="issue exactly one bounded HTTP request"
    )
    args = parser.parse_args(argv)
    if not args.capture:
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "source": "sina",
                    "requested_symbol": "sh000001",
                    "request_url": SOURCE_URL,
                    "request_params": SOURCE_PARAMS,
                    "network_requests": 0,
                    "wrapper_inspection": "not_performed",
                },
                sort_keys=True,
            )
        )
        return 0
    try:
        result = capture_once()
    except Exception as exc:
        print(json.dumps({"capture_status": "failed", "error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(result, sort_keys=True, ensure_ascii=False))
    return 0 if result["http_status"] == 200 else 2


if __name__ == "__main__":
    raise SystemExit(main())
