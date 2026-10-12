import {
  arrayFromUnknown,
  isRecord,
  nullableString,
  optionalBoolean,
  optionalNumber,
  stringArrayFromUnknown,
  stringFromUnknown,
} from './aiResearchValueAdapters'
import type {
  AIStrategyPaperTradingStart,
  AIStrategyPipelineSummary,
  AIStrategyPromotionAuditItem,
  AIStrategyQualityGateEvaluation,
  AIStrategyResearchIteration,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
  AIStrategyResearchTaskResponse,
} from '@/api/strategy'
import type { Strategy } from '@/types'
import type { StrategyUnit, TradingSnapshot, UnitStatusResponse, Workspace } from '@/types/workspace'

export function useAIResearchRunRecordAdapters({
  minPaperTradingDays,
  runtimeAssetSpecsPayload,
  runtimeEnvironmentPayload,
  bestIterationPayloadForRecord,
  bestStrategyFromRunRecord,
  fallbackSnapshotStrategyId,
  iterationStrategyPayload,
  iterationUnitPayload,
  iterationRunResultPayload,
  iterationUnitStatusPayload,
  validationWindowFromUnknown,
  promotionAuditFromPayload,
  hydrateLiveHandoffFromRunRecord,
  liveTradingPreparedAtFromPipeline,
}: {
  minPaperTradingDays: number
  runtimeAssetSpecsPayload: (record: AIStrategyResearchRunRecord | null | undefined, handoff?: Record<string, unknown> | null) => Record<string, unknown>
  runtimeEnvironmentPayload: (record: AIStrategyResearchRunRecord | null | undefined, handoff?: Record<string, unknown> | null) => Record<string, unknown>
  bestIterationPayloadForRecord: (record: AIStrategyResearchRunRecord) => Record<string, unknown> | null
  bestStrategyFromRunRecord: (record: AIStrategyResearchRunRecord) => Strategy | null
  fallbackSnapshotStrategyId: (record: AIStrategyResearchRunRecord) => string
  iterationStrategyPayload: (payload: Record<string, unknown>) => Record<string, unknown>
  iterationUnitPayload: (payload: Record<string, unknown>) => Record<string, unknown>
  iterationRunResultPayload: (payload: Record<string, unknown>) => Record<string, unknown>
  iterationUnitStatusPayload: (payload: Record<string, unknown>) => Record<string, unknown>
  validationWindowFromUnknown: (value: unknown) => Record<string, string> | null
  promotionAuditFromPayload: (payload: unknown) => AIStrategyPromotionAuditItem[]
  hydrateLiveHandoffFromRunRecord: (record: AIStrategyResearchRunRecord) => void
  liveTradingPreparedAtFromPipeline: (pipeline: AIStrategyPipelineSummary | null | undefined) => string
}) {

  function workspaceFromResearchRunRecord(record: AIStrategyResearchRunRecord): Workspace {
    return {
      id: record.research_workspace_id,
      user_id: '',
      name: `AI投研 - ${record.symbol}`,
      description: null,
      workspace_type: 'research',
      settings: { ai_research: { runs: [record] } },
      trading_config: {},
      unit_count: 0,
      completed_count: record.iteration_count,
      status: 'completed',
      created_at: record.started_at,
      updated_at: record.completed_at,
    }
  }

  function researchResultFromRunRecord(
    record: AIStrategyResearchRunRecord
  ): AIStrategyResearchRunResponse {
    const iterations = researchIterationsFromRunRecord(record)
    const snapshotBestStrategy = bestStrategyFromRunRecord(record)
    return {
      run_id: record.run_id,
      status: record.status,
      achieved: record.achieved,
      target_sharpe: record.target_sharpe,
      started_at: record.started_at,
      completed_at: record.completed_at,
      best_iteration: record.best_iteration,
      best_quality_score: record.best_quality_score,
      best_quality_gate_evaluations: record.best_quality_gate_evaluations ?? [],
      best_diagnostics: record.best_diagnostics ?? {},
      best_metrics: record.best_metrics ?? {},
      research_workspace: workspaceFromResearchRunRecord(record),
      iterations,
      best_strategy: snapshotBestStrategy?.code?.trim() ? snapshotBestStrategy : null,
      paper_trading: paperTradingFromRunRecord(record),
      paper_monitoring_plan: record.paper_monitoring_plan ?? [],
      pipeline: record.pipeline,
      promotion_audit: promotionAuditFromPayload(record.promotion_audit),
      run_record: record,
      next_actions: record.next_actions ?? [],
      message: 'AI research result restored from run history',
    }
  }

  function researchResultFromTaskSummary(
    task: AIStrategyResearchTaskResponse
  ): AIStrategyResearchRunResponse | null {
    if (!task.run_id || !task.research_workspace_id) return null
    const request: Record<string, unknown> = isRecord(task.request_snapshot)
      ? task.request_snapshot
      : {}
    const latestIteration = isRecord(task.latest_iteration) ? task.latest_iteration : null
    const bestIterationPayload = isRecord(task.best_iteration_payload)
      ? task.best_iteration_payload
      : null
    const taskIterations: Record<string, unknown>[] = []
    const appendTaskIteration = (payload: Record<string, unknown> | null) => {
      if (!payload) return
      const iteration = optionalNumber(payload.iteration)
      if (
        iteration !== null
        && taskIterations.some(item => optionalNumber(item.iteration) === iteration)
      ) {
        return
      }
      taskIterations.push(payload)
    }
    appendTaskIteration(bestIterationPayload)
    appendTaskIteration(latestIteration)
    const bestMetrics = isRecord(task.best_metrics) ? task.best_metrics : {}
    const bestSharpe = optionalNumber(task.best_sharpe)
      ?? optionalNumber(bestMetrics.sharpe_ratio)
      ?? optionalNumber(bestMetrics.sharpe)
      ?? optionalNumber(latestIteration?.sharpe_ratio)
      ?? optionalNumber(latestIteration?.sharpe)
      ?? 0
    const bestIteration = optionalNumber(task.best_iteration)
      ?? optionalNumber(bestIterationPayload?.iteration)
      ?? optionalNumber(latestIteration?.iteration)
      ?? optionalNumber(task.current_iteration)
      ?? null
    const achieved = optionalBoolean(
      task.achieved,
      Boolean(task.paper_trading_started && String(task.status || '').toLowerCase() === 'completed')
    )
    const runStatus = String(
      task.current_stage === 'interrupted'
        ? 'interrupted'
        : task.run_status || (achieved ? 'achieved' : task.status || 'completed')
    )
    const targetSharpe = optionalNumber(task.target_sharpe) ?? optionalNumber(request.target_sharpe) ?? 0
    const paperHandoff = isRecord(task.paper_handoff) ? task.paper_handoff : {}
    const bestDiagnostics = isRecord(task.best_diagnostics) ? task.best_diagnostics : {}
    const assetSpecs = isRecord(task.asset_specs) && Object.keys(task.asset_specs).length
      ? task.asset_specs as Record<string, Record<string, unknown>>
      : isRecord(paperHandoff.asset_specs)
        ? paperHandoff.asset_specs as Record<string, Record<string, unknown>>
        : {}
    const backtestEnvironment = isRecord(task.backtest_environment)
      && Object.keys(task.backtest_environment).length
      ? task.backtest_environment
      : isRecord(paperHandoff.backtest_environment)
        ? paperHandoff.backtest_environment
        : {}
    const taskPipeline = task.pipeline ?? {
      current_stage: task.current_stage || 'completed',
      status: task.run_status || task.status || 'completed',
      progress: task.progress ?? 100,
      ready_for_live: Boolean(task.paper_review_ready_for_live),
      steps: [],
    }
    const liveWorkspaceId = task.live_workspace_id ?? taskPipeline.live_workspace_id ?? null
    const liveWorkspaceName = task.live_workspace_name ?? null
    const liveUnitId = task.live_unit_id ?? taskPipeline.live_unit_id ?? null
    const liveTradingPrepared = Boolean(
      task.live_trading_prepared
      || taskPipeline.live_trading_prepared
      || taskPipeline.current_stage === 'live_trading_prepare'
    )
    const liveTradingPreparedAt = task.live_trading_prepared_at
      ?? taskPipeline.live_trading_prepared_at
      ?? liveTradingPreparedAtFromPipeline(taskPipeline)
      ?? null
    const taskContinuationContext = isRecord(task.continuation_context)
      ? { ...task.continuation_context }
      : {}
    const requestContinuationContext = isRecord(request.continuation_context)
      ? { ...request.continuation_context }
      : {}
    const continuationContext = Object.keys(taskContinuationContext).length
      ? taskContinuationContext
      : requestContinuationContext
    const record: AIStrategyResearchRunRecord = {
      run_id: task.run_id,
      prompt: stringFromUnknown(request.prompt),
      symbol: stringFromUnknown(request.symbol),
      symbol_name: stringFromUnknown(request.symbol_name, stringFromUnknown(request.symbol)),
      timeframe: stringFromUnknown(request.timeframe, '1d'),
      timeframe_n: optionalNumber(request.timeframe_n) ?? 1,
      start_date: stringFromUnknown(request.start_date) || null,
      end_date: stringFromUnknown(request.end_date) || null,
      initial_cash:
        optionalNumber(backtestEnvironment.initial_cash)
        ?? optionalNumber(request.initial_cash)
        ?? undefined,
      commission:
        optionalNumber(backtestEnvironment.commission)
        ?? optionalNumber(request.commission)
        ?? undefined,
      annual_days:
        optionalNumber(backtestEnvironment.annual_days)
        ?? optionalNumber(request.annual_days)
        ?? undefined,
      calc_method:
        stringFromUnknown(backtestEnvironment.calc_method, stringFromUnknown(request.calc_method))
        || undefined,
      weight_mode:
        stringFromUnknown(backtestEnvironment.weight_mode, stringFromUnknown(request.weight_mode))
        || undefined,
      group_name: stringFromUnknown(request.group_name) || undefined,
      asset_specs: assetSpecs,
      backtest_environment: backtestEnvironment,
      status: runStatus,
      achieved,
      target_sharpe: targetSharpe,
      quality_gates: {
        target_sharpe: targetSharpe,
        min_total_trades: optionalNumber(request.min_total_trades) ?? 0,
        max_drawdown_limit: optionalNumber(request.max_drawdown_limit),
        min_total_return: optionalNumber(request.min_total_return),
        min_annual_return: optionalNumber(request.min_annual_return),
        min_win_rate: optionalNumber(request.min_win_rate),
        out_of_sample_validation: optionalBoolean(request.out_of_sample_validation, true),
        require_out_of_sample_validation: optionalBoolean(
          request.require_out_of_sample_validation,
          false
        ),
        out_of_sample_ratio: optionalNumber(request.out_of_sample_ratio) ?? 0.25,
        min_out_of_sample_sharpe: optionalNumber(request.min_out_of_sample_sharpe),
        min_out_of_sample_trades: optionalNumber(request.min_out_of_sample_trades),
        robustness_validation: optionalBoolean(request.robustness_validation, true),
        require_robustness_validation: optionalBoolean(
          request.require_robustness_validation,
          true
        ),
        robustness_methods: request.robustness_methods ?? ['monte_carlo'],
        min_robustness_score: optionalNumber(request.min_robustness_score) ?? 55,
        robustness_monte_carlo_iterations:
          optionalNumber(request.robustness_monte_carlo_iterations) ?? 300,
        robustness_random_seed: optionalNumber(request.robustness_random_seed),
        min_paper_trading_days:
          optionalNumber(request.min_paper_trading_days) ?? minPaperTradingDays,
      },
      min_total_trades: optionalNumber(request.min_total_trades) ?? 0,
      max_iterations: optionalNumber(task.max_iterations) ?? optionalNumber(request.max_iterations) ?? 0,
      iteration_count: Math.max(
        optionalNumber(task.iteration_count) ?? 0,
        taskIterations.length,
        latestIteration ? 1 : 0
      ),
      best_iteration: bestIteration,
      best_sharpe: bestSharpe,
      best_quality_score: optionalNumber(task.best_quality_score) ?? 0,
      best_quality_gate_evaluations: task.best_quality_gate_evaluations ?? [],
      best_diagnostics: bestDiagnostics,
      best_metrics: bestMetrics,
      best_strategy_id: task.best_strategy_id ?? null,
      best_strategy_name: task.best_strategy_name ?? null,
      research_workspace_id: task.research_workspace_id,
      mandate_id: (task.mandate_id ?? stringFromUnknown(request.mandate_id)) || null,
      seed_strategy_id: stringFromUnknown(request.seed_strategy_id) || null,
      continued_from_run_id: stringFromUnknown(
        task.continued_from_run_id,
        stringFromUnknown(request.continue_from_run_id)
      ) || null,
      continuation_source: stringFromUnknown(
        task.continuation_source,
        stringFromUnknown(continuationContext.source)
      ) || null,
      continuation_context: continuationContext,
      paper_workspace_id: task.paper_workspace_id ?? null,
      paper_workspace_name: stringFromUnknown(
        task.paper_workspace_name,
        stringFromUnknown(paperHandoff.paper_workspace_name, stringFromUnknown(request.paper_workspace_name))
      ) || null,
      paper_unit_id: task.paper_unit_id ?? null,
      paper_trading_started: Boolean(task.paper_trading_started),
      paper_monitoring_plan: task.paper_monitoring_plan ?? [],
      paper_handoff: paperHandoff,
      paper_review_status: task.paper_review_status ?? null,
      paper_review_ready_for_live: Boolean(task.paper_review_ready_for_live),
      paper_reviewed_at: task.paper_reviewed_at ?? null,
      paper_review_evaluations: task.paper_review_evaluations ?? [],
      paper_review_next_actions: task.paper_review_next_actions ?? [],
      live_readiness_checklist: task.live_readiness_checklist ?? [],
      live_readiness_expires_at: task.live_readiness_expires_at ?? null,
      live_handoff: task.live_handoff ?? null,
      live_handoff_approval: task.live_handoff_approval ?? null,
      live_workspace_id: liveWorkspaceId,
      live_workspace_name: liveWorkspaceName,
      live_unit_id: liveUnitId,
      live_trading_prepared: liveTradingPrepared,
      live_trading_prepared_at: liveTradingPreparedAt,
      pipeline: taskPipeline,
      promotion_audit: promotionAuditFromPayload(task.promotion_audit),
      next_actions: task.next_actions ?? [],
      started_at: task.started_at ?? task.submitted_at,
      completed_at: task.completed_at ?? task.started_at ?? task.submitted_at,
      iterations: taskIterations,
    }
    hydrateLiveHandoffFromRunRecord(record)
    return {
      ...researchResultFromRunRecord(record),
      message: 'AI research result restored from task summary',
    }
  }

  function researchIterationsFromRunRecord(
    record: AIStrategyResearchRunRecord
  ): AIStrategyResearchIteration[] {
    return (record.iterations || [])
      .filter(isRecord)
      .map((payload, index) => researchIterationFromRunRecord(record, payload, index + 1))
  }

  function researchIterationFromRunRecord(
    record: AIStrategyResearchRunRecord,
    payload: Record<string, unknown>,
    fallbackIteration: number
  ): AIStrategyResearchIteration {
    const iteration = Math.max(Math.trunc(optionalNumber(payload.iteration) ?? fallbackIteration), 1)
    const metrics = isRecord(payload.metrics) ? payload.metrics : {}
    const strategy = strategyFromIterationRecord(record, payload, iteration)
    const unit = unitFromIterationRecord(record, payload, strategy, metrics)
    const runResult = iterationRunResultPayload(payload)
    const runStatus = stringFromUnknown(
      payload.run_status ?? runResult.status ?? unit.run_status,
      'completed'
    )
    const taskId = nullableString(payload.task_id)
      ?? nullableString(runResult.task_id)
      ?? unit.last_task_id
    return {
      iteration,
      strategy,
      unit,
      run_result: {
        unit_id: unit.id,
        task_id: taskId,
        status: runStatus,
      },
      unit_status: unitStatusFromIterationRecord(unit, payload, runStatus, taskId, metrics),
      metrics,
      sharpe_ratio: optionalNumber(payload.sharpe_ratio) ?? metricFromPayload(metrics, 'sharpe_ratio', 'sharpe') ?? 0,
      total_trades: optionalNumber(payload.total_trades) ?? metricFromPayload(metrics, 'total_trades', 'trades') ?? 0,
      validation_status: nullableString(payload.validation_status),
      validation_window: validationWindowFromUnknown(payload.validation_window),
      validation_metrics: isRecord(payload.validation_metrics) ? payload.validation_metrics : {},
      validation_gate_evaluations: arrayFromUnknown<AIStrategyQualityGateEvaluation>(
        payload.validation_gate_evaluations
      ),
      validation_failures: stringArrayFromUnknown(payload.validation_failures),
      validation_failure_reason: nullableString(payload.validation_failure_reason),
      quality_score: optionalNumber(payload.quality_score) ?? record.best_quality_score ?? 0,
      quality_gate_evaluations: arrayFromUnknown<AIStrategyQualityGateEvaluation>(
        payload.quality_gate_evaluations
      ),
      passed: Boolean(payload.passed),
      failure_reason: nullableString(payload.failure_reason),
      quality_gate_failures: stringArrayFromUnknown(payload.quality_gate_failures),
      diagnostics: isRecord(payload.diagnostics)
        ? payload.diagnostics as AIStrategyResearchIteration['diagnostics']
        : {},
      improvement_plan: stringArrayFromUnknown(payload.improvement_plan),
      improvement_notes: stringArrayFromUnknown(payload.improvement_notes),
      next_actions: stringArrayFromUnknown(payload.next_actions),
    }
  }

  function strategyFromIterationRecord(
    record: AIStrategyResearchRunRecord,
    payload: Record<string, unknown>,
    iteration: number
  ): Strategy {
    const snapshot = iterationUnitPayload(payload)
    const strategySnapshot = iterationStrategyPayload(payload)
    const strategyId = stringFromUnknown(
      strategySnapshot.id ?? payload.strategy_id,
      record.best_strategy_id || fallbackSnapshotStrategyId(record)
    )
    const strategyName = stringFromUnknown(
      strategySnapshot.name ?? payload.strategy_name,
      record.best_strategy_name || `AI策略 第${iteration}轮`
    )
    const diagnostics = isRecord(payload.diagnostics) ? payload.diagnostics : {}
    return {
      id: strategyId,
      user_id: '',
      name: strategyName,
      description: stringFromUnknown(strategySnapshot.description, stringFromUnknown(diagnostics.summary, record.prompt)),
      code: stringFromUnknown(strategySnapshot.code, stringFromUnknown(payload.strategy_code, stringFromUnknown(payload.code, ''))),
      params: isRecord(strategySnapshot.params)
        ? strategySnapshot.params as Strategy['params']
        : isRecord(snapshot.params) ? snapshot.params as Strategy['params'] : {},
      category: stringFromUnknown(strategySnapshot.category, stringFromUnknown(snapshot.category, 'custom')),
      created_at: stringFromUnknown(strategySnapshot.created_at, record.started_at),
      updated_at: stringFromUnknown(strategySnapshot.updated_at, record.completed_at),
    }
  }

  function paperTradingFromRunRecord(
    record: AIStrategyResearchRunRecord
  ): AIStrategyPaperTradingStart | null {
    if (!record.paper_trading_started || !record.paper_workspace_id || !record.paper_unit_id) {
      return null
    }
    const handoff = isRecord(record.paper_handoff) ? record.paper_handoff : {}
    const paperUnit = paperUnitFromRunRecord(record, handoff)
    const runStatus = paperUnit.run_status
    const taskId = paperUnit.last_task_id
    return {
      workspace: paperWorkspaceFromRunRecord(record),
      unit: paperUnit,
      run_result: {
        unit_id: paperUnit.id,
        task_id: taskId,
        status: runStatus,
      },
      started: Boolean(record.paper_trading_started),
      handoff,
    }
  }

  function paperUnitFromRunRecord(
    record: AIStrategyResearchRunRecord,
    handoff: Record<string, unknown>
  ): StrategyUnit {
    const payload = bestIterationPayloadForRecord(record)
    if (!payload) return fallbackPaperUnitFromRunRecord(record, handoff)
    const iteration = Math.max(
      Math.trunc(optionalNumber(payload.iteration) ?? record.best_iteration ?? 1),
      1
    )
    const metrics = isRecord(payload.metrics) ? payload.metrics : record.best_metrics ?? {}
    const strategy = strategyFromIterationRecord(record, payload, iteration)
    const researchUnit = unitFromIterationRecord(record, payload, strategy, metrics)
    const runStatus = paperRunStatusFromHandoff(handoff, 'running')
    const taskId = nullableString(handoff.paper_task_id) ?? researchUnit.last_task_id
    return {
      ...researchUnit,
      id: record.paper_unit_id || researchUnit.id,
      workspace_id: record.paper_workspace_id || researchUnit.workspace_id,
      trading_mode: 'paper',
      data_config: {
        ...researchUnit.data_config,
        ai_research_run_id: record.run_id,
        ai_research_workspace_id: record.research_workspace_id,
      },
      unit_settings: {
        ...researchUnit.unit_settings,
        ai_research_handoff: handoff,
      },
      run_status: runStatus,
      last_task_id: taskId,
      gateway_config: Object.keys(researchUnit.gateway_config || {}).length
        ? researchUnit.gateway_config
        : isRecord(handoff.gateway_config)
          ? handoff.gateway_config as StrategyUnit['gateway_config']
          : {},
      updated_at: record.completed_at,
    }
  }

  function paperWorkspaceFromRunRecord(record: AIStrategyResearchRunRecord): Workspace {
    return {
      id: record.paper_workspace_id || '',
      user_id: '',
      name: record.paper_workspace_name || `AI模拟 - ${record.symbol}`,
      description: null,
      workspace_type: 'trading',
      settings: {
        ai_research_handoff: {
          last_handoff: isRecord(record.paper_handoff) ? record.paper_handoff : {},
        },
      },
      trading_config: {},
      unit_count: record.paper_unit_id ? 1 : 0,
      completed_count: 0,
      status: 'running',
      created_at: record.completed_at,
      updated_at: record.completed_at,
    }
  }

  function fallbackPaperUnitFromRunRecord(
    record: AIStrategyResearchRunRecord,
    handoff: Record<string, unknown>
  ): StrategyUnit {
    const assetSpecs = runtimeAssetSpecsPayload(record, handoff)
    const environment = runtimeEnvironmentPayload(record, handoff)
    const dataConfig: Record<string, unknown> = {
      symbol: record.symbol,
      ai_research_run_id: record.run_id,
      ai_research_workspace_id: record.research_workspace_id,
    }
    if (Object.keys(assetSpecs).length) dataConfig.asset_specs = assetSpecs
    if (Object.keys(environment).length) dataConfig.backtest_environment = environment
    const unitSettings: Record<string, unknown> = {
      ...environment,
      ai_research_handoff: handoff,
    }
    if (Object.keys(assetSpecs).length) unitSettings.asset_specs = assetSpecs
    return {
      id: record.paper_unit_id || `${record.run_id}-paper-unit`,
      workspace_id: record.paper_workspace_id || '',
      group_name: record.group_name || record.best_strategy_name || 'AI策略',
      strategy_id: record.best_strategy_id || null,
      strategy_name: record.best_strategy_name || 'AI策略',
      symbol: record.symbol,
      symbol_name: record.symbol_name || record.symbol,
      timeframe: record.timeframe,
      timeframe_n: record.timeframe_n,
      category: 'custom',
      sort_order: 0,
      data_config: dataConfig,
      unit_settings: unitSettings,
      params: {},
      optimization_config: {},
      trading_mode: 'paper',
      gateway_config: isRecord(handoff.gateway_config)
        ? handoff.gateway_config as StrategyUnit['gateway_config']
        : {},
      lock_trading: false,
      lock_running: false,
      trading_instance_id: null,
      trading_snapshot: emptyTradingSnapshot('paper'),
      run_status: paperRunStatusFromHandoff(handoff, 'running'),
      run_count: 1,
      last_run_time: null,
      last_task_id: nullableString(handoff.paper_task_id),
      last_optimization_task_id: null,
      bar_count: null,
      metrics_snapshot: record.best_metrics ?? {},
      created_at: record.started_at,
      updated_at: record.completed_at,
    }
  }

  function paperRunStatusFromHandoff(
    handoff: Record<string, unknown>,
    fallback: StrategyUnit['run_status']
  ): StrategyUnit['run_status'] {
    const status = stringFromUnknown(handoff.paper_run_status, fallback)
    return ['idle', 'queued', 'running', 'completed', 'failed', 'cancelled', 'timeout'].includes(status)
      ? status as StrategyUnit['run_status']
      : fallback
  }

  function unitFromIterationRecord(
    record: AIStrategyResearchRunRecord,
    payload: Record<string, unknown>,
    strategy: Strategy,
    metrics: Record<string, unknown>
  ): StrategyUnit {
    const snapshot = iterationUnitPayload(payload)
    const runResult = iterationRunResultPayload(payload)
    const runStatus = stringFromUnknown(
      payload.run_status ?? runResult.status ?? snapshot.run_status,
      'completed'
    ) as StrategyUnit['run_status']
    const taskId = nullableString(payload.task_id)
      ?? nullableString(runResult.task_id)
      ?? nullableString(snapshot.last_task_id)
    return {
      id: stringFromUnknown(
        payload.unit_id ?? runResult.unit_id,
        stringFromUnknown(snapshot.id, `${record.run_id}-unit`)
      ),
      workspace_id: stringFromUnknown(snapshot.workspace_id, record.research_workspace_id),
      group_name: stringFromUnknown(snapshot.group_name, strategy.name),
      strategy_id: strategy.id,
      strategy_name: strategy.name,
      symbol: stringFromUnknown(snapshot.symbol, record.symbol),
      symbol_name: stringFromUnknown(snapshot.symbol_name, record.symbol_name || record.symbol),
      timeframe: stringFromUnknown(snapshot.timeframe, record.timeframe),
      timeframe_n: optionalNumber(snapshot.timeframe_n) ?? record.timeframe_n,
      category: stringFromUnknown(snapshot.category, strategy.category),
      sort_order: 0,
      data_config: isRecord(snapshot.data_config) ? snapshot.data_config : {},
      unit_settings: isRecord(snapshot.unit_settings) ? snapshot.unit_settings : {},
      params: isRecord(snapshot.params) ? snapshot.params : {},
      optimization_config: isRecord(snapshot.optimization_config) ? snapshot.optimization_config : {},
      trading_mode: unitTradingMode(snapshot),
      gateway_config: isRecord(snapshot.gateway_config)
        ? snapshot.gateway_config as StrategyUnit['gateway_config']
        : {},
      lock_trading: Boolean(snapshot.lock_trading),
      lock_running: Boolean(snapshot.lock_running),
      trading_instance_id: nullableString(snapshot.trading_instance_id),
      trading_snapshot: emptyTradingSnapshot(unitTradingMode(snapshot)),
      run_status: runStatus,
      run_count: optionalNumber(snapshot.run_count) ?? 1,
      last_run_time: optionalNumber(snapshot.last_run_time),
      last_task_id: taskId,
      last_optimization_task_id: nullableString(snapshot.last_optimization_task_id),
      bar_count: optionalNumber(snapshot.bar_count),
      metrics_snapshot: metrics,
      created_at: record.started_at,
      updated_at: record.completed_at,
    }
  }

  function unitStatusFromIterationRecord(
    unit: StrategyUnit,
    payload: Record<string, unknown>,
    runStatus: string,
    taskId: string | null,
    metrics: Record<string, unknown>
  ): UnitStatusResponse {
    const status = iterationUnitStatusPayload(payload)
    const statusRunStatus = stringFromUnknown(status.run_status, runStatus)
    const statusTaskId = nullableString(status.last_task_id) ?? taskId
    const statusMetrics = isRecord(status.metrics_snapshot) ? status.metrics_snapshot : metrics
    const tradingSnapshot = isRecord(status.trading_snapshot)
      ? {
          ...emptyTradingSnapshot(unit.trading_mode),
          ...status.trading_snapshot,
        } as TradingSnapshot
      : emptyTradingSnapshot(unit.trading_mode)
    return {
      id: stringFromUnknown(status.id, unit.id),
      run_status: statusRunStatus as UnitStatusResponse['run_status'],
      last_task_id: statusTaskId,
      metrics_snapshot: statusMetrics,
      run_progress: optionalNumber(status.run_progress),
      run_message: nullableString(status.run_message),
      run_count: optionalNumber(status.run_count) ?? unit.run_count,
      last_run_time: optionalNumber(status.last_run_time) ?? unit.last_run_time,
      bar_count: optionalNumber(status.bar_count) ?? unit.bar_count,
      trading_instance_id: nullableString(status.trading_instance_id) ?? unit.trading_instance_id,
      trading_snapshot: tradingSnapshot,
      trading_mode: stringFromUnknown(status.trading_mode, unit.trading_mode) as UnitStatusResponse['trading_mode'],
      lock_trading: optionalBoolean(status.lock_trading, unit.lock_trading),
      lock_running: optionalBoolean(status.lock_running, unit.lock_running),
      opt_status: nullableString(status.opt_status),
      opt_total: optionalNumber(status.opt_total),
      opt_completed: optionalNumber(status.opt_completed),
      opt_progress: optionalNumber(status.opt_progress),
      opt_elapsed_time: optionalNumber(status.opt_elapsed_time),
      opt_remaining_time: optionalNumber(status.opt_remaining_time),
    }
  }

  function metricFromPayload(payload: Record<string, unknown>, ...keys: string[]) {
    for (const key of keys) {
      const value = optionalNumber(payload[key])
      if (value !== null) return value
    }
    return null
  }

  function unitTradingMode(snapshot: Record<string, unknown>) {
    return stringFromUnknown(snapshot.trading_mode, 'paper') as StrategyUnit['trading_mode']
  }

  function emptyTradingSnapshot(mode: StrategyUnit['trading_mode']): TradingSnapshot {
    return {
      instance_id: null,
      instance_status: 'idle',
      mode,
      error: null,
      started_at: null,
      stopped_at: null,
      gateway_summary: null,
      long_position: 0,
      short_position: 0,
      today_pnl: null,
      position_pnl: null,
      latest_price: null,
      change_pct: null,
      long_market_value: null,
      short_market_value: null,
      leverage: null,
      cumulative_pnl: null,
      max_drawdown_rate: null,
      trading_day: null,
      updated_at: null,
      detail_route: null,
      positions: [],
      trades: [],
    }
  }

  return {
    workspaceFromResearchRunRecord,
    researchResultFromRunRecord,
    researchResultFromTaskSummary,
    researchIterationsFromRunRecord,
    researchIterationFromRunRecord,
    strategyFromIterationRecord,
    paperTradingFromRunRecord,
    paperUnitFromRunRecord,
    paperWorkspaceFromRunRecord,
    fallbackPaperUnitFromRunRecord,
    paperRunStatusFromHandoff,
    unitFromIterationRecord,
    unitStatusFromIterationRecord,
    metricFromPayload,
    unitTradingMode,
    emptyTradingSnapshot,
  }
}
