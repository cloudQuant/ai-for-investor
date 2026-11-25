import { computed, ref, type Ref } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  strategyApi,
  type AIStrategyResearchConfigProfile,
  type AIStrategyResearchRunRecord,
  type AIStrategyResearchRunRequest,
  type AIStrategyResearchRunResponse,
  type AIStrategyResearchTaskResponse,
  type AIStrategyResearchVersion,
  type AIStrategyResearchVersionCompareResponse,
  type InvestmentMandateResponse,
  type ResearchPipelineEvent,
} from '@/api/strategy'
import type { Strategy } from '@/types'
import {
  AI_RESEARCH_RUNS_AUTO_REFRESH_MS,
  type AIResearchFormState,
} from './aiResearchConstants'
import {
  aiResearchAutoContinuationSource,
  aiResearchVersionMetricLabel,
  formatComparisonValue,
  isLiveTradingPreparedForRecord,
  isPaperTradingStartFailure,
  isPaperTradingTargetMissing,
  outOfSampleRatioPct,
  researchRecordUsesManualCommission,
} from './aiResearchFormatters'
import type {
  AIResearchAutoContinuationSource,
  AIResearchMandateInput,
  AIResearchMandateSnapshot,
  AIResearchPreparedSubmission,
  AIResearchRunnableInput,
  AIResearchSubmissionSnapshot,
} from './aiResearchTaskTypes'
import {
  optionalBoolean,
  optionalNumber,
  routeQueryText,
  stringArrayFromUnknown,
} from './aiResearchValueAdapters'

export interface AIResearchRunHistoryState {
  aiResearchRunsAutoRefreshTimer: ReturnType<typeof setTimeout> | null
  aiResearchRunsAutoRefreshActive: boolean
}

export interface AIResearchRunHistoryDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  route: RouteLocationNormalizedLoaded
  activeTab: Ref<string>
  aiResearchForm: AIResearchFormState
  aiResearchRunning: Ref<boolean>
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  aiResearchActiveConfigProfile: Ref<AIStrategyResearchConfigProfile | null>
  aiResearchRuns: Ref<AIStrategyResearchRunRecord[]>
  aiResearchRunsLoading: Ref<boolean>
  aiResearchSelectedConfigProfileId: Ref<string>
  aiResearchMandate: Ref<InvestmentMandateResponse | null>
  runHistoryState: AIResearchRunHistoryState
  hydrateLiveHandoffFromRunRecord: (record: AIStrategyResearchRunRecord) => void
  liveHandoffLocksPaperActions: (record: AIStrategyResearchRunRecord) => boolean
  liveHandoffStatusForRecord: (record: AIStrategyResearchRunRecord) => string
  syncAIResearchDisplayedOutputWithSelectedProfile: () => void
  setAIResearchConfigProfileFromRunRecord: (record: AIStrategyResearchRunRecord) => void
  loadAIResearchMandate: (mandateId: string | null | undefined) => Promise<void>
  researchResultFromRunRecord: (record: AIStrategyResearchRunRecord) => AIStrategyResearchRunResponse
  researchResultFromTaskSummary: (task: AIStrategyResearchTaskResponse) => AIStrategyResearchRunResponse | null
  applyResearchRunRecordToCurrentResult: (runRecord: AIStrategyResearchRunRecord) => void
  aiResearchTaskFromRunRecord: (record: AIStrategyResearchRunRecord) => AIStrategyResearchTaskResponse
  resetAIResearchTaskState: () => void
  applyAIResearchTaskStatus: (task: AIStrategyResearchTaskResponse) => void
  bestIterationPayloadForRecord: (record: AIStrategyResearchRunRecord) => Record<string, unknown> | null
  strategyFromIterationRecord: (
    record: AIStrategyResearchRunRecord,
    iterationPayload: Record<string, unknown>,
    fallbackIteration: number,
  ) => Strategy
  bestStrategyIdForRecord: (record: AIStrategyResearchRunRecord) => string
  gatewayConfigJsonFromRunRecord: (record: AIStrategyResearchRunRecord) => string
  liveGatewayConfigJsonFromRunRecord: (record: AIStrategyResearchRunRecord) => string
  continuationSourceForRecord: (record: AIStrategyResearchRunRecord) => string
  aiResearchContinuationContextForRecord: (
    record: AIStrategyResearchRunRecord,
    source?: string,
  ) => Record<string, unknown> | undefined
  aiResearchContinuationRunnableInput: (
    source: AIResearchAutoContinuationSource | null,
  ) => AIResearchRunnableInput | null
  captureAIResearchSubmission: (input: AIResearchMandateInput) => AIResearchSubmissionSnapshot
  applyAIResearchMandateSnapshotToForm: (snapshot: AIResearchMandateSnapshot) => void
  handleAIResearchRunError: (error: unknown) => boolean
  runAIResearchPreparedLoop: (prepared: AIResearchPreparedSubmission) => Promise<unknown>
  continueAIResearchFromRunRecord: (
    record: AIStrategyResearchRunRecord,
    continueRun: NonNullable<typeof strategyApi.continueAIResearchRun>,
    prepared: AIResearchPreparedSubmission,
  ) => Promise<unknown>
}

export function useAIResearchRunHistory(deps: AIResearchRunHistoryDeps) {
  const { t, aiResearchForm } = deps

  const aiResearchTimeline = ref<ResearchPipelineEvent[]>([])
  const aiResearchTimelineLoading = ref(false)
  const aiResearchVersions = ref<AIStrategyResearchVersion[]>([])
  const aiResearchVersionsLoading = ref(false)
  const aiResearchVersionCompare = ref<AIStrategyResearchVersionCompareResponse | null>(null)
  const aiResearchVersionCompareLoading = ref(false)
  const aiResearchSelectedVersionIds = ref<string[]>([])

  const aiResearchCanCompareVersions = computed(() => aiResearchSelectedVersionIds.value.length === 2)
  const aiResearchVersionMetricKeys = computed(() => {
    const keys = new Set<string>()
    aiResearchVersions.value.forEach(version => {
      Object.keys(version.backtest_metrics || {}).forEach(key => {
        if (['sharpe_ratio', 'sharpe', 'total_return', 'annual_return', 'max_drawdown', 'total_trades'].includes(key)) {
          keys.add(key)
        }
      })
    })
    return [...keys]
  })

  const aiResearchVersionComparisonRows = computed(() => {
    const comparison = aiResearchVersionCompare.value
    if (!comparison) return []
    const rows: Array<{
      scope: 'metric' | 'gate'
      key: string
      label: string
      left: string
      right: string
      delta: string
      operator: string
      passed: boolean | null
    }> = []
    const append = (scope: 'metric' | 'gate', payload: Record<string, unknown>) => {
      for (const [key, value] of Object.entries(payload)) {
        const item = value && typeof value === 'object' ? value as Record<string, unknown> : {}
        const passed = typeof item.passed === 'boolean' ? item.passed : null
        rows.push({
          scope,
          key,
          label: String(item.label || (scope === 'metric' ? aiResearchVersionMetricLabel(key) : key)),
          left: formatComparisonValue(item.left),
          right: formatComparisonValue(item.right),
          delta: formatComparisonValue(item.delta),
          operator: String(item.operator || '—'),
          passed,
        })
      }
    }
    append('metric', comparison.metric_deltas || {})
    append('gate', comparison.gate_deltas || {})
    return rows
  })

  function bestStrategyFromRunRecord(record: AIStrategyResearchRunRecord): Strategy | null {
    const payload = deps.bestIterationPayloadForRecord(record)
    if (!payload) return null
    const fallbackIteration = Math.max(
      Math.trunc(
        optionalNumber(payload.iteration)
        ?? optionalNumber(record.best_iteration)
        ?? record.iteration_count
        ?? 1,
      ),
      1,
    )
    return deps.strategyFromIterationRecord(record, payload, fallbackIteration)
  }

  function aiResearchRunNeedsAutoRefresh(record: AIStrategyResearchRunRecord) {
    if (!record.paper_trading_started || isLiveTradingPreparedForRecord(record)) return false
    if (isPaperTradingStartFailure(record) || isPaperTradingTargetMissing(record)) return false
    if (deps.liveHandoffLocksPaperActions(record)) return false
    const handoffStatus = deps.liveHandoffStatusForRecord(record)
    if (handoffStatus === 'blocked') return false
    return true
  }

  function shouldAutoRefreshAIResearchRuns() {
    return (
      deps.runHistoryState.aiResearchRunsAutoRefreshActive
      && deps.activeTab.value === 'aiResearch'
      && !deps.aiResearchRunsLoading.value
      && !deps.aiResearchRunning.value
      && deps.aiResearchRuns.value.some(aiResearchRunNeedsAutoRefresh)
    )
  }

  function clearAIResearchRunsAutoRefresh() {
    if (!deps.runHistoryState.aiResearchRunsAutoRefreshTimer) return
    clearTimeout(deps.runHistoryState.aiResearchRunsAutoRefreshTimer)
    deps.runHistoryState.aiResearchRunsAutoRefreshTimer = null
  }

  function unrefTimer(timer: ReturnType<typeof setTimeout>) {
    if (typeof timer !== 'object' || timer === null || !('unref' in timer)) return
    const maybeUnref = (timer as { unref?: () => void }).unref
    if (typeof maybeUnref === 'function') maybeUnref.call(timer)
  }

  function scheduleAIResearchRunsAutoRefresh() {
    clearAIResearchRunsAutoRefresh()
    if (!shouldAutoRefreshAIResearchRuns()) return
    const timer = setTimeout(() => {
      deps.runHistoryState.aiResearchRunsAutoRefreshTimer = null
      void refreshAIResearchRunsSilently()
    }, AI_RESEARCH_RUNS_AUTO_REFRESH_MS)
    deps.runHistoryState.aiResearchRunsAutoRefreshTimer = timer
    unrefTimer(timer)
  }

  async function refreshAIResearchRunsSilently() {
    if (!shouldAutoRefreshAIResearchRuns()) return
    try {
      await loadAIResearchRuns({ showLoading: false })
    } catch {
      scheduleAIResearchRunsAutoRefresh()
    }
  }

  async function loadAIResearchRuns(options: { showLoading?: boolean } = {}) {
    if (deps.aiResearchRunsLoading.value) {
      scheduleAIResearchRunsAutoRefresh()
      return
    }
    const showLoading = options.showLoading ?? true
    if (showLoading) deps.aiResearchRunsLoading.value = true
    try {
      const response = await strategyApi.listAIResearchRuns(undefined, 50)
      deps.aiResearchRuns.value = response.items
      response.items.forEach(deps.hydrateLiveHandoffFromRunRecord)
      deps.syncAIResearchDisplayedOutputWithSelectedProfile()
    } finally {
      if (showLoading) deps.aiResearchRunsLoading.value = false
      scheduleAIResearchRunsAutoRefresh()
    }
  }

  function upsertAIResearchRunRecord(record: AIStrategyResearchRunRecord) {
    deps.hydrateLiveHandoffFromRunRecord(record)
    deps.aiResearchRuns.value = [
      record,
      ...deps.aiResearchRuns.value.filter(item => item.run_id !== record.run_id),
    ].slice(0, 50)
    scheduleAIResearchRunsAutoRefresh()
  }

  function clearAIResearchArtifacts() {
    aiResearchTimeline.value = []
    aiResearchVersions.value = []
    aiResearchVersionCompare.value = null
    aiResearchSelectedVersionIds.value = []
  }

  async function loadAIResearchTimeline(record: AIStrategyResearchRunRecord) {
    aiResearchTimelineLoading.value = true
    try {
      const response = await strategyApi.getAIResearchTimeline(
        record.run_id,
        record.research_workspace_id,
      )
      aiResearchTimeline.value = response.items
    } finally {
      aiResearchTimelineLoading.value = false
    }
  }

  async function loadAIResearchVersions(record: AIStrategyResearchRunRecord) {
    aiResearchVersionsLoading.value = true
    try {
      const response = await strategyApi.listAIResearchVersions(
        record.run_id,
        record.research_workspace_id,
      )
      aiResearchVersions.value = response.items
      aiResearchSelectedVersionIds.value = response.items.slice(-2).map(item => item.id)
      aiResearchVersionCompare.value = null
    } finally {
      aiResearchVersionsLoading.value = false
    }
  }

  async function loadAIResearchRunArtifacts(record: AIStrategyResearchRunRecord) {
    await Promise.allSettled([
      loadAIResearchTimeline(record),
      loadAIResearchVersions(record),
      deps.loadAIResearchMandate(record.mandate_id),
    ])
  }

  async function refreshAIResearchRunRecord(
    runId: string,
    researchWorkspaceId?: string | null,
  ) {
    let record: AIStrategyResearchRunRecord | null = null
    try {
      record = await strategyApi.getAIResearchRun(runId, researchWorkspaceId || undefined)
    } catch {
      const response = await strategyApi.listAIResearchRuns(researchWorkspaceId || undefined, 20)
      record = response.items.find(item => item.run_id === runId) ?? null
    }
    if (!record) return null
    upsertAIResearchRunRecord(record)
    deps.applyResearchRunRecordToCurrentResult(record)
    if (deps.aiResearchResult.value?.run_id === record.run_id) {
      void loadAIResearchRunArtifacts(record)
    }
    return record
  }

  async function compareSelectedAIResearchVersions() {
    if (!aiResearchCanCompareVersions.value) return
    const [leftId, rightId] = aiResearchSelectedVersionIds.value
    aiResearchVersionCompareLoading.value = true
    try {
      aiResearchVersionCompare.value = await strategyApi.compareAIResearchVersions(leftId, rightId)
    } catch {
      ElMessage.error(t('strategy.aiResearchVersionCompareFailed'))
    } finally {
      aiResearchVersionCompareLoading.value = false
    }
  }

  function useAIResearchRecord(record: AIStrategyResearchRunRecord) {
    const gates = record.quality_gates || {}
    aiResearchForm.prompt = record.prompt
    aiResearchForm.workflow_mode = record.workflow_mode === 'prompt' ? 'prompt' : 'auto'
    aiResearchForm.symbol = record.symbol
    aiResearchForm.symbol_name = record.symbol_name || ''
    aiResearchForm.market_data_asset_type = ''
    aiResearchForm.timeframe = record.timeframe || '1d'
    aiResearchForm.timeframe_n = record.timeframe_n || 1
    aiResearchForm.start_date = record.start_date || ''
    aiResearchForm.end_date = record.end_date || ''
    if (typeof record.initial_cash === 'number') {
      aiResearchForm.initial_cash = record.initial_cash
    }
    if (typeof record.commission === 'number') {
      aiResearchForm.commission = record.commission
      aiResearchForm.use_manual_commission = researchRecordUsesManualCommission(record)
    } else {
      aiResearchForm.use_manual_commission = false
    }
    aiResearchForm.annual_days = record.annual_days || 252
    aiResearchForm.calc_method = record.calc_method || 'simple'
    aiResearchForm.weight_mode = record.weight_mode || 'equal'
    aiResearchForm.group_name = record.group_name || record.best_strategy_name || ''
    aiResearchForm.knowledge_base_id = record.knowledge_base_id || ''
    aiResearchForm.thinking_mode = Boolean(record.thinking_mode)
    aiResearchForm.paper_workspace_name = record.paper_workspace_name || ''
    aiResearchForm.trading_workspace_id = record.paper_workspace_id || ''
    aiResearchForm.gateway_config_json = deps.gatewayConfigJsonFromRunRecord(record)
    aiResearchForm.live_workspace_name = record.live_workspace_name || ''
    aiResearchForm.live_trading_workspace_id = record.live_workspace_id || ''
    aiResearchForm.live_gateway_config_json = deps.liveGatewayConfigJsonFromRunRecord(record)
    aiResearchForm.target_sharpe = record.target_sharpe
    aiResearchForm.min_total_trades = record.min_total_trades
    aiResearchForm.use_max_drawdown_limit = typeof gates.max_drawdown_limit === 'number'
    aiResearchForm.max_drawdown_limit = Number(gates.max_drawdown_limit ?? 20)
    aiResearchForm.use_min_total_return = typeof gates.min_total_return === 'number'
    aiResearchForm.min_total_return = Number(gates.min_total_return ?? 0)
    aiResearchForm.use_min_annual_return = typeof gates.min_annual_return === 'number'
    aiResearchForm.min_annual_return = Number(gates.min_annual_return ?? 0)
    aiResearchForm.use_min_win_rate = typeof gates.min_win_rate === 'number'
    aiResearchForm.min_win_rate = Number(gates.min_win_rate ?? 50)
    aiResearchForm.max_iterations = record.max_iterations || 3
    if (typeof record.backtest_timeout_seconds === 'number') {
      aiResearchForm.backtest_timeout_seconds = record.backtest_timeout_seconds
    }
    if (typeof record.poll_interval_seconds === 'number') {
      aiResearchForm.poll_interval_seconds = record.poll_interval_seconds
    }
    aiResearchForm.out_of_sample_validation = optionalBoolean(gates.out_of_sample_validation, true)
    aiResearchForm.require_out_of_sample_validation = optionalBoolean(
      gates.require_out_of_sample_validation,
      false,
    )
    aiResearchForm.out_of_sample_ratio_pct = outOfSampleRatioPct(gates.out_of_sample_ratio)
    aiResearchForm.use_min_out_of_sample_sharpe =
      optionalNumber(gates.min_out_of_sample_sharpe) !== null
    aiResearchForm.min_out_of_sample_sharpe = Number(gates.min_out_of_sample_sharpe ?? 0.6)
    aiResearchForm.use_min_out_of_sample_trades =
      optionalNumber(gates.min_out_of_sample_trades) !== null
    aiResearchForm.min_out_of_sample_trades = Number(gates.min_out_of_sample_trades ?? 1)
    aiResearchForm.robustness_validation = optionalBoolean(gates.robustness_validation, true)
    aiResearchForm.require_robustness_validation = optionalBoolean(
      gates.require_robustness_validation,
      true,
    )
    const robustnessMethods = stringArrayFromUnknown(gates.robustness_methods)
    aiResearchForm.robustness_methods = robustnessMethods.length ? robustnessMethods : ['monte_carlo']
    aiResearchForm.min_robustness_score = Number(gates.min_robustness_score ?? 55)
    aiResearchForm.robustness_monte_carlo_iterations = Number(
      gates.robustness_monte_carlo_iterations ?? 300,
    )
    aiResearchForm.robustness_random_seed = optionalNumber(gates.robustness_random_seed)
    aiResearchForm.min_paper_trading_days = Math.max(
      0,
      Number(gates.min_paper_trading_days ?? aiResearchForm.min_paper_trading_days),
    )
    aiResearchForm.research_workspace_id = record.research_workspace_id || ''
    const bestStrategyId = deps.bestStrategyIdForRecord(record)
    aiResearchForm.seed_strategy_id = bestStrategyId
    aiResearchForm.continue_from_run_id = bestStrategyId ? record.run_id : ''
    aiResearchForm.continuation_source = deps.continuationSourceForRecord(record)
  }

  function selectAIResearchRunRecord(
    record: AIStrategyResearchRunRecord,
    options: { keepSelectedProfile?: boolean } = {},
  ) {
    const selectedProfileId = deps.aiResearchSelectedConfigProfileId.value
    deps.hydrateLiveHandoffFromRunRecord(record)
    deps.aiResearchResult.value = deps.researchResultFromRunRecord(record)
    deps.aiResearchActiveConfigProfile.value = null
    if (!options.keepSelectedProfile) useAIResearchRecord(record)
    deps.resetAIResearchTaskState()
    deps.applyAIResearchTaskStatus(deps.aiResearchTaskFromRunRecord(record))
    if (options.keepSelectedProfile) {
      deps.aiResearchSelectedConfigProfileId.value = selectedProfileId
    } else {
      deps.setAIResearchConfigProfileFromRunRecord(record)
    }
    void loadAIResearchRunArtifacts(record)
  }

  function syncAIResearchFormFromResult(result: AIStrategyResearchRunResponse | null | undefined) {
    const record = result?.run_record
    if (record) useAIResearchRecord(record)
  }

  function clearAIResearchContinuation() {
    aiResearchForm.research_workspace_id = ''
    aiResearchForm.seed_strategy_id = ''
    aiResearchForm.continue_from_run_id = ''
    aiResearchForm.continuation_source = ''
  }

  function aiResearchRouteRunId() {
    return (
      routeQueryText(deps.route.query.ai_research_run_id)
      || routeQueryText(deps.route.query.research_run_id)
      || routeQueryText(deps.route.query.run_id)
    )
  }

  function aiResearchRouteWorkspaceId() {
    return (
      routeQueryText(deps.route.query.research_workspace_id)
      || routeQueryText(deps.route.query.workspace_id)
    )
  }

  function applyAIResearchRoutePrefill() {
    const prompt = routeQueryText(deps.route.query.prompt)
      || routeQueryText(deps.route.query.strategy_prompt)
    const symbol = routeQueryText(deps.route.query.symbol)
    const symbolName = routeQueryText(deps.route.query.symbol_name)
      || routeQueryText(deps.route.query.symbolName)
    const timeframe = routeQueryText(deps.route.query.timeframe)
    const knowledgeBaseId = routeQueryText(deps.route.query.knowledge_base_id)
      || routeQueryText(deps.route.query.kbId)

    if (!prompt && !symbol && !symbolName && !timeframe && !knowledgeBaseId) return false

    deps.activeTab.value = 'aiResearch'
    if (prompt) {
      aiResearchForm.prompt = prompt
      aiResearchForm.workflow_mode = 'prompt'
    }
    if (symbol) aiResearchForm.symbol = symbol
    if (symbolName) aiResearchForm.symbol_name = symbolName
    if (timeframe) aiResearchForm.timeframe = timeframe
    if (knowledgeBaseId) aiResearchForm.knowledge_base_id = knowledgeBaseId
    return true
  }

  async function restoreAIResearchResultFromTask(
    task: AIStrategyResearchTaskResponse,
  ): Promise<AIStrategyResearchRunResponse | null> {
    if (!task.run_id) return null
    try {
      let record: AIStrategyResearchRunRecord | null = null
      try {
        record = await strategyApi.getAIResearchRun(
          task.run_id,
          task.research_workspace_id || undefined,
        )
      } catch {
        const response = await strategyApi.listAIResearchRuns(
          task.research_workspace_id || undefined,
          100,
        )
        record = response.items.find(item => item.run_id === task.run_id) ?? null
      }
      if (!record) return deps.researchResultFromTaskSummary(task)
      upsertAIResearchRunRecord(record)
      return deps.researchResultFromRunRecord(record)
    } catch {
      return deps.researchResultFromTaskSummary(task)
    }
  }

  async function restoreAIResearchRunFromRoute() {
    const runId = aiResearchRouteRunId()
    if (!runId) return false
    try {
      const record = await refreshAIResearchRunRecord(runId, aiResearchRouteWorkspaceId())
      if (!record) return false
      selectAIResearchRunRecord(record)
      deps.activeTab.value = 'aiResearch'
      return true
    } catch {
      return false
    }
  }

  function prepareContinuationPromotion(record: AIStrategyResearchRunRecord) {
    const source = deps.continuationSourceForRecord(record)
    if (source) {
      aiResearchForm.start_paper_trading = true
    }
  }

  function aiResearchContinuationRequest(
    request: AIStrategyResearchRunRequest,
    record: AIStrategyResearchRunRecord,
  ): AIStrategyResearchRunRequest {
    const bestStrategyId = deps.bestStrategyIdForRecord(record)
    const source = deps.continuationSourceForRecord(record)
    const startPaperTrading = source ? true : request.start_paper_trading
    return {
      ...request,
      research_workspace_id: record.research_workspace_id || request.research_workspace_id,
      seed_strategy_id: bestStrategyId || request.seed_strategy_id,
      continue_from_run_id: bestStrategyId ? record.run_id : request.continue_from_run_id,
      continuation_context: deps.aiResearchContinuationContextForRecord(record, source)
        || request.continuation_context,
      start_paper_trading: startPaperTrading,
      paper_workspace_name: startPaperTrading ? request.paper_workspace_name : null,
      trading_workspace_id: request.trading_workspace_id,
    }
  }

  async function continueResearchFromRecord(record: AIStrategyResearchRunRecord) {
    const currentSymbol = aiResearchForm.symbol.trim()
    const recordSymbol = record.symbol.trim()
    const recordTimeframe = record.timeframe || aiResearchForm.timeframe
    let prepared: AIResearchPreparedSubmission | undefined
    const autoContinuationSource = aiResearchAutoContinuationSource(record)
    if (currentSymbol === recordSymbol && aiResearchForm.timeframe === recordTimeframe) {
      const input = deps.aiResearchContinuationRunnableInput(autoContinuationSource)
      if (!input) return
      try {
        prepared = {
          input,
          submission: deps.captureAIResearchSubmission(input),
        }
      } catch (error) {
        deps.handleAIResearchRunError(error)
        return
      }
    }

    useAIResearchRecord(record)
    if (prepared) {
      deps.applyAIResearchMandateSnapshotToForm(prepared.submission.mandate)
    }
    prepareContinuationPromotion(record)
    if (!prepared) {
      const input = deps.aiResearchContinuationRunnableInput(autoContinuationSource)
      if (!input) return
      try {
        prepared = {
          input,
          submission: deps.captureAIResearchSubmission(input),
        }
      } catch (error) {
        deps.handleAIResearchRunError(error)
        return
      }
    }
    if (!prepared) return
    prepared = {
      ...prepared,
      submission: {
        ...prepared.submission,
        request: aiResearchContinuationRequest(prepared.submission.request, record),
      },
    }
    if (
      autoContinuationSource
      && deps.aiResearchMandate.value?.id !== autoContinuationSource.mandateId
    ) {
      await deps.loadAIResearchMandate(autoContinuationSource.mandateId)
    } else if (!deps.aiResearchMandate.value?.id && record.mandate_id) {
      await deps.loadAIResearchMandate(record.mandate_id)
    }
    const continueRun = (strategyApi as typeof strategyApi & {
      continueAIResearchRun?: typeof strategyApi.continueAIResearchRun
      getAIResearchTask?: typeof strategyApi.getAIResearchTask
    }).continueAIResearchRun
    if (typeof continueRun !== 'function') {
      await deps.runAIResearchPreparedLoop(prepared)
      return
    }
    await deps.continueAIResearchFromRunRecord(record, continueRun, prepared)
  }

  async function continueResearchFromCurrentPaperReview() {
    const record = deps.aiResearchResult.value?.run_record
    if (!record) return
    await continueResearchFromRecord(record)
  }

  async function continueResearchFromCurrentRunRecord() {
    const record = deps.aiResearchResult.value?.run_record
    if (!record) return
    await continueResearchFromRecord(record)
  }

  async function continueResearchFromPaperReview(record: AIStrategyResearchRunRecord) {
    await continueResearchFromRecord(record)
  }

  return {
    aiResearchTimeline,
    aiResearchTimelineLoading,
    aiResearchVersions,
    aiResearchVersionsLoading,
    aiResearchVersionCompare,
    aiResearchVersionCompareLoading,
    aiResearchSelectedVersionIds,
    aiResearchCanCompareVersions,
    aiResearchVersionMetricKeys,
    aiResearchVersionComparisonRows,
    bestStrategyFromRunRecord,
    aiResearchRunNeedsAutoRefresh,
    shouldAutoRefreshAIResearchRuns,
    clearAIResearchRunsAutoRefresh,
    unrefTimer,
    scheduleAIResearchRunsAutoRefresh,
    refreshAIResearchRunsSilently,
    loadAIResearchRuns,
    upsertAIResearchRunRecord,
    refreshAIResearchRunRecord,
    clearAIResearchArtifacts,
    loadAIResearchRunArtifacts,
    loadAIResearchTimeline,
    loadAIResearchVersions,
    compareSelectedAIResearchVersions,
    useAIResearchRecord,
    selectAIResearchRunRecord,
    syncAIResearchFormFromResult,
    clearAIResearchContinuation,
    aiResearchRouteRunId,
    aiResearchRouteWorkspaceId,
    applyAIResearchRoutePrefill,
    restoreAIResearchResultFromTask,
    restoreAIResearchRunFromRoute,
    prepareContinuationPromotion,
    aiResearchContinuationRequest,
    continueResearchFromRecord,
    continueResearchFromCurrentPaperReview,
    continueResearchFromCurrentRunRecord,
    continueResearchFromPaperReview,
  }
}
