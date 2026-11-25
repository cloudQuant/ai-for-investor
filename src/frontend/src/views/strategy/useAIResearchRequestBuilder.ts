import { computed, type Ref } from 'vue'
import type { Router } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { MarketAssetType, MarketDataCapabilitiesResponse } from '@/api/marketData'
import type {
  AIStrategyResearchConfigProfile,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunRequest,
  AIStrategyResearchRunResponse,
} from '@/api/strategy'
import {
  AI_RESEARCH_CONFIG_ERROR_MESSAGES,
  AI_RESEARCH_WORKFLOW_STEPS,
  AIResearchConfigError,
  type AIResearchFormState,
} from './aiResearchConstants'
import { enabledQualityGate, formatMetric } from './aiResearchFormatters'
import type {
  AIResearchMandateInput,
  AIResearchMandateSnapshot,
  AIResearchRunnableInput,
  AIResearchSubmissionSnapshot,
} from './aiResearchTaskTypes'
import {
  containsRedactedSecret,
  isRecord,
  parseResearchDate,
} from './aiResearchValueAdapters'
import {
  isAIResearchMarketDataPlatformBridgeEnabled,
  type AIResearchMarketDataPrecheckSnapshot,
  type useAIResearchMarketData,
} from './useAIResearchMarketData'

type AIResearchMarketDataPlatformStatus = ReturnType<
  typeof useAIResearchMarketData
>['aiResearchMarketDataPlatformStatus']['value']

export interface AIResearchRequestBuilderDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  router: Router
  aiResearchForm: AIResearchFormState
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  aiResearchActiveConfigProfile: Ref<AIStrategyResearchConfigProfile | null>
  aiResearchSelectedConfigProfile: Ref<AIStrategyResearchConfigProfile | null>
  aiResearchMandateConfirmed: Ref<boolean>
  aiResearchMandateId: () => string | null
  aiResearchCancelRequested: Ref<boolean>
  aiResearchTaskError: Ref<string>
  aiResearchMarketDataCapabilities: Ref<MarketDataCapabilitiesResponse | null>
  aiResearchErrorMessage: (error: unknown) => string
  aiResearchMandateSnapshot: (input?: AIResearchMandateInput | null) => AIResearchMandateSnapshot
  aiResearchContinuationContext: () => Record<string, unknown> | undefined
  buildGeneratedAIResearchPrompt: () => string
  resolveAIResearchMarketDataCapabilities: (options?: { forceRefresh?: boolean }) => Promise<MarketDataCapabilitiesResponse | null>
  setAIResearchMarketDataPlatformStatus: (
    patch: Partial<AIResearchMarketDataPlatformStatus> & Pick<AIResearchMarketDataPlatformStatus, 'path'>,
  ) => AIResearchMarketDataPlatformStatus
  aiResearchStrictMarketDataRunBlockReasonForStatus: (status: AIResearchMarketDataPlatformStatus) => string
  runAIResearchMarketDataPlatformPrecheck: (
    snapshot: AIResearchMarketDataPrecheckSnapshot,
    controller: AbortController,
    options?: {
      forceStrictLocalReread?: boolean
      capabilities?: MarketDataCapabilitiesResponse | null
    },
  ) => Promise<AIResearchMarketDataPlatformStatus | null>
  bindAIResearchConfigProfileToRunRecord: (
    profile: AIStrategyResearchConfigProfile,
    record: AIStrategyResearchRunRecord,
  ) => Promise<void>
  aiResearchRunMatchesConfigProfile: (
    record: AIStrategyResearchRunRecord,
    profile: AIStrategyResearchConfigProfile,
  ) => boolean
  setAIResearchConfigProfileFromRunRecord: (record: AIStrategyResearchRunRecord) => void
  upsertAIResearchRunRecord: (record: AIStrategyResearchRunRecord) => void
  loadAIResearchRunArtifacts: (record: AIStrategyResearchRunRecord) => Promise<void>
  loadAIResearchRuns: (options?: { showLoading?: boolean }) => Promise<void>
  clearAIResearchArtifacts: () => void
}

export function useAIResearchRequestBuilder(deps: AIResearchRequestBuilderDeps) {
  const { t, router, aiResearchForm } = deps

  const aiResearchHeroSteps = computed(() => [
    { key: 'idea', index: '01', label: t('strategy.aiResearchHeroStepIdea') },
    { key: 'code', index: '02', label: t('strategy.aiResearchHeroStepCode') },
    { key: 'backtest', index: '03', label: t('strategy.aiResearchHeroStepBacktest') },
    { key: 'review', index: '04', label: t('strategy.aiResearchHeroStepReview') },
    { key: 'optimize', index: '05', label: t('strategy.aiResearchHeroStepOptimize') },
  ])

  const aiResearchHeroMetrics = computed(() => [
    {
      key: 'workflow',
      label: t('strategy.aiResearchHeroWorkflow'),
      value: aiResearchForm.workflow_mode === 'auto'
        ? t('strategy.aiResearchWorkflowAuto')
        : t('strategy.aiResearchWorkflowPrompt'),
    },
    {
      key: 'target',
      label: t('strategy.aiResearchHeroTarget'),
      value: formatMetric(aiResearchForm.target_sharpe),
    },
    {
      key: 'iterations',
      label: t('strategy.aiResearchHeroIterations'),
      value: formatMetric(aiResearchForm.max_iterations, 0),
    },
    {
      key: 'validation',
      label: t('strategy.aiResearchHeroValidation'),
      value: aiResearchForm.out_of_sample_validation
        ? aiResearchForm.robustness_validation
          ? `${formatMetric(aiResearchForm.out_of_sample_ratio_pct, 0)}% / R${formatMetric(aiResearchForm.min_robustness_score, 0)}`
          : `${formatMetric(aiResearchForm.out_of_sample_ratio_pct, 0)}%`
        : t('common.disable'),
    },
  ])

  function outOfSampleRatioValue() {
    const ratio = Number(aiResearchForm.out_of_sample_ratio_pct || 25) / 100
    return Number(ratio.toFixed(4))
  }

  function requiredOutOfSampleValidationError() {
    if (
      !aiResearchForm.out_of_sample_validation
      || !aiResearchForm.require_out_of_sample_validation
    ) {
      return ''
    }
    const startDate = parseResearchDate(aiResearchForm.start_date)
    const endDate = parseResearchDate(aiResearchForm.end_date)
    if (!startDate || !endDate || endDate <= startDate) {
      return '强制样本外验证需要填写合法的开始日期和结束日期'
    }
    const totalDays = Math.floor((endDate.getTime() - startDate.getTime()) / 86400000) + 1
    if (totalDays < 8) {
      return '强制样本外验证至少需要 8 天以上的回测区间'
    }
    return ''
  }

  function aiResearchPaperWorkspaceName() {
    return aiResearchForm.paper_workspace_name.trim() || null
  }

  function parseGatewayConfigJson(
    rawValue: string,
    parseErrorMessage: string,
    objectErrorMessage: string,
    redactedErrorMessage: string,
  ): Record<string, unknown> | undefined {
    const raw = rawValue.trim()
    if (!raw) return undefined
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      throw new AIResearchConfigError(parseErrorMessage)
    }
    if (!isRecord(parsed) || Array.isArray(parsed)) {
      throw new AIResearchConfigError(objectErrorMessage)
    }
    if (containsRedactedSecret(parsed)) {
      throw new AIResearchConfigError(redactedErrorMessage)
    }
    return parsed
  }

  function parseAIResearchGatewayConfig() {
    return parseGatewayConfigJson(
      aiResearchForm.gateway_config_json,
      '模拟网关配置必须是合法 JSON',
      '模拟网关配置必须是 JSON 对象',
      '模拟网关配置包含脱敏凭据，请重新输入真实网关配置',
    )
  }

  function parseAIResearchLiveGatewayConfig() {
    return parseGatewayConfigJson(
      aiResearchForm.live_gateway_config_json,
      '实盘网关配置必须是合法 JSON',
      '实盘网关配置必须是 JSON 对象',
      '实盘网关配置包含脱敏凭据，请重新输入真实网关配置',
    )
  }

  function notifyAIResearchConfigError(error: unknown) {
    const message = error instanceof Error
      ? error.message
      : typeof error === 'string'
        ? error
        : ''
    if (!AI_RESEARCH_CONFIG_ERROR_MESSAGES.has(message)) return false
    ElMessage.warning(message)
    return true
  }

  function buildAIResearchRequest(prompt: string, symbol: string): AIStrategyResearchRunRequest {
    const paperWorkspaceName = aiResearchPaperWorkspaceName()
    const gatewayConfig = parseAIResearchGatewayConfig()
    const request: AIStrategyResearchRunRequest = {
      prompt,
      workflow_mode: aiResearchForm.workflow_mode === 'prompt' ? 'prompt' : 'auto',
      workflow_steps: [...AI_RESEARCH_WORKFLOW_STEPS],
      symbol,
      symbol_name: aiResearchForm.symbol_name.trim(),
      timeframe: aiResearchForm.timeframe,
      timeframe_n: aiResearchForm.timeframe_n,
      start_date: aiResearchForm.start_date || null,
      end_date: aiResearchForm.end_date || null,
      target_sharpe: aiResearchForm.target_sharpe,
      min_total_trades: aiResearchForm.min_total_trades,
      max_drawdown_limit: enabledQualityGate(
        aiResearchForm.use_max_drawdown_limit,
        aiResearchForm.max_drawdown_limit,
      ),
      min_total_return: enabledQualityGate(
        aiResearchForm.use_min_total_return,
        aiResearchForm.min_total_return,
      ),
      min_annual_return: enabledQualityGate(
        aiResearchForm.use_min_annual_return,
        aiResearchForm.min_annual_return,
      ),
      min_win_rate: enabledQualityGate(
        aiResearchForm.use_min_win_rate,
        aiResearchForm.min_win_rate,
      ),
      max_iterations: aiResearchForm.max_iterations,
      out_of_sample_validation: aiResearchForm.out_of_sample_validation,
      require_out_of_sample_validation: Boolean(
        aiResearchForm.out_of_sample_validation
          && aiResearchForm.require_out_of_sample_validation,
      ),
      out_of_sample_ratio: outOfSampleRatioValue(),
      min_out_of_sample_sharpe: aiResearchForm.out_of_sample_validation
        ? enabledQualityGate(
            aiResearchForm.use_min_out_of_sample_sharpe,
            aiResearchForm.min_out_of_sample_sharpe,
          )
        : null,
      min_out_of_sample_trades: aiResearchForm.out_of_sample_validation
        ? enabledQualityGate(
            aiResearchForm.use_min_out_of_sample_trades,
            aiResearchForm.min_out_of_sample_trades,
          )
        : null,
      robustness_validation: aiResearchForm.robustness_validation,
      require_robustness_validation: Boolean(
        aiResearchForm.robustness_validation
          && aiResearchForm.require_robustness_validation,
      ),
      robustness_methods: aiResearchForm.robustness_validation
        ? [...aiResearchForm.robustness_methods]
        : [],
      min_robustness_score: aiResearchForm.min_robustness_score,
      robustness_monte_carlo_iterations: aiResearchForm.robustness_monte_carlo_iterations,
      robustness_random_seed: aiResearchForm.robustness_random_seed,
      initial_cash: aiResearchForm.initial_cash,
      annual_days: aiResearchForm.annual_days,
      calc_method: aiResearchForm.calc_method,
      weight_mode: aiResearchForm.weight_mode,
      research_workspace_id: aiResearchForm.research_workspace_id || null,
      mandate_id: deps.aiResearchMandateConfirmed.value ? deps.aiResearchMandateId() : null,
      seed_strategy_id: aiResearchForm.seed_strategy_id || null,
      continue_from_run_id: aiResearchForm.continue_from_run_id || null,
      start_paper_trading: aiResearchForm.start_paper_trading,
      min_paper_trading_days: Math.max(0, aiResearchForm.min_paper_trading_days),
      trading_workspace_id: aiResearchForm.trading_workspace_id.trim() || null,
      paper_workspace_name: aiResearchForm.start_paper_trading
        ? paperWorkspaceName
        : null,
      backtest_timeout_seconds: aiResearchForm.backtest_timeout_seconds,
      poll_interval_seconds: aiResearchForm.poll_interval_seconds,
      group_name: aiResearchForm.group_name.trim() || null,
      knowledge_base_id: aiResearchForm.knowledge_base_id.trim() || null,
      thinking_mode: aiResearchForm.thinking_mode,
    }
    if (aiResearchForm.use_manual_commission) {
      request.commission = aiResearchForm.commission
    }
    const continuationContext = deps.aiResearchContinuationContext()
    if (continuationContext) {
      request.continuation_context = continuationContext
    }
    if (gatewayConfig) {
      request.gateway_config = gatewayConfig
    }
    return request
  }

  function captureAIResearchSubmission(
    input: AIResearchMandateInput,
  ): AIResearchSubmissionSnapshot {
    const mandate = deps.aiResearchMandateSnapshot(input)
    const request = buildAIResearchRequest(input.prompt, input.symbol)
    return {
      request,
      mandate,
      marketDataAssetType: mandate.marketDataAssetType,
    }
  }

  function withoutAIResearchMarketDataBridgeIntent(
    request: AIStrategyResearchRunRequest,
  ): AIStrategyResearchRunRequest {
    const dataConfig = request.data_config
    if (!dataConfig || !Object.prototype.hasOwnProperty.call(dataConfig, 'market_data_asset_type')) {
      return request
    }
    const remainingDataConfig = { ...dataConfig }
    delete remainingDataConfig.market_data_asset_type
    if (Object.keys(remainingDataConfig).length > 0) {
      return { ...request, data_config: remainingDataConfig }
    }
    const requestWithoutDataConfig = { ...request }
    delete requestWithoutDataConfig.data_config
    return requestWithoutDataConfig
  }

  function applyAIResearchMarketDataBridgeIntent(
    request: AIStrategyResearchRunRequest,
    capabilities: MarketDataCapabilitiesResponse | null,
    marketDataAssetType: MarketAssetType | undefined,
  ): AIStrategyResearchRunRequest {
    const requestWithoutBridgeIntent = withoutAIResearchMarketDataBridgeIntent(request)
    if (
      requestWithoutBridgeIntent.data_config
      || !isAIResearchMarketDataPlatformBridgeEnabled(capabilities)
    ) {
      return requestWithoutBridgeIntent
    }
    if (!marketDataAssetType) return requestWithoutBridgeIntent
    return {
      ...requestWithoutBridgeIntent,
      data_config: { market_data_asset_type: marketDataAssetType },
    }
  }

  function aiResearchMarketDataPrecheckSnapshotFromSubmission(
    submission: AIResearchSubmissionSnapshot,
  ): AIResearchMarketDataPrecheckSnapshot {
    const { request } = submission
    const startDate = request.start_date || null
    const endDate = request.end_date || null
    const start = parseResearchDate(startDate || '')
    const endInclusive = parseResearchDate(endDate || '')
    let window: { start: string; end: string } | null = null
    if (start && endInclusive && start <= endInclusive) {
      endInclusive.setUTCDate(endInclusive.getUTCDate() + 1)
      window = { start: start.toISOString(), end: endInclusive.toISOString() }
    }
    const timeframe = request.timeframe || ''
    const period = timeframe === '1d'
      ? 'daily'
      : timeframe === '1w'
        ? 'weekly'
        : timeframe === '1mo'
          ? 'monthly'
          : null
    return {
      symbol: request.symbol.trim(),
      assetType: submission.marketDataAssetType,
      timeframe,
      startDate,
      endDate,
      period,
      window,
    }
  }

  async function resolveAIResearchMarketDataCapabilitiesForAction(): Promise<{
    capabilities: MarketDataCapabilitiesResponse | null
    lastKnownBridgeEnabled: boolean
  }> {
    const lastKnownBridgeEnabled = isAIResearchMarketDataPlatformBridgeEnabled(
      deps.aiResearchMarketDataCapabilities.value,
    )
    const capabilities = await deps.resolveAIResearchMarketDataCapabilities({ forceRefresh: true })
    return {
      capabilities,
      lastKnownBridgeEnabled: capabilities === null && (
        lastKnownBridgeEnabled
        || isAIResearchMarketDataPlatformBridgeEnabled(
          deps.aiResearchMarketDataCapabilities.value,
        )
      ),
    }
  }

  async function ensureAIResearchStrictLocalMarketDataReady(
    submission: AIResearchSubmissionSnapshot,
    capabilities: MarketDataCapabilitiesResponse | null,
    lastKnownBridgeEnabled: boolean,
  ): Promise<boolean> {
    if (!capabilities && lastKnownBridgeEnabled) {
      const reason = deps.aiResearchStrictMarketDataRunBlockReasonForStatus(
        deps.setAIResearchMarketDataPlatformStatus({
          path: 'error',
          detail: 'MARKET_DATA_CAPABILITIES_UNAVAILABLE',
        }),
      )
      deps.aiResearchTaskError.value = reason
      ElMessage.warning(reason)
      return false
    }
    if (!isAIResearchMarketDataPlatformBridgeEnabled(capabilities)) return true

    const status = await deps.runAIResearchMarketDataPlatformPrecheck(
      aiResearchMarketDataPrecheckSnapshotFromSubmission(submission),
      new AbortController(),
      {
        forceStrictLocalReread: true,
        capabilities,
      },
    )
    if (status?.path === 'strict_local') return true

    const reason = deps.aiResearchStrictMarketDataRunBlockReasonForStatus(status ?? {
      path: 'error',
      provider: null,
      coverageStatus: null,
      coverageRatio: null,
      queryId: null,
      detail: 'MARKET_DATA_STRICT_LOCAL_PRECHECK_UNAVAILABLE',
    })
    deps.aiResearchTaskError.value = reason
    ElMessage.warning(reason)
    return false
  }

  function aiResearchPaperStartRequest(record: AIStrategyResearchRunRecord) {
    const gatewayConfig = parseAIResearchGatewayConfig()
    const request = {
      research_workspace_id: record.research_workspace_id,
    } as {
      research_workspace_id: string
      trading_workspace_id?: string
      paper_workspace_name?: string
      gateway_config?: Record<string, unknown>
    }
    const tradingWorkspaceId = aiResearchForm.trading_workspace_id.trim()
    if (tradingWorkspaceId) {
      request.trading_workspace_id = tradingWorkspaceId
    }
    const paperWorkspaceName = aiResearchPaperWorkspaceName()
      || record.paper_workspace_name?.trim()
      || null
    if (paperWorkspaceName) {
      request.paper_workspace_name = paperWorkspaceName
    }
    if (gatewayConfig) {
      request.gateway_config = gatewayConfig
    }
    return request
  }

  function aiResearchLivePrepareRequest(record: AIStrategyResearchRunRecord) {
    const gatewayConfig = parseAIResearchLiveGatewayConfig()
    const request = {
      research_workspace_id: record.research_workspace_id,
    } as {
      research_workspace_id: string
      trading_workspace_id?: string
      live_workspace_name?: string
      gateway_config?: Record<string, unknown>
    }
    const liveWorkspaceId = aiResearchForm.live_trading_workspace_id.trim()
    if (liveWorkspaceId) {
      request.trading_workspace_id = liveWorkspaceId
    }
    const liveWorkspaceName = aiResearchForm.live_workspace_name.trim()
    if (liveWorkspaceName) {
      request.live_workspace_name = liveWorkspaceName
    }
    if (gatewayConfig) {
      request.gateway_config = gatewayConfig
    }
    return request
  }

  function isAIResearchResultPaperStartFailure(result: AIStrategyResearchRunResponse) {
    const pipeline = result.pipeline ?? result.run_record?.pipeline
    return Boolean(
      pipeline?.current_stage === 'paper_trading_failed'
      || pipeline?.paper_trading_error
      || result.run_record?.pipeline?.current_stage === 'paper_trading_failed'
      || result.run_record?.pipeline?.paper_trading_error,
    )
  }

  function notifyAIResearchResult(result: AIStrategyResearchRunResponse) {
    const status = String(result.status || '').toLowerCase()
    if (status === 'cancelled') {
      if (!deps.aiResearchCancelRequested.value) {
        ElMessage.success(t('strategy.aiResearchTaskCancelled'))
      }
      return
    }
    if (isAIResearchResultPaperStartFailure(result)) {
      ElMessage.error(t('strategy.aiResearchPaperStartFailed'))
      return
    }
    if (result.achieved || status === 'achieved') {
      ElMessage.success(t('strategy.aiResearchRunSuccess'))
      return
    }
    if (status === 'timeout' || result.pipeline?.current_stage === 'backtest_timeout') {
      ElMessage.warning(t('strategy.aiResearchBacktestTimedOut'))
      return
    }
    if (status === 'interrupted' || result.pipeline?.current_stage === 'interrupted') {
      ElMessage.warning(t('strategy.aiResearchTaskInterrupted'))
      return
    }
    if (status === 'configuration_invalid' || result.pipeline?.current_stage === 'configuration_invalid') {
      const message = String(result.message || result.next_actions?.[0] || '').trim()
      ElMessage.warning(message ? t('strategy.aiResearchConfigInvalidDetail', { message }) : t('strategy.aiResearchConfigInvalid'))
      return
    }
    ElMessage.warning(t('strategy.aiResearchTargetNotMet'))
  }

  function prepareAIResearchOutputForRun() {
    deps.aiResearchResult.value = null
    deps.clearAIResearchArtifacts()
    const profile = deps.aiResearchSelectedConfigProfile.value
    deps.aiResearchActiveConfigProfile.value = profile
      ? { ...profile, config: { ...profile.config } }
      : null
  }

  function aiResearchRunnableInput(): AIResearchRunnableInput | null {
    let prompt = aiResearchForm.prompt.trim()
    const promptRequired = aiResearchForm.workflow_mode === 'prompt'
    const shouldUseServerGeneratedPrompt = !prompt && !promptRequired
    const symbol = aiResearchForm.symbol.trim()
    if (!symbol) {
      ElMessage.warning(t('strategy.aiResearchSymbolRequired'))
      return null
    }
    if (!prompt && promptRequired) {
      ElMessage.warning(t('strategy.aiResearchPromptOrAutoRequired'))
      return null
    }
    if (shouldUseServerGeneratedPrompt) {
      aiResearchForm.prompt = deps.buildGeneratedAIResearchPrompt()
      prompt = ''
    }
    const outOfSampleError = requiredOutOfSampleValidationError()
    if (outOfSampleError) {
      ElMessage.warning(outOfSampleError)
      return null
    }
    return { prompt, symbol, shouldUseServerGeneratedPrompt }
  }

  async function applyCompletedAIResearchResult(result: AIStrategyResearchRunResponse) {
    deps.aiResearchResult.value = result
    if (result.run_record) {
      const activeProfile = deps.aiResearchActiveConfigProfile.value
        ?? deps.aiResearchSelectedConfigProfile.value
      if (activeProfile) {
        await deps.bindAIResearchConfigProfileToRunRecord(activeProfile, result.run_record)
      }
      const selected = deps.aiResearchSelectedConfigProfile.value
      if (!selected || !deps.aiResearchRunMatchesConfigProfile(result.run_record, selected)) {
        deps.setAIResearchConfigProfileFromRunRecord(result.run_record)
      }
      deps.upsertAIResearchRunRecord(result.run_record)
      await deps.loadAIResearchRunArtifacts(result.run_record)
    } else {
      await deps.loadAIResearchRuns()
    }
    notifyAIResearchResult(result)
  }

  function handleAIResearchRunError(error: unknown) {
    if (
      error instanceof Error
      && error.message === 'AI_RESEARCH_CANCELLED'
      && deps.aiResearchCancelRequested.value
    ) {
      deps.aiResearchTaskError.value = ''
      return true
    }
    if (notifyAIResearchConfigError(error)) {
      deps.aiResearchTaskError.value = ''
      return true
    }
    deps.aiResearchTaskError.value = deps.aiResearchErrorMessage(error)
    ElMessage.error(t('strategy.aiResearchRunFailed'))
    return true
  }

  function openResearchWorkspace() {
    const workspaceId = deps.aiResearchResult.value?.research_workspace.id
    if (!workspaceId) return
    router.push({ name: 'ResearchWorkspaceDetail', params: { id: workspaceId } })
  }

  function openPaperWorkspace() {
    const workspaceId = deps.aiResearchResult.value?.paper_trading?.workspace.id
      || deps.aiResearchResult.value?.run_record?.paper_workspace_id
    if (!workspaceId) return
    router.push({ name: 'TradingWorkspaceDetail', params: { id: workspaceId } })
  }

  function openLiveWorkspaceFromRecord(record: AIStrategyResearchRunRecord) {
    const workspaceId = record.live_workspace_id || record.pipeline?.live_workspace_id
    if (!workspaceId) return
    router.push({ name: 'TradingWorkspaceDetail', params: { id: workspaceId } })
  }

  function openLiveWorkspaceFromCurrentResult() {
    const record = deps.aiResearchResult.value?.run_record
    if (!record) return
    openLiveWorkspaceFromRecord(record)
  }

  return {
    aiResearchHeroSteps,
    aiResearchHeroMetrics,
    outOfSampleRatioValue,
    requiredOutOfSampleValidationError,
    aiResearchPaperWorkspaceName,
    parseGatewayConfigJson,
    parseAIResearchGatewayConfig,
    parseAIResearchLiveGatewayConfig,
    notifyAIResearchConfigError,
    buildAIResearchRequest,
    captureAIResearchSubmission,
    withoutAIResearchMarketDataBridgeIntent,
    applyAIResearchMarketDataBridgeIntent,
    aiResearchMarketDataPrecheckSnapshotFromSubmission,
    resolveAIResearchMarketDataCapabilitiesForAction,
    ensureAIResearchStrictLocalMarketDataReady,
    aiResearchPaperStartRequest,
    aiResearchLivePrepareRequest,
    isAIResearchResultPaperStartFailure,
    notifyAIResearchResult,
    prepareAIResearchOutputForRun,
    aiResearchRunnableInput,
    applyCompletedAIResearchResult,
    handleAIResearchRunError,
    openResearchWorkspace,
    openPaperWorkspace,
    openLiveWorkspaceFromRecord,
    openLiveWorkspaceFromCurrentResult,
  }
}
