import asyncio
import contextlib
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.services.live_trading import instance as live_instance_service
from app.services.live_trading.metadata import (
    SERVER_RUNTIME_LAUNCH_ID_FIELD,
    SERVER_RUNTIME_LAUNCH_STARTED_AT_FIELD,
    clear_server_runtime_launch_observation,
    instance_timestamp,
    normalize_instance_metadata,
    server_runtime_launch_timestamp,
)
from app.services.live_trading.service_execution_launch import (
    SERVICE_EXECUTION_READY_ENV,
    ServiceStrategyProfileError,
)

# Callback dependencies injected by ``LiveTradingManager``; typed loosely
# since the concrete signatures vary per callback.
_Cb = Callable[..., Any]
_SUBPROCESS_STDOUT_LOG = "subprocess.stdout.log"
_SUBPROCESS_STDERR_LOG = "subprocess.stderr.log"
_SERVICE_EXECUTION_MANAGED_FIELD = "_server_service_execution_managed"
_SERVICE_EXECUTION_PROFILE_FIELD = "_server_service_execution_profile_ref"
_SERVICE_EXECUTION_RUN_FIELD = "_server_service_execution_run_id"
_SERVICE_EXECUTION_START_TIMEOUT_SECONDS = 30.0


def _clear_service_execution_metadata(instance: dict[str, Any]) -> None:
    instance.pop(_SERVICE_EXECUTION_MANAGED_FIELD, None)
    instance.pop(_SERVICE_EXECUTION_PROFILE_FIELD, None)
    instance.pop(_SERVICE_EXECUTION_RUN_FIELD, None)


def _optional_lock(lock: Any | None) -> contextlib.AbstractAsyncContextManager[Any]:
    return lock if lock is not None else contextlib.nullcontext()


def _decode_output_tail(data: bytes, limit: int = 500) -> str:
    for encoding in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(encoding)[-limit:]
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")[-limit:]


def _read_file_tail(path: Path, limit: int = 500, read_bytes: int = 8192) -> str:
    try:
        with path.open("rb") as handle:
            try:
                handle.seek(-read_bytes, os.SEEK_END)
            except OSError:
                handle.seek(0)
            data = handle.read()
    except OSError:
        return ""
    return _decode_output_tail(data, limit=limit)


def _close_subprocess_log_handles(proc: asyncio.subprocess.Process) -> None:
    proc_attrs = getattr(proc, "__dict__", {})
    for attr in ("_bt_stdout_handle", "_bt_stderr_handle"):
        handle = proc_attrs.get(attr)
        if handle is None:
            continue
        try:
            handle.close()
        except OSError:
            pass


async def _wait_for_service_execution_ready(
    proc: asyncio.subprocess.Process,
    stdout_path: Path,
    *,
    start_offset: int,
    marker: str,
    timeout_seconds: float = _SERVICE_EXECUTION_START_TIMEOUT_SECONDS,
) -> None:
    expected = marker.encode("utf-8")
    position = start_offset
    partial = bytearray()
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        try:
            with stdout_path.open("rb") as handle:
                handle.seek(position)
                chunk = handle.read(4096)
        except OSError:
            chunk = b""
        if chunk:
            position += len(chunk)
            partial.extend(chunk)
            while b"\n" in partial:
                line, _, remainder = partial.partition(b"\n")
                partial[:] = remainder
                if line.rstrip(b"\r") == expected:
                    return
        if proc.returncode is not None:
            raise RuntimeError("SERVICE_EXECUTION_EXITED_BEFORE_READY")
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("SERVICE_EXECUTION_START_TIMEOUT")
        await asyncio.sleep(0.05)


def _merge_runtime_contract_metadata(
    target: dict[str, Any],
    source: dict[str, Any],
) -> None:
    raw_source_params = source.get("params")
    source_params = raw_source_params if isinstance(raw_source_params, dict) else {}
    contract_metadata = source_params.get("contract_metadata")
    if not isinstance(contract_metadata, dict) or not contract_metadata:
        return

    target_params = (
        dict(target.get("params") or {}) if isinstance(target.get("params"), dict) else {}
    )
    target_metadata = (
        dict(target_params.get("contract_metadata") or {})
        if isinstance(target_params.get("contract_metadata"), dict)
        else {}
    )
    for key, value in contract_metadata.items():
        if isinstance(value, dict):
            target_metadata[str(key)] = dict(value)
    if not target_metadata:
        return
    target_params["contract_metadata"] = target_metadata
    target["params"] = target_params


async def start_instance(
    instance_id: str,
    load_instances: _Cb,
    save_instances: _Cb,
    is_pid_alive: _Cb,
    resolve_strategy_dir: _Cb,
    build_subprocess_env: _Cb,
    release_gateway_for_instance: _Cb,
    wait_process_callback: _Cb,
    processes: dict[str, Any],
    stopping_instances: set[str],
    instance_lock: Any | None = None,
    user_id: str | None = None,
    build_subprocess_command: _Cb | None = None,
    execution_mode: str = "live",
    allow_service_strategy_execution: bool = True,
) -> dict[str, Any]:
    instances = load_instances()
    if instance_id not in instances:
        raise live_instance_service.InstanceAccessError("Instance not found")
    inst = instances[instance_id]
    if user_id is not None and inst.get("user_id") != user_id:
        raise live_instance_service.InstanceAccessError("Instance not found")

    if inst.get(_SERVICE_EXECUTION_MANAGED_FIELD) is True:
        raise RuntimeError("SERVICE_EXECUTION_OWNER_UNCERTAIN")
    current_proc = processes.get(instance_id)
    if current_proc is not None:
        raise ValueError("Strategy process is still owned")

    if inst["status"] == "running" and inst.get("pid") and is_pid_alive(inst["pid"]):
        raise ValueError("Strategy is already running")

    if execution_mode not in {"live", "simulation"}:
        raise ValueError("INVALID_EXECUTION_MODE")
    launch_instance = dict(inst)
    # InstanceStore is keyed by instance id and does not duplicate that key
    # inside each persisted row.  Trusted service profiles bind the launch
    # context to both subject and instance, so pass the key explicitly to the
    # server-side profile resolver without persisting it as a new field.
    launch_instance["id"] = instance_id
    launch_instance["_server_execution_mode"] = execution_mode
    launch_instance["_server_allow_service_strategy_execution"] = bool(
        allow_service_strategy_execution
    )
    try:
        runtime_dir = str(inst.get("runtime_dir") or "").strip()
        strategy_dir = (
            Path(runtime_dir).expanduser()
            if runtime_dir
            else resolve_strategy_dir(inst["strategy_id"])
        )
    except ValueError as exc:
        raise ValueError(f"Invalid strategy_id: {inst['strategy_id']}") from exc
    run_py = strategy_dir / "run.py"
    if not run_py.is_file():
        raise ValueError(f"run.py does not exist: {run_py}")

    # Seal the old launch epoch before any gateway work or subprocess spawn.
    # ``get_instance`` is synchronous and may run in another ASGI/Gunicorn
    # worker, so it can observe the newly spawned PID before this coroutine
    # reaches its post-spawn persistence block.  A ``starting`` record with
    # no server launch UUID is intentionally unusable for paper review,
    # approval, and live preparation during that interval.
    pending_now = instance_timestamp()
    async with _optional_lock(instance_lock):
        latest = load_instances()
        latest_inst = latest.get(instance_id)
        if not isinstance(latest_inst, dict):
            raise live_instance_service.InstanceAccessError("Instance not found")
        if user_id is not None and latest_inst.get("user_id") != user_id:
            raise live_instance_service.InstanceAccessError("Instance not found")
        if str(latest_inst.get("status") or "").strip().casefold() == "starting":
            raise ValueError("Strategy start is already in progress")
        if (
            str(latest_inst.get("status") or "").strip().casefold() == "running"
            and latest_inst.get("pid")
            and is_pid_alive(latest_inst["pid"])
        ):
            raise ValueError("Strategy is already running")
        latest_inst["status"] = "starting"
        latest_inst["pid"] = None
        latest_inst["error"] = None
        latest_inst["started_at"] = None
        clear_server_runtime_launch_observation(latest_inst)
        normalize_instance_metadata(
            latest_inst, instance_id=instance_id, now=pending_now, touch=True
        )
        latest[instance_id] = latest_inst
        save_instances(latest)
        inst = latest_inst

    try:
        # Gateway preparation may wait for an external broker to authenticate.
        # Keep that synchronous adapter work off the ASGI event loop so a bad
        # broker credential cannot stall health checks, status polling, or the
        # portfolio/risk APIs while this instance is being started.
        env = await asyncio.to_thread(
            build_subprocess_env, instance_id, launch_instance, strategy_dir
        )
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        if not isinstance(exc, ServiceStrategyProfileError):
            release_gateway_for_instance(instance_id)
        now = instance_timestamp()
        async with _optional_lock(instance_lock):
            latest = load_instances()
            inst = latest.get(instance_id, inst)
            inst["status"] = "error"
            inst["pid"] = None
            inst["error"] = str(exc)
            inst["stopped_at"] = now
            clear_server_runtime_launch_observation(inst)
            normalize_instance_metadata(inst, instance_id=instance_id, now=now, touch=True)
            latest[instance_id] = inst
            save_instances(latest)
        raise ValueError(str(exc)) from exc

    sub_kwargs: dict[str, Any] = {}
    service_execution = bool(env.get("AFI_SERVICE_EXECUTION_PROFILE_REF"))
    stdout_handle = None
    stderr_handle = None
    stdout_path = strategy_dir / "logs" / _SUBPROCESS_STDOUT_LOG
    start_offset = 0
    try:
        if service_execution:
            if not env.get(SERVICE_EXECUTION_READY_ENV):
                raise ServiceStrategyProfileError("SERVICE_EXECUTION_READY_MARKER_UNAVAILABLE")
            if build_subprocess_command is None:
                raise ServiceStrategyProfileError("SERVICE_EXECUTION_COMMAND_UNAVAILABLE")
            command = build_subprocess_command(instance_id, inst, strategy_dir, env)
            if (
                type(command) not in (tuple, list)
                or not command
                or any(type(item) is not str or not item for item in command)
            ):
                raise ServiceStrategyProfileError("SERVICE_EXECUTION_COMMAND_INVALID")
            sub_kwargs["stdin"] = asyncio.subprocess.PIPE
        else:
            command = (sys.executable, str(run_py))
        if sys.platform == "win32":
            import subprocess as _sp

            sub_kwargs["creationflags"] = _sp.CREATE_NEW_PROCESS_GROUP | _sp.CREATE_NO_WINDOW
        logs_dir = strategy_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stderr_path = logs_dir / _SUBPROCESS_STDERR_LOG
        if stdout_path.exists():
            start_offset = stdout_path.stat().st_size
        stdout_handle = stdout_path.open("ab", buffering=0)
        stderr_handle = stderr_path.open("ab", buffering=0)
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=str(strategy_dir),
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
            **sub_kwargs,
        )
        # Handles are cleaned up dynamically via __dict__ in _close_subprocess_log_handles.
        proc.__dict__["_bt_stdout_handle"] = stdout_handle
        proc.__dict__["_bt_stderr_handle"] = stderr_handle
        proc.__dict__["_bt_stderr_path"] = str(stderr_path)
        proc.__dict__["_bt_service_execution"] = service_execution
    except (OSError, subprocess.SubprocessError, ServiceStrategyProfileError) as exc:
        for handle in (stdout_handle, stderr_handle):
            if handle is not None:
                try:
                    handle.close()
                except OSError:
                    pass
        if not service_execution:
            release_gateway_for_instance(instance_id)
        failed_now = instance_timestamp()
        async with _optional_lock(instance_lock):
            latest = load_instances()
            failed = latest.get(instance_id, inst)
            if isinstance(failed, dict):
                failed["status"] = "error"
                failed["pid"] = None
                failed["error"] = str(exc)
                failed["stopped_at"] = failed_now
                clear_server_runtime_launch_observation(failed)
                normalize_instance_metadata(
                    failed, instance_id=instance_id, now=failed_now, touch=True
                )
                latest[instance_id] = failed
                save_instances(latest)
        raise
    stopping_instances.discard(instance_id)
    processes[instance_id] = proc

    if service_execution:
        inst[_SERVICE_EXECUTION_MANAGED_FIELD] = True
        inst[_SERVICE_EXECUTION_PROFILE_FIELD] = env.get("AFI_SERVICE_EXECUTION_PROFILE_REF")
        inst[_SERVICE_EXECUTION_RUN_FIELD] = env.get("AFI_SERVICE_EXECUTION_RUN_ID")
        started_now = instance_timestamp()
        async with _optional_lock(instance_lock):
            latest = load_instances()
            current = latest.get(instance_id, inst)
            if isinstance(current, dict):
                current["pid"] = proc.pid
                current[_SERVICE_EXECUTION_MANAGED_FIELD] = True
                current[_SERVICE_EXECUTION_PROFILE_FIELD] = env.get(
                    "AFI_SERVICE_EXECUTION_PROFILE_REF"
                )
                current[_SERVICE_EXECUTION_RUN_FIELD] = env.get("AFI_SERVICE_EXECUTION_RUN_ID")
                normalize_instance_metadata(
                    current, instance_id=instance_id, now=started_now, touch=True
                )
                latest[instance_id] = current
                save_instances(latest)
                inst = current
        try:
            await _wait_for_service_execution_ready(
                proc,
                stdout_path,
                start_offset=start_offset,
                marker=env.get(SERVICE_EXECUTION_READY_ENV, ""),
            )
        except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
            ready_now = instance_timestamp()
            alive = proc.returncode is None
            async with _optional_lock(instance_lock):
                latest = load_instances()
                failed = latest.get(instance_id, inst)
                if isinstance(failed, dict):
                    failed["status"] = "error"
                    failed["pid"] = proc.pid if alive else None
                    failed["error"] = str(exc)
                    failed["stopped_at"] = None if alive else ready_now
                    if alive:
                        failed[_SERVICE_EXECUTION_MANAGED_FIELD] = True
                        failed[_SERVICE_EXECUTION_PROFILE_FIELD] = env.get(
                            "AFI_SERVICE_EXECUTION_PROFILE_REF"
                        )
                        failed[_SERVICE_EXECUTION_RUN_FIELD] = env.get(
                            "AFI_SERVICE_EXECUTION_RUN_ID"
                        )
                    else:
                        if proc.returncode == 0:
                            _clear_service_execution_metadata(failed)
                        else:
                            failed[_SERVICE_EXECUTION_MANAGED_FIELD] = True
                            failed[_SERVICE_EXECUTION_PROFILE_FIELD] = env.get(
                                "AFI_SERVICE_EXECUTION_PROFILE_REF"
                            )
                            failed[_SERVICE_EXECUTION_RUN_FIELD] = env.get(
                                "AFI_SERVICE_EXECUTION_RUN_ID"
                            )
                    normalize_instance_metadata(
                        failed, instance_id=instance_id, now=ready_now, touch=True
                    )
                    latest[instance_id] = failed
                    save_instances(latest)
            if alive:
                asyncio.create_task(wait_process_callback(instance_id, proc))
            else:
                await proc.wait()
                _close_subprocess_log_handles(proc)
                processes.pop(instance_id, None)
            raise RuntimeError("SERVICE_EXECUTION_START_FAILED") from None

    refreshed_inst = inst
    now = instance_timestamp()
    async with _optional_lock(instance_lock):
        latest = load_instances()
        latest_inst = latest.get(instance_id)
        if isinstance(latest_inst, dict):
            _merge_runtime_contract_metadata(latest_inst, refreshed_inst)
            inst = latest_inst
        else:
            inst = refreshed_inst
        inst["status"] = "running"
        inst["pid"] = proc.pid
        inst["error"] = None
        inst["started_at"] = now
        # These private values are persisted only after a process has actually
        # spawned.  ``started_at`` is a legacy local, second-precision display
        # field; paper promotion instead consumes the UTC microsecond timestamp
        # and fresh UUID below, so CST hosts and same-second restarts cannot
        # inherit an earlier observation window.
        inst[SERVER_RUNTIME_LAUNCH_ID_FIELD] = uuid.uuid4().hex
        inst[SERVER_RUNTIME_LAUNCH_STARTED_AT_FIELD] = server_runtime_launch_timestamp()
        if service_execution:
            inst[_SERVICE_EXECUTION_MANAGED_FIELD] = True
            inst[_SERVICE_EXECUTION_PROFILE_FIELD] = env.get("AFI_SERVICE_EXECUTION_PROFILE_REF")
            inst[_SERVICE_EXECUTION_RUN_FIELD] = env.get("AFI_SERVICE_EXECUTION_RUN_ID")
        else:
            inst.pop(_SERVICE_EXECUTION_MANAGED_FIELD, None)
            inst.pop(_SERVICE_EXECUTION_PROFILE_FIELD, None)
            inst.pop(_SERVICE_EXECUTION_RUN_FIELD, None)
        inst["stopped_at"] = None
        normalize_instance_metadata(inst, instance_id=instance_id, now=now, touch=True)
        latest[instance_id] = inst
        save_instances(latest)
    asyncio.create_task(wait_process_callback(instance_id, proc))
    inst["id"] = instance_id
    return inst


async def stop_instance(
    instance_id: str,
    load_instances: _Cb,
    save_instances: _Cb,
    is_pid_alive: _Cb,
    kill_pid: _Cb,
    release_gateway_for_instance: _Cb,
    processes: dict[str, Any],
    stopping_instances: set[str],
    instance_lock: Any | None = None,
    user_id: str | None = None,
    graceful_stop_callback: _Cb | None = None,
) -> dict[str, Any]:
    instances = load_instances()
    if instance_id not in instances:
        raise live_instance_service.InstanceAccessError("Instance not found")
    inst = instances[instance_id]
    if user_id is not None and inst.get("user_id") != user_id:
        raise live_instance_service.InstanceAccessError("Instance not found")
    stopping_instances.add(instance_id)

    proc = processes.get(instance_id)
    service_execution = bool(
        inst.get(_SERVICE_EXECUTION_MANAGED_FIELD) is True
        or (proc is not None and getattr(proc, "_bt_service_execution", False))
    )
    if service_execution:
        if proc is None or graceful_stop_callback is None:
            stopping_instances.discard(instance_id)
            raise RuntimeError("SERVICE_EXECUTION_STOP_CONTROL_UNAVAILABLE")
        try:
            await graceful_stop_callback(instance_id, proc)
        except BaseException:
            stopping_instances.discard(instance_id)
            raise
        if proc.returncode != 0:
            stopping_instances.discard(instance_id)
            raise RuntimeError("SERVICE_EXECUTION_CLOSE_UNCERTAIN")
        processes.pop(instance_id, None)
    else:
        pid = inst.get("pid")
        if pid and is_pid_alive(pid):
            kill_pid(pid)

        proc = processes.pop(instance_id, None)
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except (ProcessLookupError, asyncio.TimeoutError, OSError, RuntimeError):
                proc.kill()

    now = instance_timestamp()
    async with _optional_lock(instance_lock):
        latest = load_instances()
        inst = latest.get(instance_id, inst)
        inst["status"] = "stopped"
        inst["pid"] = None
        inst["stopped_at"] = now
        if service_execution:
            _clear_service_execution_metadata(inst)
        clear_server_runtime_launch_observation(inst)
        normalize_instance_metadata(inst, instance_id=instance_id, now=now, touch=True)
        latest[instance_id] = inst
        save_instances(latest)
    if not service_execution:
        release_gateway_for_instance(instance_id)
    inst["id"] = instance_id
    return inst


async def start_all(
    user_id: str | None,
    load_instances: _Cb,
    is_pid_alive: _Cb,
    start_instance_callback: _Cb,
) -> dict[str, Any]:
    instances = load_instances()
    success = 0
    failed = 0
    details = []
    for instance_id, inst in instances.items():
        if user_id is not None and inst.get("user_id") != user_id:
            continue
        if inst["status"] == "running" and inst.get("pid") and is_pid_alive(inst["pid"]):
            continue
        try:
            await start_instance_callback(instance_id)
            success += 1
            details.append(
                {"id": instance_id, "strategy_id": inst["strategy_id"], "result": "started"}
            )
        except Exception as exc:
            failed += 1
            details.append(
                {"id": instance_id, "strategy_id": inst["strategy_id"], "result": str(exc)}
            )
    return {"success": success, "failed": failed, "details": details}


async def stop_all(
    user_id: str | None,
    load_instances: _Cb,
    stop_instance_callback: _Cb,
) -> dict[str, Any]:
    instances = load_instances()
    success = 0
    failed = 0
    details = []
    for instance_id, inst in instances.items():
        if user_id is not None and inst.get("user_id") != user_id:
            continue
        if inst["status"] != "running":
            continue
        try:
            await stop_instance_callback(instance_id)
            success += 1
            details.append(
                {"id": instance_id, "strategy_id": inst["strategy_id"], "result": "stopped"}
            )
        except Exception as exc:
            failed += 1
            details.append(
                {"id": instance_id, "strategy_id": inst["strategy_id"], "result": str(exc)}
            )
    return {"success": success, "failed": failed, "details": details}


async def wait_process(
    instance_id: str,
    proc: asyncio.subprocess.Process,
    load_instances: _Cb,
    save_instances: _Cb,
    resolve_strategy_dir: _Cb,
    find_latest_log_dir: _Cb,
    release_gateway_for_instance: _Cb,
    processes: dict[str, Any],
    stopping_instances: set[str],
    instance_lock: Any | None = None,
) -> None:
    try:
        await proc.wait()
    except asyncio.CancelledError:
        # Supervisors can intentionally exit after starting a detached strategy
        # (for example run_dual_exchange_simulation.py --no-hold). In that case
        # asyncio cancels this background watcher while the child process is
        # still running and proc.returncode is still None. The instance must
        # remain running for the next monitor/backend process to observe it.
        pass
    except Exception as e:
        # wait() may raise if process already terminated; safe to ignore
        # but log for debugging visibility
        import logging

        logging.getLogger(__name__).debug("proc.wait() raised (ignored): %s", e)
    finally:
        _close_subprocess_log_handles(proc)
        service_execution = bool(getattr(proc, "_bt_service_execution", False))
        stale_callback = False
        async with _optional_lock(instance_lock):
            instances = load_instances()
            current_proc = processes.get(instance_id)
            if current_proc is not None and current_proc is not proc:
                stale_callback = True
            if instance_id in instances:
                inst = instances[instance_id]
                current_pid = inst.get("pid")
                if current_pid not in (None, proc.pid):
                    stale_callback = True
                if not stale_callback:
                    was_stopping = instance_id in stopping_instances
                    if proc.returncode is None and not was_stopping:
                        stale_callback = True
                    else:
                        if was_stopping:
                            inst["status"] = "stopped"
                            inst["error"] = None
                        elif proc.returncode != 0:
                            stderr = ""
                            if proc.stderr:
                                try:
                                    stderr_bytes = await proc.stderr.read()
                                    stderr = _decode_output_tail(stderr_bytes, limit=500)
                                except Exception as e:
                                    # stderr read failed; use empty string
                                    import logging

                                    logging.getLogger(__name__).warning(
                                        "Failed to read stderr: %s", e
                                    )
                            if not stderr:
                                proc_attrs = getattr(proc, "__dict__", {})
                                stderr_path = str(proc_attrs.get("_bt_stderr_path") or "").strip()
                                if stderr_path:
                                    stderr = _read_file_tail(Path(stderr_path), limit=500)
                            inst["status"] = "error"
                            inst["error"] = stderr or f"Process exit code: {proc.returncode}"
                        else:
                            inst["status"] = "stopped"
                            inst["error"] = None
                        inst["pid"] = None
                        if service_execution and proc.returncode == 0:
                            _clear_service_execution_metadata(inst)
                        now = instance_timestamp()
                        inst["stopped_at"] = now
                        clear_server_runtime_launch_observation(inst)
                        normalize_instance_metadata(
                            inst, instance_id=instance_id, now=now, touch=True
                        )
                        try:
                            runtime_dir = str(inst.get("runtime_dir") or "").strip()
                            strategy_dir = (
                                Path(runtime_dir).expanduser()
                                if runtime_dir
                                else resolve_strategy_dir(inst["strategy_id"])
                            )
                            inst["log_dir"] = find_latest_log_dir(strategy_dir)
                        except ValueError:
                            inst["log_dir"] = None
                        instances[instance_id] = inst
                        save_instances(instances)
            if not stale_callback:
                processes.pop(instance_id, None)
                stopping_instances.discard(instance_id)
        if not stale_callback and not service_execution:
            release_gateway_for_instance(instance_id)
