"""Startup orchestration for workspace trading units."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from app.models.workspace import StrategyUnit

if TYPE_CHECKING:
    from app.services.live_trading.manager import LiveTradingManager
    from app.services.risk_gate_service import RiskGateService
    from app.services.trading_workspace_service import TradingWorkspaceService


class VerifyPaperRuntimeAnchor(Protocol):
    def __call__(
        self,
        anchor: Any,
        *,
        user_id: str,
        paper_workspace_id: str,
        paper_unit_id: str,
        unit: Any,
        workspace_settings: Mapping[str, Any] | None = None,
        require_runtime_snapshot: bool = True,
    ) -> bool: ...


class IssuePaperRuntimeAnchor(Protocol):
    def __call__(
        self,
        *,
        user_id: str,
        research_workspace_id: str,
        paper_workspace_id: str,
        paper_unit_id: str,
        run_id: str,
        unit: Any,
        workspace_settings: Mapping[str, Any] | None = None,
        include_runtime_snapshot: bool = True,
        runtime_digest_override: str | None = None,
    ) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class StartupDependencies:
    get_live_trading_manager: Callable[[], LiveTradingManager]
    risk_gate_service_factory: Callable[[], RiskGateService]
    logger: logging.Logger
    is_server_owned_ai_research_paper_runtime: Callable[[StrategyUnit], bool]
    is_server_owned_ai_research_live_handoff_unit: Callable[[StrategyUnit], bool]
    verify_ai_research_paper_runtime_anchor_for_unit: VerifyPaperRuntimeAnchor
    issue_ai_research_paper_runtime_anchor: IssuePaperRuntimeAnchor
    assert_ai_research_live_handoff_runtime_start_allowed: Callable[
        [StrategyUnit, str], Awaitable[bool]
    ]
    paper_runtime_anchor_field: str
    sync_trading_unit_runtime: Callable[[StrategyUnit, dict[str, Any]], Path]
    clear_runtime_logs_before_start: Callable[[Path], None]


async def start_units(
    self: TradingWorkspaceService,
    units: list[StrategyUnit],
    user_id: str,
    workspace_settings: dict[str, Any] | None = None,
    *,
    allow_server_owned_ai_research_live_handoff_start: bool = False,
    live_handoff_pre_start_validator: Callable[[], Awaitable[None]] | None = None,
    dependencies: StartupDependencies,
) -> list[dict[str, Any]]:
    get_live_trading_manager = dependencies.get_live_trading_manager
    RiskGateService = dependencies.risk_gate_service_factory
    logger = dependencies.logger
    is_server_owned_ai_research_paper_runtime = (
        dependencies.is_server_owned_ai_research_paper_runtime
    )
    is_server_owned_ai_research_live_handoff_unit = (
        dependencies.is_server_owned_ai_research_live_handoff_unit
    )
    verify_ai_research_paper_runtime_anchor_for_unit = (
        dependencies.verify_ai_research_paper_runtime_anchor_for_unit
    )
    issue_ai_research_paper_runtime_anchor = dependencies.issue_ai_research_paper_runtime_anchor
    assert_ai_research_live_handoff_runtime_start_allowed = (
        dependencies.assert_ai_research_live_handoff_runtime_start_allowed
    )
    AI_RESEARCH_PAPER_RUNTIME_ANCHOR_FIELD = dependencies.paper_runtime_anchor_field
    sync_trading_unit_runtime = dependencies.sync_trading_unit_runtime
    _clear_runtime_logs_before_start = dependencies.clear_runtime_logs_before_start
    manager = get_live_trading_manager()
    risk_gate_service = RiskGateService()
    results: list[dict[str, Any]] = []
    normalized_workspace_settings = dict(workspace_settings or {})
    gateway_failures: dict[str, str] = {}

    for unit in units:
        gateway_startup_key = self._gateway_startup_key(unit)
        try:
            if unit.lock_running:
                raise ValueError("该策略单元已锁定运行")
            if unit.lock_trading:
                raise ValueError("该策略单元已锁定交易")
            if not str(unit.strategy_id or "").strip():
                raise ValueError("策略单元缺少策略模板")
            server_attested_paper_runtime = is_server_owned_ai_research_paper_runtime(unit)
            server_attested_live_handoff = is_server_owned_ai_research_live_handoff_unit(unit)
            server_attested_paper_runtime_digest: str | None = None
            live_handoff_activation_token: str | None = None
            paper_runtime_anchor: dict[str, Any] | None = None
            # This is a pure, local preflight.  Run it before consuming a
            # server-only live-handoff capability or touching a manager so
            # an objectively unsafe unit is stopped at the first boundary.
            # Provenance/activation checks below still run before any
            # materialization or runtime side effect.
            risk_gate_service.assert_trading_unit_pre_run(
                unit,
                workspace_settings=normalized_workspace_settings,
            )
            if server_attested_paper_runtime:
                unit_settings = (
                    dict(unit.unit_settings or {}) if isinstance(unit.unit_settings, dict) else {}
                )
                raw_paper_runtime_anchor = unit_settings.get(AI_RESEARCH_PAPER_RUNTIME_ANCHOR_FIELD)
                if isinstance(raw_paper_runtime_anchor, dict):
                    paper_runtime_anchor = raw_paper_runtime_anchor
                if not verify_ai_research_paper_runtime_anchor_for_unit(
                    paper_runtime_anchor,
                    user_id=user_id,
                    paper_workspace_id=str(unit.workspace_id),
                    paper_unit_id=str(unit.id),
                    unit=unit,
                    workspace_settings=normalized_workspace_settings,
                    require_runtime_snapshot=False,
                ):
                    raise ValueError("AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID")
            if server_attested_live_handoff:
                if not allow_server_owned_ai_research_live_handoff_start:
                    raise ValueError("AI_RESEARCH_LIVE_HANDOFF_SERVER_ACTIVATION_REQUIRED")
                await assert_ai_research_live_handoff_runtime_start_allowed(unit, user_id)
                live_handoff_activation_token = manager.new_live_handoff_runtime_activation_token()

            instance = None
            self._refresh_unit_asset_specs_from_local(unit, None)
            runtime_dir = await asyncio.to_thread(
                sync_trading_unit_runtime,
                unit,
                normalized_workspace_settings,
            )
            if server_attested_paper_runtime:
                # The pre-sync check authorizes only the original expected
                # template/config. A strategy or workspace mutation can
                # race the public preflight before this directory copy, so
                # re-check the old signed expected digest after sync and
                # compare it to the actual isolated files before granting
                # the one-start manager capability.
                if not verify_ai_research_paper_runtime_anchor_for_unit(
                    paper_runtime_anchor,
                    user_id=user_id,
                    paper_workspace_id=str(unit.workspace_id),
                    paper_unit_id=str(unit.id),
                    unit=unit,
                    workspace_settings=normalized_workspace_settings,
                    require_runtime_snapshot=False,
                ):
                    raise ValueError("AI_RESEARCH_PAPER_RUNTIME_PROVENANCE_INVALID")
                assert isinstance(paper_runtime_anchor, dict)
                expected_runtime_digest = paper_runtime_anchor.get("runtime_digest")
                refreshed_anchor = issue_ai_research_paper_runtime_anchor(
                    user_id=user_id,
                    research_workspace_id=str(
                        paper_runtime_anchor.get("research_workspace_id") or ""
                    ),
                    paper_workspace_id=str(unit.workspace_id),
                    paper_unit_id=str(unit.id),
                    run_id=str(paper_runtime_anchor.get("run_id") or ""),
                    unit=unit,
                    workspace_settings=normalized_workspace_settings,
                    include_runtime_snapshot=True,
                    runtime_digest_override=(
                        expected_runtime_digest
                        if isinstance(expected_runtime_digest, str)
                        else None
                    ),
                )
                if (
                    refreshed_anchor is None
                    or refreshed_anchor.get("runtime_snapshot_digest") != expected_runtime_digest
                ):
                    raise ValueError("AI_RESEARCH_PAPER_RUNTIME_MATERIALIZATION_MISMATCH")
                unit.unit_settings = {
                    **unit_settings,
                    AI_RESEARCH_PAPER_RUNTIME_ANCHOR_FIELD: refreshed_anchor,
                }
                server_attested_paper_runtime_digest = str(
                    refreshed_anchor["runtime_snapshot_digest"]
                )
            if unit.trading_instance_id:
                # Instance-store access may scan runtime directories and
                # strategy templates.  During a batch launch that work is
                # repeated for every unit, so keep it off the ASGI event
                # loop just like the generated runtime files above.
                instance = await asyncio.to_thread(
                    manager.get_instance,
                    unit.trading_instance_id,
                    user_id=user_id,
                )
                if instance is not None:
                    existing_runtime_dir = str(instance.get("runtime_dir") or "").strip()
                    if existing_runtime_dir != str(runtime_dir):
                        await asyncio.to_thread(
                            manager.remove_instance,
                            unit.trading_instance_id,
                            user_id=user_id,
                        )
                        unit.trading_instance_id = None
                        instance = None
            if instance is None:
                # Keep the long-standing ordinary manager contract intact.
                # The owner/capability kwargs are required only where the
                # AI-research provenance boundary actually consumes them.
                add_instance_kwargs: dict[str, Any] = {
                    # ``add_instance`` has always been owner-scoped; keep
                    # that existing contract for ordinary workspace starts.
                    "user_id": user_id,
                    "runtime_dir": str(runtime_dir),
                }
                if server_attested_paper_runtime and server_attested_paper_runtime_digest:
                    add_instance_kwargs["server_attested_paper_runtime_digest"] = (
                        server_attested_paper_runtime_digest
                    )
                # Keep the new server-only live-handoff capability opt-in
                # for manager implementations.  Paper and ordinary
                # workspace starts must retain compatibility with the
                # existing manager contract; a real activation always
                # supplies a non-empty one-shot token below.
                if live_handoff_activation_token:
                    add_instance_kwargs["server_attested_live_handoff_activation_token"] = (
                        live_handoff_activation_token
                    )
                created = await asyncio.to_thread(
                    manager.add_instance,
                    str(unit.strategy_id),
                    self._build_instance_params(unit),
                    **add_instance_kwargs,
                )
                unit.trading_instance_id = str(created.get("id") or "")
                attest_managed_runtime = getattr(
                    manager,
                    "attest_managed_workspace_runtime_start",
                    None,
                )
                if callable(attest_managed_runtime) and not server_attested_live_handoff:
                    attest_managed_runtime(unit.trading_instance_id)
                instance = await asyncio.to_thread(
                    manager.get_instance,
                    unit.trading_instance_id,
                    user_id=user_id,
                )

            already_running = False
            started: Mapping[str, object]
            if instance is not None and str(instance.get("status") or "").lower() == "running":
                started = instance
                already_running = True
            else:
                known_gateway_failure = (
                    gateway_failures.get(gateway_startup_key)
                    if gateway_startup_key is not None
                    else None
                )
                if known_gateway_failure:
                    raise ValueError(
                        "同一网关配置已启动失败，跳过重复连接: " + known_gateway_failure
                    )
                await asyncio.to_thread(_clear_runtime_logs_before_start, runtime_dir)
                if server_attested_paper_runtime:
                    assert server_attested_paper_runtime_digest is not None
                    manager.attest_paper_runtime_start(
                        str(unit.trading_instance_id),
                        server_attested_paper_runtime_digest,
                    )
                if server_attested_live_handoff:
                    assert live_handoff_activation_token is not None
                    if live_handoff_pre_start_validator is None:
                        raise ValueError("AI_RESEARCH_LIVE_HANDOFF_SERVER_ACTIVATION_REQUIRED")
                    # Run this after isolated runtime materialization and
                    # immediately before the manager launch boundary.  It
                    # lets the research service re-observe the paper
                    # runtime's signed launch/metrics receipt after all
                    # slow file and gateway work, closing the final
                    # approval-to-spawn interval.
                    await live_handoff_pre_start_validator()
                    manager.attest_live_handoff_runtime_start(
                        str(unit.trading_instance_id),
                        live_handoff_activation_token,
                    )
                try:
                    start_instance_kwargs: dict[str, Any] = {}
                    if server_attested_paper_runtime or server_attested_live_handoff:
                        start_instance_kwargs["user_id"] = user_id
                    if live_handoff_activation_token:
                        start_instance_kwargs["server_attested_live_handoff_activation_token"] = (
                            live_handoff_activation_token
                        )
                    started = await manager.start_instance(
                        str(unit.trading_instance_id),
                        **start_instance_kwargs,
                    )
                except ValueError as exc:
                    if str(exc) != "Strategy is already running":
                        raise
                    refreshed = await asyncio.to_thread(
                        manager.get_instance, str(unit.trading_instance_id), user_id=user_id
                    )
                    if not refreshed or str(refreshed.get("status") or "").lower() != "running":
                        raise
                    started = refreshed
                    already_running = True

            self._sync_unit_contract_metadata_from_instance(unit, started)
            if self.normalize_trading_mode(unit.trading_mode) == "live":
                self._refresh_unit_asset_specs_from_manager(manager, unit, started)
            unit.run_status = "running"
            if not already_running:
                unit.run_count = int(unit.run_count or 0) + 1
            snapshot, metrics_snapshot, bar_count, elapsed_seconds = self._build_snapshot(
                unit, started, full_log=False
            )
            unit.trading_snapshot = snapshot
            if metrics_snapshot:
                unit.metrics_snapshot = metrics_snapshot
            if bar_count is not None:
                unit.bar_count = bar_count
            if elapsed_seconds is not None:
                unit.last_run_time = elapsed_seconds
            results.append(
                {
                    "unit_id": unit.id,
                    "task_id": unit.trading_instance_id,
                    "status": "running",
                    "already_running": already_running,
                }
            )
        except Exception as exc:
            logger.exception("Trading unit %s start failed", unit.id)
            if gateway_startup_key and self._is_gateway_startup_failure(exc):
                gateway_failures[gateway_startup_key] = str(exc)
            unit.run_status = "failed"
            unit.trading_snapshot = self.default_snapshot(
                unit=unit,
                instance_status="error",
                error=str(exc),
            )
            results.append(
                {
                    "unit_id": unit.id,
                    "task_id": None,
                    "status": "failed",
                    "error": str(exc),
                }
            )

    return results
