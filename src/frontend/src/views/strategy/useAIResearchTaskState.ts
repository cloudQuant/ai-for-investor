import { ref } from 'vue'
import type { MarketAssetType } from '@/api/marketData'
import type {
  AIStrategyPipelineSummary,
  AIStrategyPromotionAuditItem,
  AIStrategyResearchRunRequest,
  AIStrategyResearchTaskResponse,
} from '@/api/strategy'
import { isRecord, optionalBoolean, optionalNumber, stringArrayFromUnknown, stringFromUnknown } from './aiResearchValueAdapters'
import type { AIResearchAutoContinuationSource, AIResearchTaskFormState } from './aiResearchTaskTypes'

export interface AIResearchTaskStateOptions {
  aiResearchForm: AIResearchTaskFormState
  aiResearchTaskAutoContinuationSourceFromTask: (
    task: AIStrategyResearchTaskResponse
  ) => AIResearchAutoContinuationSource | null
  gatewayConfigJsonFromTaskSnapshot: (snapshot: Record<string, unknown>) => string
  aiResearchMarketDataAssetTypeFromDataConfig: (value: unknown) => '' | MarketAssetType
  resolvedAIResearchTaskBacktestEnvironment: (
    task: AIStrategyResearchTaskResponse,
    snapshot: Record<string, unknown>
  ) => Record<string, unknown> | null
  aiResearchTaskRestoredCommission: (
    task: AIStrategyResearchTaskResponse,
    snapshot: Record<string, unknown>
  ) => number | null
  aiResearchTaskUsesManualCommission: (
    task: AIStrategyResearchTaskResponse,
    snapshot: Record<string, unknown>
  ) => boolean
  promotionAuditFromPayload: (payload: unknown) => AIStrategyPromotionAuditItem[]
}

export function useAIResearchTaskState({
  aiResearchForm,
  aiResearchTaskAutoContinuationSourceFromTask,
  gatewayConfigJsonFromTaskSnapshot,
  aiResearchMarketDataAssetTypeFromDataConfig,
  resolvedAIResearchTaskBacktestEnvironment,
  aiResearchTaskRestoredCommission,
  aiResearchTaskUsesManualCommission,
  promotionAuditFromPayload,
}: AIResearchTaskStateOptions) {
  const aiResearchTaskId = ref('')
  const aiResearchTaskStatus = ref('')
  const aiResearchTaskStage = ref('')
  const aiResearchTaskProgress = ref(0)
  const aiResearchTaskIteration = ref<number | null>(null)
  const aiResearchBacktestTaskId = ref('')
  const aiResearchCancelledBacktestTaskId = ref('')
  const aiResearchTaskPaperWorkspaceId = ref('')
  const aiResearchTaskPaperUnitId = ref('')
  const aiResearchTaskPaperStarted = ref(false)
  const aiResearchTaskLiveWorkspaceId = ref('')
  const aiResearchTaskLiveUnitId = ref('')
  const aiResearchTaskLivePrepared = ref(false)
  const aiResearchTaskPipeline = ref<AIStrategyPipelineSummary | null>(null)
  const aiResearchTaskRequestSnapshot = ref<Record<string, unknown> | null>(null)
  const aiResearchTaskAutoContinuationSource = ref<AIResearchAutoContinuationSource | null>(null)
  const aiResearchTaskContinuedFromRunId = ref('')
  const aiResearchTaskContinuationSource = ref('')
  const aiResearchTaskContinuationContext = ref<Record<string, unknown>>({})
  const aiResearchTaskError = ref('')
  const aiResearchTaskMessage = ref('')
  const aiResearchTaskLatestIteration = ref<Record<string, unknown> | null>(null)
  const aiResearchTaskBestIteration = ref<Record<string, unknown> | null>(null)
  const aiResearchTaskAssetSpecs = ref<Record<string, Record<string, unknown>>>({})
  const aiResearchTaskBacktestEnvironment = ref<Record<string, unknown>>({})
  const aiResearchTaskPromotionAudit = ref<AIStrategyPromotionAuditItem[]>([])
  const aiResearchCancelling = ref(false)
  const aiResearchCancelRequested = ref(false)

  function isAIResearchTaskTerminal(task: AIStrategyResearchTaskResponse) {
    return ['completed', 'failed', 'cancelled'].includes(String(task.status || '').toLowerCase())
  }

  function isAIResearchTaskCancelled(task: AIStrategyResearchTaskResponse) {
    return String(task.status || '').toLowerCase() === 'cancelled'
  }

  function isRestorableAIResearchTask(task: AIStrategyResearchTaskResponse) {
    return isAIResearchTaskTerminal(task) && Boolean(task.result || task.run_id)
  }

  function boundedNumber(value: unknown, fallback: number, min: number, max: number) {
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) return fallback
    return Math.min(Math.max(parsed, min), max)
  }

  function aiResearchTaskPollTimeoutMs(
    payload?: AIStrategyResearchRunRequest,
    task?: AIStrategyResearchTaskResponse
  ) {
    const snapshot: Record<string, unknown> = isRecord(task?.request_snapshot)
      ? task.request_snapshot
      : {}
    const maxIterations = boundedNumber(
      payload?.max_iterations
        ?? task?.max_iterations
        ?? snapshot.max_iterations
        ?? aiResearchForm.max_iterations,
      3,
      1,
      8
    )
    const backtestTimeoutSeconds = boundedNumber(
      payload?.backtest_timeout_seconds ?? snapshot.backtest_timeout_seconds,
      600,
      1,
      3600
    )
    const outOfSampleValidation = payload?.out_of_sample_validation ?? snapshot.out_of_sample_validation
    const robustnessValidation = payload?.robustness_validation ?? snapshot.robustness_validation ?? false
    const validationFactor = 1
      + (outOfSampleValidation === false ? 0 : 1)
      + (robustnessValidation === false ? 0 : 1)
    const estimatedSeconds = maxIterations * validationFactor * backtestTimeoutSeconds + 240
    return boundedNumber(
      estimatedSeconds * 1000,
      10 * 60 * 1000,
      10 * 60 * 1000,
      8 * 60 * 60 * 1000
    )
  }

  function applyAIResearchTaskStatus(task: AIStrategyResearchTaskResponse) {
    const pipeline = task.pipeline ?? null
    const sameTask = aiResearchTaskId.value === task.task_id
    const hasTaskKey = (key: string) => Object.prototype.hasOwnProperty.call(task, key)
    aiResearchTaskId.value = task.task_id
    aiResearchTaskStatus.value = task.status
    aiResearchTaskStage.value = task.current_stage || task.status
    aiResearchTaskProgress.value = Number(task.progress || 0)
    aiResearchTaskIteration.value = task.current_iteration ?? task.iteration_count ?? null
    aiResearchBacktestTaskId.value = task.current_backtest_task_id || ''
    aiResearchCancelledBacktestTaskId.value = task.cancelled_backtest_task_id || ''
    aiResearchTaskPaperWorkspaceId.value = task.paper_workspace_id || ''
    aiResearchTaskPaperUnitId.value = task.paper_unit_id || ''
    aiResearchTaskPaperStarted.value = Boolean(task.paper_trading_started)
    aiResearchTaskLiveWorkspaceId.value = task.live_workspace_id || pipeline?.live_workspace_id || ''
    aiResearchTaskLiveUnitId.value = task.live_unit_id || pipeline?.live_unit_id || ''
    aiResearchTaskLivePrepared.value = Boolean(
      task.live_trading_prepared || pipeline?.live_trading_prepared
    )
    aiResearchTaskPipeline.value = pipeline
    if (hasTaskKey('continued_from_run_id') || !sameTask) {
      aiResearchTaskContinuedFromRunId.value = stringFromUnknown(task.continued_from_run_id)
    }
    if (hasTaskKey('continuation_source') || !sameTask) {
      aiResearchTaskContinuationSource.value = stringFromUnknown(task.continuation_source)
    }
    if (hasTaskKey('continuation_context') || !sameTask) {
      aiResearchTaskContinuationContext.value = isRecord(task.continuation_context)
        ? { ...task.continuation_context }
        : {}
    }
    if (isRecord(task.request_snapshot)) {
      aiResearchTaskRequestSnapshot.value = task.request_snapshot
    } else if (hasTaskKey('request_snapshot') || !sameTask) {
      aiResearchTaskRequestSnapshot.value = {}
    }
    if (hasTaskKey('request_explicit_fields') || !sameTask) {
      aiResearchTaskAutoContinuationSource.value = aiResearchTaskAutoContinuationSourceFromTask(task)
    }
    if (hasTaskKey('asset_specs') || !sameTask) {
      aiResearchTaskAssetSpecs.value = isRecord(task.asset_specs)
        ? task.asset_specs as Record<string, Record<string, unknown>>
        : {}
    }
    if (hasTaskKey('backtest_environment') || !sameTask) {
      aiResearchTaskBacktestEnvironment.value = isRecord(task.backtest_environment)
        ? task.backtest_environment
        : {}
    }
    if (hasTaskKey('promotion_audit') || !sameTask) {
      aiResearchTaskPromotionAudit.value = promotionAuditFromPayload(task.promotion_audit)
    }
    aiResearchTaskError.value = aiResearchTaskFailureMessage(task)
    aiResearchTaskMessage.value = String(task.message || '').trim()
    aiResearchTaskLatestIteration.value = task.latest_iteration ?? null
    if (hasTaskKey('best_iteration_payload') || !sameTask) {
      aiResearchTaskBestIteration.value = isRecord(task.best_iteration_payload)
        ? task.best_iteration_payload
        : null
    }
  }

  function applyAIResearchTaskSnapshotToForm(task: AIStrategyResearchTaskResponse) {
    const snapshot = isRecord(task.request_snapshot) ? task.request_snapshot : null
    if (!snapshot) return
    const environment = resolvedAIResearchTaskBacktestEnvironment(task, snapshot)
    const prompt = stringFromUnknown(snapshot.prompt)
    const symbol = stringFromUnknown(snapshot.symbol)
    const symbolName = stringFromUnknown(snapshot.symbol_name)
    const timeframe = stringFromUnknown(snapshot.timeframe)
    const startDate = stringFromUnknown(snapshot.start_date)
    const endDate = stringFromUnknown(snapshot.end_date)
    if (prompt) aiResearchForm.prompt = prompt
    aiResearchForm.workflow_mode = snapshot.workflow_mode === 'prompt' ? 'prompt' : 'auto'
    if (symbol) aiResearchForm.symbol = symbol
    if (symbolName || snapshot.symbol_name !== undefined) aiResearchForm.symbol_name = symbolName
    aiResearchForm.market_data_asset_type = aiResearchMarketDataAssetTypeFromDataConfig(
      snapshot.data_config,
    )
    if (timeframe) aiResearchForm.timeframe = timeframe
    aiResearchForm.timeframe_n = optionalNumber(snapshot.timeframe_n) ?? aiResearchForm.timeframe_n
    aiResearchForm.start_date = startDate
    aiResearchForm.end_date = endDate
    aiResearchForm.knowledge_base_id = stringFromUnknown(snapshot.knowledge_base_id)
    aiResearchForm.thinking_mode = optionalBoolean(snapshot.thinking_mode, false)
    aiResearchForm.target_sharpe = optionalNumber(snapshot.target_sharpe) ?? aiResearchForm.target_sharpe
    aiResearchForm.min_total_trades =
      optionalNumber(snapshot.min_total_trades) ?? aiResearchForm.min_total_trades
    aiResearchForm.max_iterations = optionalNumber(snapshot.max_iterations) ?? aiResearchForm.max_iterations
    aiResearchForm.initial_cash =
      (environment ? optionalNumber(environment.initial_cash) : null)
      ?? optionalNumber(snapshot.initial_cash)
      ?? aiResearchForm.initial_cash
    const commission = aiResearchTaskRestoredCommission(task, snapshot)
    if (commission !== null) {
      aiResearchForm.commission = commission
      aiResearchForm.use_manual_commission = aiResearchTaskUsesManualCommission(task, snapshot)
    } else {
      aiResearchForm.use_manual_commission = false
    }
    aiResearchForm.annual_days =
      (environment ? optionalNumber(environment.annual_days) : null)
      ?? optionalNumber(snapshot.annual_days)
      ?? aiResearchForm.annual_days
    aiResearchForm.calc_method = environment
      ? stringFromUnknown(environment.calc_method, stringFromUnknown(snapshot.calc_method, aiResearchForm.calc_method))
      : stringFromUnknown(snapshot.calc_method, aiResearchForm.calc_method)
    aiResearchForm.weight_mode = environment
      ? stringFromUnknown(environment.weight_mode, stringFromUnknown(snapshot.weight_mode, aiResearchForm.weight_mode))
      : stringFromUnknown(snapshot.weight_mode, aiResearchForm.weight_mode)
    aiResearchForm.group_name = stringFromUnknown(snapshot.group_name)
    aiResearchForm.backtest_timeout_seconds =
      optionalNumber(snapshot.backtest_timeout_seconds) ?? aiResearchForm.backtest_timeout_seconds
    aiResearchForm.poll_interval_seconds =
      optionalNumber(snapshot.poll_interval_seconds) ?? aiResearchForm.poll_interval_seconds
    aiResearchForm.research_workspace_id = stringFromUnknown(snapshot.research_workspace_id)
    aiResearchForm.trading_workspace_id = stringFromUnknown(snapshot.trading_workspace_id)
    aiResearchForm.seed_strategy_id = stringFromUnknown(snapshot.seed_strategy_id)
    const taskContinuationContext = isRecord(task.continuation_context)
      ? task.continuation_context
      : null
    const snapshotContinuationContext = isRecord(snapshot.continuation_context)
      ? snapshot.continuation_context
      : null
    const continuationContext = taskContinuationContext ?? snapshotContinuationContext
    const continuationRunId = continuationContext
      ? stringFromUnknown(continuationContext.run_id)
      : ''
    const continuationSource = continuationContext
      ? stringFromUnknown(continuationContext.source)
      : ''
    aiResearchForm.continue_from_run_id =
      stringFromUnknown(task.continued_from_run_id, stringFromUnknown(snapshot.continue_from_run_id))
      || continuationRunId
    aiResearchForm.continuation_source =
      stringFromUnknown(task.continuation_source, continuationSource)
    aiResearchForm.start_paper_trading = optionalBoolean(snapshot.start_paper_trading, true)
    aiResearchForm.paper_workspace_name = stringFromUnknown(snapshot.paper_workspace_name)
    if (snapshot.gateway_config !== undefined) {
      aiResearchForm.gateway_config_json = gatewayConfigJsonFromTaskSnapshot(snapshot)
    }
    const maxDrawdownLimit = optionalNumber(snapshot.max_drawdown_limit)
    aiResearchForm.use_max_drawdown_limit = maxDrawdownLimit !== null
    aiResearchForm.max_drawdown_limit = maxDrawdownLimit ?? aiResearchForm.max_drawdown_limit
    const minTotalReturn = optionalNumber(snapshot.min_total_return)
    aiResearchForm.use_min_total_return = minTotalReturn !== null
    aiResearchForm.min_total_return = minTotalReturn ?? aiResearchForm.min_total_return
    const minAnnualReturn = optionalNumber(snapshot.min_annual_return)
    aiResearchForm.use_min_annual_return = minAnnualReturn !== null
    aiResearchForm.min_annual_return = minAnnualReturn ?? aiResearchForm.min_annual_return
    const minWinRate = optionalNumber(snapshot.min_win_rate)
    aiResearchForm.use_min_win_rate = minWinRate !== null
    aiResearchForm.min_win_rate = minWinRate ?? aiResearchForm.min_win_rate
    aiResearchForm.out_of_sample_validation =
      optionalBoolean(snapshot.out_of_sample_validation, aiResearchForm.out_of_sample_validation)
    aiResearchForm.require_out_of_sample_validation = optionalBoolean(
      snapshot.require_out_of_sample_validation,
      false
    )
    const outOfSampleRatio = optionalNumber(snapshot.out_of_sample_ratio)
    if (outOfSampleRatio !== null) aiResearchForm.out_of_sample_ratio_pct = outOfSampleRatio * 100
    const minOutOfSampleSharpe = optionalNumber(snapshot.min_out_of_sample_sharpe)
    aiResearchForm.use_min_out_of_sample_sharpe = minOutOfSampleSharpe !== null
    aiResearchForm.min_out_of_sample_sharpe =
      minOutOfSampleSharpe ?? aiResearchForm.min_out_of_sample_sharpe
    const minOutOfSampleTrades = optionalNumber(snapshot.min_out_of_sample_trades)
    aiResearchForm.use_min_out_of_sample_trades = minOutOfSampleTrades !== null
    aiResearchForm.min_out_of_sample_trades =
      minOutOfSampleTrades ?? aiResearchForm.min_out_of_sample_trades
    aiResearchForm.robustness_validation =
      optionalBoolean(snapshot.robustness_validation, aiResearchForm.robustness_validation)
    aiResearchForm.require_robustness_validation = optionalBoolean(
      snapshot.require_robustness_validation,
      aiResearchForm.require_robustness_validation
    )
    const robustnessMethods = stringArrayFromUnknown(snapshot.robustness_methods)
    aiResearchForm.robustness_methods = robustnessMethods.length
      ? robustnessMethods
      : aiResearchForm.robustness_methods
    aiResearchForm.min_robustness_score =
      optionalNumber(snapshot.min_robustness_score) ?? aiResearchForm.min_robustness_score
    aiResearchForm.robustness_monte_carlo_iterations =
      optionalNumber(snapshot.robustness_monte_carlo_iterations)
      ?? aiResearchForm.robustness_monte_carlo_iterations
    aiResearchForm.robustness_random_seed = optionalNumber(snapshot.robustness_random_seed)
    const minPaperTradingDays = optionalNumber(snapshot.min_paper_trading_days)
    if (minPaperTradingDays !== null) {
      aiResearchForm.min_paper_trading_days = Math.max(0, minPaperTradingDays)
    }
  }

  function aiResearchTaskFailureMessage(task: AIStrategyResearchTaskResponse) {
    if (isAIResearchTaskCancelled(task)) return ''
    if (String(task.status || '').toLowerCase() !== 'failed') return ''
    return String(task.error || task.message || 'AI research task failed').trim()
  }

  function resetAIResearchTaskState() {
    aiResearchTaskId.value = ''
    aiResearchTaskStatus.value = ''
    aiResearchTaskStage.value = ''
    aiResearchTaskProgress.value = 0
    aiResearchTaskIteration.value = null
    aiResearchBacktestTaskId.value = ''
    aiResearchCancelledBacktestTaskId.value = ''
    aiResearchTaskPaperWorkspaceId.value = ''
    aiResearchTaskPaperUnitId.value = ''
    aiResearchTaskPaperStarted.value = false
    aiResearchTaskLiveWorkspaceId.value = ''
    aiResearchTaskLiveUnitId.value = ''
    aiResearchTaskLivePrepared.value = false
    aiResearchTaskPipeline.value = null
    aiResearchTaskRequestSnapshot.value = null
    aiResearchTaskAutoContinuationSource.value = null
    aiResearchTaskContinuedFromRunId.value = ''
    aiResearchTaskContinuationSource.value = ''
    aiResearchTaskContinuationContext.value = {}
    aiResearchTaskError.value = ''
    aiResearchTaskMessage.value = ''
    aiResearchTaskLatestIteration.value = null
    aiResearchTaskAssetSpecs.value = {}
    aiResearchTaskBacktestEnvironment.value = {}
    aiResearchTaskPromotionAudit.value = []
  }

  return {
    aiResearchTaskId,
    aiResearchTaskStatus,
    aiResearchTaskStage,
    aiResearchTaskProgress,
    aiResearchTaskIteration,
    aiResearchBacktestTaskId,
    aiResearchCancelledBacktestTaskId,
    aiResearchTaskPaperWorkspaceId,
    aiResearchTaskPaperUnitId,
    aiResearchTaskPaperStarted,
    aiResearchTaskLiveWorkspaceId,
    aiResearchTaskLiveUnitId,
    aiResearchTaskLivePrepared,
    aiResearchTaskPipeline,
    aiResearchTaskRequestSnapshot,
    aiResearchTaskAutoContinuationSource,
    aiResearchTaskContinuedFromRunId,
    aiResearchTaskContinuationSource,
    aiResearchTaskContinuationContext,
    aiResearchTaskError,
    aiResearchTaskMessage,
    aiResearchTaskLatestIteration,
    aiResearchTaskBestIteration,
    aiResearchTaskAssetSpecs,
    aiResearchTaskBacktestEnvironment,
    aiResearchTaskPromotionAudit,
    aiResearchCancelling,
    aiResearchCancelRequested,
    isAIResearchTaskTerminal,
    isAIResearchTaskCancelled,
    isRestorableAIResearchTask,
    boundedNumber,
    aiResearchTaskPollTimeoutMs,
    applyAIResearchTaskStatus,
    applyAIResearchTaskSnapshotToForm,
    aiResearchTaskFailureMessage,
    resetAIResearchTaskState,
  }
}

export type AIResearchTaskState = ReturnType<typeof useAIResearchTaskState>
