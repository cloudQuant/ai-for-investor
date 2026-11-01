"""Fixed child entry point for code-profiled service-v2 strategy runs."""

from __future__ import annotations

import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from app.services.live_trading.service_execution_launch import (
    SERVICE_EXECUTION_STOP_COMMAND,
    ServiceStrategyProfileError,
    get_service_strategy_profile_registry,
    run_profiled_strategy_script,
)


def _read_stop_command(request_stop: Callable[[], None]) -> None:
    descriptor = sys.stdin.fileno()
    command = bytearray()
    while len(command) < 16 and b"\n" not in command:
        try:
            chunk = os.read(descriptor, 16 - len(command))
        except OSError:
            return
        if not chunk:
            return
        command.extend(chunk)
    if bytes(command) == SERVICE_EXECUTION_STOP_COMMAND:
        request_stop()
        return
    if command:
        raise ServiceStrategyProfileError("INVALID_STOP_COMMAND")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        return 2
    try:
        profile_ref = os.environ.get("AFI_SERVICE_EXECUTION_PROFILE_REF", "")
        registry = get_service_strategy_profile_registry({profile_ref})
        profile, context = registry.context_from_environment(os.environ)
        script_path = Path(args[0]).resolve(strict=True)
        error_codes: list[str] = []
        error_lock = threading.Lock()

        def stop_reader(request_stop: Callable[[], None]) -> None:
            def read() -> None:
                try:
                    _read_stop_command(request_stop)
                except ServiceStrategyProfileError as error:
                    with error_lock:
                        error_codes.append(error.code)

            threading.Thread(
                target=read,
                name="afi-service-strategy-stop-reader",
                daemon=True,
            ).start()

        run_profiled_strategy_script(
            script_path,
            profile,
            context,
            stop_reader=stop_reader,
        )
        with error_lock:
            if error_codes:
                return 2
        return 0
    except ServiceStrategyProfileError as error:
        sys.stderr.write(f"AFI_SERVICE_EXECUTION_ERROR:{error.code}\n")
        sys.stderr.flush()
        return 2
    except BaseException as error:
        code = getattr(error, "code", None)
        if type(code) is not str or not code.isidentifier():
            code = "STRATEGY_RUN_FAILED"
        sys.stderr.write(f"AFI_SERVICE_EXECUTION_ERROR:{code}\n")
        sys.stderr.flush()
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
