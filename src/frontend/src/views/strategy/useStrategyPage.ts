/** State, side effects, and actions for the strategy management page. */

import { onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  strategyApi,
  type AIStrategyLiveHandoffPackage,
  type AIStrategyPaperTradingReview,
  type AIStrategyResearchConfigProfile,
  type AIStrategyResearchRunRecord,
  type AIStrategyResearchRunResponse,
} from '@/api/strategy'
import { useStrategyStore } from '@/stores/strategy'
import {
  AI_RESEARCH_CONFIG_ERROR_MESSAGES,
  AI_RESEARCH_LIVE_HANDOFF_STATUS_LABELS,
  AI_RESEARCH_LIVE_READINESS_STATUS_LABELS,
  AI_RESEARCH_PAPER_REVIEW_STATUS_LABELS,
  AI_RESEARCH_PAPER_RULE_STATUS_LABELS,
  AI_RESEARCH_PIPELINE_STEP_STATUS_LABELS,
  AI_RESEARCH_RUN_STATUS_LABELS,
  AI_RESEARCH_RUNS_AUTO_REFRESH_MS,
  AI_RESEARCH_STAGE_LABELS,
  AI_RESEARCH_WORKFLOW_STEPS,
  createAIResearchForm,
  DEFAULT_AI_RESEARCH_END_DATE,
  DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS,
  DEFAULT_AI_RESEARCH_START_DATE,
  LIVE_GATEWAY_CONFIG_PLACEHOLDER,
  PAPER_GATEWAY_CONFIG_PLACEHOLDER,
  todayIsoDate,
} from './aiResearchConstants'
import {
  aiResearchAutoContinuationSource,
  aiResearchEventTagType,
  aiResearchRunStatusLabel,
  aiResearchStageLabel,
  aiResearchTaskAutoContinuationSourceFromTask,
  aiResearchTaskExplicitFields,
  aiResearchTaskRestoredCommission,
  aiResearchTaskUsesManualCommission,
  aiResearchVersionMetric,
  aiResearchVersionMetricLabel,
  aiResearchVersionStatusTagType,
  canApproveLiveHandoff,
  configStringValue,
  continuationIterationPayload,
  continuationSourceLabel,
  enabledQualityGate,
  formatAIResearchConfigJson,
  formatDateTime,
  formatMetric,
  gateGapListFromUnknown,
  gateGapText,
  hasConfigKey,
  isLiveTradingActivatedForRecord,
  isLiveTradingPreparedForRecord,
  isPaperTradingStartFailure,
  isPaperTradingTargetMissing,
  iterationProgress,
  iterationProgressDeltaText,
  iterationProgressLabel,
  iterationProgressTagType,
  liveHandoffApprovalLabel,
  liveHandoffStatusLabel,
  liveReadinessChecklistForRecord,
  liveReadinessChecklistForReview,
  liveReadinessChecklistFromPayload,
  liveReadinessExpiresAtForRecord,
  liveReadinessStatusLabel,
  liveTradingPreparedAtFromPipeline,
  liveTradingPrepareSummary,
  mandateQualityGateSummary,
  outOfSampleRatioPct,
  paperHandoffRunRecordAssetSpecs,
  paperHandoffRunRecordBacktestEnvironment,
  paperMonitoringPlanFromHandoff,
  paperReviewDispositionLabel,
  paperReviewFailureText,
  paperReviewLockForRecord,
  paperReviewLockFromPayload,
  paperReviewLockStopResultText,
  paperReviewLockSummary,
  paperReviewRuleGapText,
  paperReviewRuleStatusLabel,
  paperReviewStatusLabel,
  paperStartButtonLabel,
  paperTradingStartError,
  pipelineStage,
  pipelineStageLabel,
  pipelineStepIterationText,
  pipelineStepStatusLabel,
  pipelineStepTagType,
  promotionAuditFromPayload,
  researchIterationNextActions,
  researchRecordUsesManualCommission,
  researchRunTimestamp,
  resolvedAIResearchTaskBacktestEnvironment,
  strategyGenerationText,
  stringListFromUnknown,
  taskLatestIterationDiagnostics,
  taskLatestIterationLabel,
  taskLatestIterationMetric,
  taskLatestIterationProgress,
  formatTaskProgress,
} from './aiResearchFormatters'
import {
  aiResearchRequestSnapshotFromRunRecord,
  aiResearchTaskFromRunRecord,
  paperStartedPipeline as buildPaperStartedPipeline,
} from './aiResearchRunTransforms'
import {
  arrayFromUnknown,
  containsRedactedSecret,
  isRecord,
  nullableString,
  optionalBoolean,
  optionalNumber,
  parseResearchDate,
  routeQueryText,
  stringArrayFromUnknown,
  stringFromUnknown,
  uniqueTextItems,
} from './aiResearchValueAdapters'
import { useAIResearchConfigProfiles } from './useAIResearchConfigProfiles'
import { useAIResearchMandate } from './useAIResearchMandate'
import { useAIResearchMarketData } from './useAIResearchMarketData'
import { useAIResearchPipelineSelectors } from './useAIResearchPipelineSelectors'
import { useAIResearchRequestBuilder } from './useAIResearchRequestBuilder'
import { useAIResearchRunExecution } from './useAIResearchRunExecution'
import { useAIResearchRunHistory, type AIResearchRunHistoryState } from './useAIResearchRunHistory'
import { useAIResearchRunRecordAdapters } from './useAIResearchRunRecordAdapters'
import { useAIResearchRuntimeOperations } from './useAIResearchRuntimeOperations'
import { useAIResearchRuntimeProjections } from './useAIResearchRuntimeProjections'
import {
  AI_RESEARCH_TASK_MAX_TIMEOUT_MS,
  AI_RESEARCH_TASK_MIN_TIMEOUT_MS,
  AI_RESEARCH_TASK_POLL_INTERVAL_MS,
  sleep,
  useAIResearchTaskLifecycle,
} from './useAIResearchTaskLifecycle'
import { useAIResearchTaskState } from './useAIResearchTaskState'
import { useStrategyPageDialogs } from './useStrategyPageDialogs'
import { useStrategyPageViewState } from './useStrategyPageViewState'

export function useStrategyPage() {
  const { t } = useI18n()
  const route = useRoute()
  const router = useRouter()
  const strategyStore = useStrategyStore()

  const viewState = useStrategyPageViewState({ route, strategyStore, t })
  const dialogs = useStrategyPageDialogs({
    t,
    router,
    strategyStore,
    activeTab: viewState.activeTab,
  })
  const runtimeProjections = useAIResearchRuntimeProjections({
    t,
    formatMetric,
    aiResearchStageLabel,
    outOfSampleRatioPct,
  })

  const aiResearchRunning = ref(false)
  const aiResearchResult = ref<AIStrategyResearchRunResponse | null>(null)
  const aiResearchActiveConfigProfile = ref<AIStrategyResearchConfigProfile | null>(null)
  const aiResearchRunsLoading = ref(false)
  const aiResearchRuns = ref<AIStrategyResearchRunRecord[]>([])
  const aiResearchPaperStartingRunId = ref('')
  const aiResearchPaperReviewingRunId = ref('')
  const aiResearchLiveHandoffLoadingRunId = ref('')
  const aiResearchStrategyViewingRunId = ref('')
  const aiResearchPaperReviews = reactive<Record<string, AIStrategyPaperTradingReview>>({})
  const aiResearchLiveHandoffs = reactive<Record<string, AIStrategyLiveHandoffPackage>>({})
  const aiResearchLiveHandoffApprovingRunId = ref('')
  const aiResearchLiveTradingPreparingRunId = ref('')
  const aiResearchLiveTradingActivatingRunId = ref('')
  const aiResearchLiveTradingDeactivatingRunId = ref('')
  const aiResearchForm = createAIResearchForm()

  const runHistoryState: AIResearchRunHistoryState = {
    aiResearchRunsAutoRefreshTimer: null,
    aiResearchRunsAutoRefreshActive: false,
  }

  function hydrateLiveHandoffFromRunRecord(record: AIStrategyResearchRunRecord) {
    const handoff = record.live_handoff
    if (handoff?.run_id === record.run_id) {
      aiResearchLiveHandoffs[record.run_id] = handoff
      return
    }
    const status = String(record.paper_review_status || '').trim()
    if (status && status !== 'ready_for_live_candidate') {
      delete aiResearchLiveHandoffs[record.run_id]
    }
  }

  const runRecordAdapters = useAIResearchRunRecordAdapters({
    minPaperTradingDays: DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS,
    runtimeAssetSpecsPayload: runtimeProjections.runtimeAssetSpecsPayload,
    runtimeEnvironmentPayload: runtimeProjections.runtimeEnvironmentPayload,
    bestIterationPayloadForRecord: runtimeProjections.bestIterationPayloadForRecord,
    bestStrategyFromRunRecord: (record) => runHistoryModule.bestStrategyFromRunRecord(record),
    fallbackSnapshotStrategyId: runtimeProjections.fallbackSnapshotStrategyId,
    iterationStrategyPayload: runtimeProjections.iterationStrategyPayload,
    iterationUnitPayload: runtimeProjections.iterationUnitPayload,
    iterationRunResultPayload: runtimeProjections.iterationRunResultPayload,
    iterationUnitStatusPayload: runtimeProjections.iterationUnitStatusPayload,
    validationWindowFromUnknown: runtimeProjections.validationWindowFromUnknown,
    promotionAuditFromPayload,
    hydrateLiveHandoffFromRunRecord,
    liveTradingPreparedAtFromPipeline,
  })

  const marketData = useAIResearchMarketData({ t, aiResearchForm })

  const aiResearchTaskState = useAIResearchTaskState({
    aiResearchForm,
    aiResearchTaskAutoContinuationSourceFromTask,
    gatewayConfigJsonFromTaskSnapshot: runtimeProjections.gatewayConfigJsonFromTaskSnapshot,
    aiResearchMarketDataAssetTypeFromDataConfig: marketData.aiResearchMarketDataAssetTypeFromDataConfig,
    resolvedAIResearchTaskBacktestEnvironment,
    aiResearchTaskRestoredCommission,
    aiResearchTaskUsesManualCommission,
    promotionAuditFromPayload,
  })

  const pipelineSelectors = useAIResearchPipelineSelectors({
    t,
    aiResearchForm,
    aiResearchRunning,
    aiResearchResult,
    aiResearchRuns,
    aiResearchPaperReviews,
    aiResearchLiveHandoffs,
    aiResearchTaskId: aiResearchTaskState.aiResearchTaskId,
    aiResearchTaskStatus: aiResearchTaskState.aiResearchTaskStatus,
    aiResearchTaskStage: aiResearchTaskState.aiResearchTaskStage,
    aiResearchTaskPipeline: aiResearchTaskState.aiResearchTaskPipeline,
    aiResearchTaskRequestSnapshot: aiResearchTaskState.aiResearchTaskRequestSnapshot,
    aiResearchTaskContinuedFromRunId: aiResearchTaskState.aiResearchTaskContinuedFromRunId,
    aiResearchTaskContinuationSource: aiResearchTaskState.aiResearchTaskContinuationSource,
    aiResearchTaskContinuationContext: aiResearchTaskState.aiResearchTaskContinuationContext,
    aiResearchTaskPaperWorkspaceId: aiResearchTaskState.aiResearchTaskPaperWorkspaceId,
    aiResearchTaskPaperUnitId: aiResearchTaskState.aiResearchTaskPaperUnitId,
    aiResearchTaskPaperStarted: aiResearchTaskState.aiResearchTaskPaperStarted,
    aiResearchTaskLiveWorkspaceId: aiResearchTaskState.aiResearchTaskLiveWorkspaceId,
    aiResearchTaskLiveUnitId: aiResearchTaskState.aiResearchTaskLiveUnitId,
    aiResearchTaskLivePrepared: aiResearchTaskState.aiResearchTaskLivePrepared,
    aiResearchTaskLatestIteration: aiResearchTaskState.aiResearchTaskLatestIteration,
    aiResearchTaskBestIteration: aiResearchTaskState.aiResearchTaskBestIteration,
    bestStrategyIdForRecord: runtimeProjections.bestStrategyIdForRecord,
    outOfSampleStatusLabel: runtimeProjections.outOfSampleStatusLabel,
    outOfSampleValidationFromHandoff: runtimeProjections.outOfSampleValidationFromHandoff,
    iterationOutOfSampleValidation: runtimeProjections.iterationOutOfSampleValidation,
    paperEnvironmentItems: runtimeProjections.paperEnvironmentItems,
    researchRuntimeItems: runtimeProjections.researchRuntimeItems,
    researchResultFromRunRecord: runRecordAdapters.researchResultFromRunRecord,
    hydrateLiveHandoffFromRunRecord,
  })

  const mandateModule = useAIResearchMandate({
    t,
    aiResearchForm,
    aiResearchRunning,
    aiResearchResolvedMarketDataAssetType: marketData.aiResearchResolvedMarketDataAssetType,
    aiResearchAssetConstraintLine: marketData.aiResearchAssetConstraintLine,
    outOfSampleRatioValue: () => requestBuilderModule.outOfSampleRatioValue(),
    requiredOutOfSampleValidationError: () => requestBuilderModule.requiredOutOfSampleValidationError(),
    aiResearchRunnableInput: () => requestBuilderModule.aiResearchRunnableInput(),
  })

  const configProfilesModule = useAIResearchConfigProfiles({
    t,
    aiResearchForm,
    aiResearchRunning,
    aiResearchResult,
    aiResearchActiveConfigProfile,
    aiResearchRuns,
    isAIResearchMarketDataAssetType: marketData.isAIResearchMarketDataAssetType,
    buildGeneratedAIResearchPrompt: mandateModule.buildGeneratedAIResearchPrompt,
    clearAIResearchMandate: mandateModule.clearAIResearchMandate,
    clearAIResearchArtifacts: () => runHistoryModule.clearAIResearchArtifacts(),
    resetAIResearchTaskState: aiResearchTaskState.resetAIResearchTaskState,
    selectAIResearchRunRecord: (record, options) => (
      runHistoryModule.selectAIResearchRunRecord(record, options)
    ),
  })

  const requestBuilderModule = useAIResearchRequestBuilder({
    t,
    router,
    aiResearchForm,
    aiResearchResult,
    aiResearchActiveConfigProfile,
    aiResearchSelectedConfigProfile: configProfilesModule.aiResearchSelectedConfigProfile,
    aiResearchMandateConfirmed: mandateModule.aiResearchMandateConfirmed,
    aiResearchMandateId: () => mandateModule.aiResearchMandate.value?.id ?? null,
    aiResearchCancelRequested: aiResearchTaskState.aiResearchCancelRequested,
    aiResearchTaskError: aiResearchTaskState.aiResearchTaskError,
    aiResearchMarketDataCapabilities: marketData.aiResearchMarketDataCapabilities,
    aiResearchErrorMessage: (error) => taskLifecycle.aiResearchErrorMessage(error),
    aiResearchMandateSnapshot: mandateModule.aiResearchMandateSnapshot,
    aiResearchContinuationContext: pipelineSelectors.aiResearchContinuationContext,
    buildGeneratedAIResearchPrompt: mandateModule.buildGeneratedAIResearchPrompt,
    resolveAIResearchMarketDataCapabilities: marketData.resolveAIResearchMarketDataCapabilities,
    setAIResearchMarketDataPlatformStatus: marketData.setAIResearchMarketDataPlatformStatus,
    aiResearchStrictMarketDataRunBlockReasonForStatus: (
      marketData.aiResearchStrictMarketDataRunBlockReasonForStatus
    ),
    runAIResearchMarketDataPlatformPrecheck: marketData.runAIResearchMarketDataPlatformPrecheck,
    bindAIResearchConfigProfileToRunRecord: configProfilesModule.bindAIResearchConfigProfileToRunRecord,
    aiResearchRunMatchesConfigProfile: configProfilesModule.aiResearchRunMatchesConfigProfile,
    setAIResearchConfigProfileFromRunRecord: configProfilesModule.setAIResearchConfigProfileFromRunRecord,
    upsertAIResearchRunRecord: (record) => runHistoryModule.upsertAIResearchRunRecord(record),
    loadAIResearchRunArtifacts: (record) => runHistoryModule.loadAIResearchRunArtifacts(record),
    loadAIResearchRuns: (options) => runHistoryModule.loadAIResearchRuns(options),
    clearAIResearchArtifacts: () => runHistoryModule.clearAIResearchArtifacts(),
  })

  const runHistoryModule = useAIResearchRunHistory({
    t,
    route,
    activeTab: viewState.activeTab,
    aiResearchForm,
    aiResearchRunning,
    aiResearchResult,
    aiResearchActiveConfigProfile,
    aiResearchRuns,
    aiResearchRunsLoading,
    aiResearchSelectedConfigProfileId: configProfilesModule.aiResearchSelectedConfigProfileId,
    aiResearchMandate: mandateModule.aiResearchMandate,
    runHistoryState,
    hydrateLiveHandoffFromRunRecord,
    liveHandoffLocksPaperActions: pipelineSelectors.liveHandoffLocksPaperActions,
    liveHandoffStatusForRecord: pipelineSelectors.liveHandoffStatusForRecord,
    syncAIResearchDisplayedOutputWithSelectedProfile: (
      configProfilesModule.syncAIResearchDisplayedOutputWithSelectedProfile
    ),
    setAIResearchConfigProfileFromRunRecord: configProfilesModule.setAIResearchConfigProfileFromRunRecord,
    loadAIResearchMandate: mandateModule.loadAIResearchMandate,
    researchResultFromRunRecord: runRecordAdapters.researchResultFromRunRecord,
    researchResultFromTaskSummary: runRecordAdapters.researchResultFromTaskSummary,
    applyResearchRunRecordToCurrentResult: pipelineSelectors.applyResearchRunRecordToCurrentResult,
    aiResearchTaskFromRunRecord,
    resetAIResearchTaskState: aiResearchTaskState.resetAIResearchTaskState,
    applyAIResearchTaskStatus: aiResearchTaskState.applyAIResearchTaskStatus,
    bestIterationPayloadForRecord: runtimeProjections.bestIterationPayloadForRecord,
    strategyFromIterationRecord: runRecordAdapters.strategyFromIterationRecord,
    bestStrategyIdForRecord: runtimeProjections.bestStrategyIdForRecord,
    gatewayConfigJsonFromRunRecord: runtimeProjections.gatewayConfigJsonFromRunRecord,
    liveGatewayConfigJsonFromRunRecord: runtimeProjections.liveGatewayConfigJsonFromRunRecord,
    continuationSourceForRecord: pipelineSelectors.continuationSourceForRecord,
    aiResearchContinuationContextForRecord: pipelineSelectors.aiResearchContinuationContextForRecord,
    aiResearchContinuationRunnableInput: mandateModule.aiResearchContinuationRunnableInput,
    captureAIResearchSubmission: requestBuilderModule.captureAIResearchSubmission,
    applyAIResearchMandateSnapshotToForm: mandateModule.applyAIResearchMandateSnapshotToForm,
    handleAIResearchRunError: requestBuilderModule.handleAIResearchRunError,
    runAIResearchPreparedLoop: (prepared) => runExecution.runAIResearchPreparedLoop(prepared),
    continueAIResearchFromRunRecord: (record, continueRun, prepared) => (
      runExecution.continueAIResearchFromRunRecord(record, continueRun, prepared)
    ),
  })

  const taskLifecycle = useAIResearchTaskLifecycle({
    t,
    api: strategyApi,
    taskState: aiResearchTaskState,
    aiResearchRunning,
    aiResearchResult,
    restoreAIResearchResultFromTask: runHistoryModule.restoreAIResearchResultFromTask,
    syncAIResearchFormFromResult: runHistoryModule.syncAIResearchFormFromResult,
    setAIResearchConfigProfileFromRunRecord: configProfilesModule.setAIResearchConfigProfileFromRunRecord,
    upsertAIResearchRunRecord: runHistoryModule.upsertAIResearchRunRecord,
    loadAIResearchRuns: runHistoryModule.loadAIResearchRuns,
    refreshAIResearchRunRecord: runHistoryModule.refreshAIResearchRunRecord,
    researchResultFromRunRecord: runRecordAdapters.researchResultFromRunRecord,
    notifyAIResearchResult: requestBuilderModule.notifyAIResearchResult,
    scheduleAIResearchRunsAutoRefresh: runHistoryModule.scheduleAIResearchRunsAutoRefresh,
  })

  const runExecution = useAIResearchRunExecution({
    api: strategyApi,
    taskState: aiResearchTaskState,
    aiResearchForm,
    aiResearchRunning,
    aiResearchResult,
    aiResearchMandate: mandateModule.aiResearchMandate,
    canRetryAIResearchTask: () => pipelineSelectors.canRetryAIResearchTask.value,
    aiResearchRunnableInput: requestBuilderModule.aiResearchRunnableInput,
    aiResearchContinuationRunnableInput: mandateModule.aiResearchContinuationRunnableInput,
    captureAIResearchSubmission: requestBuilderModule.captureAIResearchSubmission,
    loadAIResearchMandate: mandateModule.loadAIResearchMandate,
    ensureAIResearchMandateConfirmed: mandateModule.ensureAIResearchMandateConfirmed,
    resolveAIResearchMarketDataCapabilitiesForAction: (
      requestBuilderModule.resolveAIResearchMarketDataCapabilitiesForAction
    ),
    ensureAIResearchStrictLocalMarketDataReady: (
      requestBuilderModule.ensureAIResearchStrictLocalMarketDataReady
    ),
    applyAIResearchMarketDataBridgeIntent: requestBuilderModule.applyAIResearchMarketDataBridgeIntent,
    prepareAIResearchOutputForRun: requestBuilderModule.prepareAIResearchOutputForRun,
    runAIResearchRequest: taskLifecycle.runAIResearchRequest,
    applyCompletedAIResearchResult: requestBuilderModule.applyCompletedAIResearchResult,
    handleAIResearchRunError: requestBuilderModule.handleAIResearchRunError,
    clearAIResearchContinuation: runHistoryModule.clearAIResearchContinuation,
    scheduleAIResearchRunsAutoRefresh: runHistoryModule.scheduleAIResearchRunsAutoRefresh,
    aiResearchTaskPollTimeoutMs: aiResearchTaskState.aiResearchTaskPollTimeoutMs,
    pollAIResearchTask: taskLifecycle.pollAIResearchTask,
    setAIResearchConfigProfileFromRunRecord: configProfilesModule.setAIResearchConfigProfileFromRunRecord,
    upsertAIResearchRunRecord: runHistoryModule.upsertAIResearchRunRecord,
    loadAIResearchRuns: runHistoryModule.loadAIResearchRuns,
    notifyAIResearchResult: requestBuilderModule.notifyAIResearchResult,
  })

  const runtimeOperations = useAIResearchRuntimeOperations({
    t,
    aiResearchPaperStartingRunId,
    aiResearchStrategyViewingRunId,
    aiResearchPaperReviewingRunId,
    aiResearchLiveHandoffLoadingRunId,
    aiResearchLiveHandoffApprovingRunId,
    aiResearchLiveTradingPreparingRunId,
    aiResearchLiveTradingActivatingRunId,
    aiResearchLiveTradingDeactivatingRunId,
    aiResearchLiveHandoffs,
    aiResearchPaperReviews,
    aiResearchResult,
    aiResearchPaperStartRequest: requestBuilderModule.aiResearchPaperStartRequest,
    aiResearchLivePrepareRequest: requestBuilderModule.aiResearchLivePrepareRequest,
    refreshAIResearchRunRecord: runHistoryModule.refreshAIResearchRunRecord,
    upsertAIResearchRunRecord: runHistoryModule.upsertAIResearchRunRecord,
    applyPaperStartToCurrentResult: pipelineSelectors.applyPaperStartToCurrentResult,
    applyPaperReviewToCurrentResult: pipelineSelectors.applyPaperReviewToCurrentResult,
    applyResearchRunRecordToCurrentResult: pipelineSelectors.applyResearchRunRecordToCurrentResult,
    paperStartFailedRunRecord: pipelineSelectors.paperStartFailedRunRecord,
    paperStartedRunRecord: pipelineSelectors.paperStartedRunRecord,
    reviewedRunRecord: pipelineSelectors.reviewedRunRecord,
    bestStrategyFromRunRecord: runHistoryModule.bestStrategyFromRunRecord,
    bestStrategyIdForRecord: runtimeProjections.bestStrategyIdForRecord,
    liveHandoffForRecord: pipelineSelectors.liveHandoffForRecord,
    canApproveLiveHandoff,
    canPrepareLiveTradingFromRecord: pipelineSelectors.canPrepareLiveTradingFromRecord,
    canActivateLiveTradingFromRecord: pipelineSelectors.canActivateLiveTradingFromRecord,
    canDeactivateLiveTradingFromRecord: pipelineSelectors.canDeactivateLiveTradingFromRecord,
    notifyAIResearchConfigError: requestBuilderModule.notifyAIResearchConfigError,
    viewStrategy: dialogs.viewStrategy,
  })

  onMounted(async () => {
    runHistoryState.aiResearchRunsAutoRefreshActive = true
    try {
      const initialLoads: Array<Promise<unknown>> = [
        strategyStore.fetchStrategies(),
        strategyStore.fetchTemplates(),
      ]
      if (viewState.showAIResearchTab.value) {
        initialLoads.push(runHistoryModule.loadAIResearchRuns())
        initialLoads.push(configProfilesModule.loadAIResearchConfigProfiles())
        initialLoads.push(marketData.resolveAIResearchMarketDataCapabilities())
      }
      await Promise.all(initialLoads)
      if (viewState.showAIResearchTab.value) {
        const restoredFromRoute = await runHistoryModule.restoreAIResearchRunFromRoute()
        const prefilledFromRoute = !restoredFromRoute && runHistoryModule.applyAIResearchRoutePrefill()
        if (!restoredFromRoute && !prefilledFromRoute) {
          void taskLifecycle.restoreActiveAIResearchTask()
        }
      }
    } catch {
      ElMessage.error(t('strategy.loadFailed'))
    }
  })

  watch(viewState.activeTab, tab => {
    if (!viewState.showAIResearchTab.value && tab === 'aiResearch') {
      viewState.activeTab.value = 'gallery'
      return
    }
    if (!viewState.showStrategyManagementTabs.value && tab !== 'aiResearch') {
      viewState.activeTab.value = 'aiResearch'
      return
    }
    if (tab === 'aiResearch') {
      runHistoryModule.scheduleAIResearchRunsAutoRefresh()
    } else {
      runHistoryModule.clearAIResearchRunsAutoRefresh()
    }
  })

  watch(viewState.showAIResearchTab, visible => {
    if (visible && viewState.activeTab.value !== 'aiResearch') {
      viewState.activeTab.value = 'aiResearch'
      void configProfilesModule.loadAIResearchConfigProfiles()
      return
    }
    if (visible) {
      void configProfilesModule.loadAIResearchConfigProfiles()
    }
    if (!visible && viewState.activeTab.value === 'aiResearch') {
      viewState.activeTab.value = 'gallery'
    }
  }, { immediate: true })

  watch(
    () => [
      aiResearchForm.symbol,
      aiResearchForm.market_data_asset_type,
      aiResearchForm.timeframe,
      aiResearchForm.start_date,
      aiResearchForm.end_date,
    ],
    () => {
      marketData.aiResearchPrecheckResult.value = null
      marketData.aiResearchPrecheckError.value = ''
      marketData.scheduleAIResearchDataPrecheck()
    },
  )

  onUnmounted(() => {
    runHistoryState.aiResearchRunsAutoRefreshActive = false
    runHistoryModule.clearAIResearchRunsAutoRefresh()
  })

  return {
    t,
    route,
    router,
    strategyStore,
    ...viewState,
    ...dialogs,
    ...runtimeProjections,
    ...runRecordAdapters,
    ...marketData,
    ...aiResearchTaskState,
    ...pipelineSelectors,
    ...mandateModule,
    ...configProfilesModule,
    ...requestBuilderModule,
    ...runHistoryModule,
    ...taskLifecycle,
    ...runExecution,
    ...runtimeOperations,
    aiResearchRunning,
    aiResearchResult,
    aiResearchRunsLoading,
    aiResearchRuns,
    aiResearchRunsAutoRefreshTimer: runHistoryState.aiResearchRunsAutoRefreshTimer,
    aiResearchRunsAutoRefreshActive: runHistoryState.aiResearchRunsAutoRefreshActive,
    aiResearchPaperStartingRunId,
    aiResearchPaperReviewingRunId,
    aiResearchLiveHandoffLoadingRunId,
    aiResearchStrategyViewingRunId,
    aiResearchPaperReviews,
    aiResearchLiveHandoffs,
    aiResearchLiveHandoffApprovingRunId,
    aiResearchLiveTradingPreparingRunId,
    aiResearchLiveTradingActivatingRunId,
    aiResearchLiveTradingDeactivatingRunId,
    aiResearchForm,
    hydrateLiveHandoffFromRunRecord,
    paperStartedPipeline: (record: AIStrategyResearchRunRecord) => buildPaperStartedPipeline(record, t),
    aiResearchRequestSnapshotFromRunRecord,
    aiResearchTaskFromRunRecord,
    AI_RESEARCH_RUNS_AUTO_REFRESH_MS,
    AI_RESEARCH_STAGE_LABELS,
    AI_RESEARCH_RUN_STATUS_LABELS,
    AI_RESEARCH_PAPER_REVIEW_STATUS_LABELS,
    AI_RESEARCH_PAPER_RULE_STATUS_LABELS,
    AI_RESEARCH_LIVE_READINESS_STATUS_LABELS,
    AI_RESEARCH_LIVE_HANDOFF_STATUS_LABELS,
    AI_RESEARCH_PIPELINE_STEP_STATUS_LABELS,
    AI_RESEARCH_WORKFLOW_STEPS,
    todayIsoDate,
    DEFAULT_AI_RESEARCH_START_DATE,
    DEFAULT_AI_RESEARCH_END_DATE,
    DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS,
    PAPER_GATEWAY_CONFIG_PLACEHOLDER,
    LIVE_GATEWAY_CONFIG_PLACEHOLDER,
    AI_RESEARCH_CONFIG_ERROR_MESSAGES,
    AI_RESEARCH_TASK_POLL_INTERVAL_MS,
    AI_RESEARCH_TASK_MIN_TIMEOUT_MS,
    AI_RESEARCH_TASK_MAX_TIMEOUT_MS,
    sleep,
    aiResearchAutoContinuationSource,
    aiResearchTaskAutoContinuationSourceFromTask,
    formatMetric,
    gateGapListFromUnknown,
    gateGapText,
    formatTaskProgress,
    taskLatestIterationLabel,
    taskLatestIterationMetric,
    taskLatestIterationProgress,
    taskLatestIterationDiagnostics,
    strategyGenerationText,
    formatDateTime,
    isRecord,
    containsRedactedSecret,
    optionalNumber,
    optionalBoolean,
    outOfSampleRatioPct,
    parseResearchDate,
    mandateQualityGateSummary,
    hasConfigKey,
    configStringValue,
    formatAIResearchConfigJson,
    aiResearchEventTagType,
    aiResearchVersionStatusTagType,
    aiResearchVersionMetric,
    aiResearchVersionMetricLabel,
    researchRecordUsesManualCommission,
    resolvedAIResearchTaskBacktestEnvironment,
    aiResearchTaskExplicitFields,
    aiResearchTaskUsesManualCommission,
    aiResearchTaskRestoredCommission,
    enabledQualityGate,
    researchIterationNextActions,
    iterationProgress,
    iterationProgressLabel,
    iterationProgressTagType,
    iterationProgressDeltaText,
    canApproveLiveHandoff,
    liveHandoffApprovalLabel,
    liveTradingPrepareSummary,
    isLiveTradingPreparedForRecord,
    isLiveTradingActivatedForRecord,
    liveTradingPreparedAtFromPipeline,
    isPaperTradingTargetMissing,
    paperStartButtonLabel,
    continuationSourceLabel,
    continuationIterationPayload,
    stringListFromUnknown,
    isPaperTradingStartFailure,
    paperReviewFailureText,
    pipelineStage,
    pipelineStageLabel,
    aiResearchRunStatusLabel,
    paperReviewStatusLabel,
    paperReviewRuleStatusLabel,
    paperReviewRuleGapText,
    paperReviewDispositionLabel,
    liveReadinessStatusLabel,
    liveHandoffStatusLabel,
    pipelineStepStatusLabel,
    pipelineStepTagType,
    pipelineStepIterationText,
    aiResearchStageLabel,
    liveReadinessChecklistForReview,
    liveReadinessChecklistForRecord,
    liveReadinessExpiresAtForRecord,
    paperReviewLockFromPayload,
    paperReviewLockForRecord,
    paperReviewLockSummary,
    paperReviewLockStopResultText,
    liveReadinessChecklistFromPayload,
    promotionAuditFromPayload,
    paperHandoffRunRecordAssetSpecs,
    paperHandoffRunRecordBacktestEnvironment,
    paperTradingStartError,
    paperMonitoringPlanFromHandoff,
    researchRunTimestamp,
    stringFromUnknown,
    routeQueryText,
    nullableString,
    stringArrayFromUnknown,
    uniqueTextItems,
    arrayFromUnknown,
  }
}
