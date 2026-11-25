import { computed, type Ref } from 'vue'
import {
  strategyApi,
  type AIStrategyLiveHandoffPackage,
  type AIStrategyPaperTradingReview,
  type AIStrategyPaperTradingStart,
  type AIStrategyPipelineStep,
  type AIStrategyPipelineSummary,
  type AIStrategyPromotionAuditItem,
  type AIStrategyResearchIteration,
  type AIStrategyResearchRunRecord,
  type AIStrategyResearchRunResponse,
} from '@/api/strategy'
import type { AIResearchFormState } from './aiResearchConstants'
import {
  aiResearchStageLabel,
  continuationIterationPayload,
  continuationSourceLabel,
  formatMetric,
  gateGapListFromUnknown,
  isLiveTradingActivatedForRecord,
  isLiveTradingPreparedForRecord,
  isPaperTradingStartFailure,
  isPaperTradingTargetMissing,
  liveHandoffStatusLabel,
  liveReadinessChecklistForRecord,
  liveReadinessExpiresAtForRecord,
  paperMonitoringPlanFromHandoff,
  paperReviewFailureText,
  paperReviewLockForRecord,
  paperReviewStatusLabel,
  pipelineStepIterationText,
  promotionAuditFromPayload,
  strategyGenerationText,
  stringListFromUnknown,
  taskLatestIterationDiagnostics,
} from './aiResearchFormatters'
import {
  paperStartFailedRunRecord as buildPaperStartFailedRunRecord,
  paperStartedRunRecord as buildPaperStartedRunRecord,
  reviewedRunRecord,
} from './aiResearchRunTransforms'
import { isRecord, optionalNumber, stringFromUnknown } from './aiResearchValueAdapters'
import type { useAIResearchRuntimeProjections } from './useAIResearchRuntimeProjections'

type RuntimeProjections = ReturnType<typeof useAIResearchRuntimeProjections>

export interface AIResearchPipelineSelectorsDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  aiResearchForm: AIResearchFormState
  aiResearchRunning: Ref<boolean>
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  aiResearchRuns: Ref<AIStrategyResearchRunRecord[]>
  aiResearchPaperReviews: Record<string, AIStrategyPaperTradingReview>
  aiResearchLiveHandoffs: Record<string, AIStrategyLiveHandoffPackage>
  aiResearchTaskId: Ref<string>
  aiResearchTaskStatus: Ref<string>
  aiResearchTaskStage: Ref<string>
  aiResearchTaskPipeline: Ref<AIStrategyPipelineSummary | null>
  aiResearchTaskRequestSnapshot: Ref<Record<string, unknown> | null>
  aiResearchTaskContinuedFromRunId: Ref<string>
  aiResearchTaskContinuationSource: Ref<string>
  aiResearchTaskContinuationContext: Ref<Record<string, unknown>>
  aiResearchTaskPaperWorkspaceId: Ref<string>
  aiResearchTaskPaperUnitId: Ref<string>
  aiResearchTaskPaperStarted: Ref<boolean>
  aiResearchTaskLiveWorkspaceId: Ref<string>
  aiResearchTaskLiveUnitId: Ref<string>
  aiResearchTaskLivePrepared: Ref<boolean>
  aiResearchTaskLatestIteration: Ref<Record<string, unknown> | null>
  aiResearchTaskBestIteration: Ref<Record<string, unknown> | null>
  bestStrategyIdForRecord: (record: AIStrategyResearchRunRecord) => string
  outOfSampleStatusLabel: RuntimeProjections['outOfSampleStatusLabel']
  outOfSampleValidationFromHandoff: RuntimeProjections['outOfSampleValidationFromHandoff']
  iterationOutOfSampleValidation: (iteration: AIStrategyResearchIteration) => ReturnType<
    RuntimeProjections['iterationOutOfSampleValidation']
  >
  paperEnvironmentItems: RuntimeProjections['paperEnvironmentItems']
  researchRuntimeItems: RuntimeProjections['researchRuntimeItems']
  researchResultFromRunRecord: (record: AIStrategyResearchRunRecord) => AIStrategyResearchRunResponse
  hydrateLiveHandoffFromRunRecord: (record: AIStrategyResearchRunRecord) => void
}

export function useAIResearchPipelineSelectors(deps: AIResearchPipelineSelectorsDeps) {
  const { t, aiResearchForm } = deps

  function liveHandoffForRunId(runId: string): AIStrategyLiveHandoffPackage | null {
    return deps.aiResearchLiveHandoffs[runId] ?? null
  }

  function liveHandoffForRecord(
    record: AIStrategyResearchRunRecord,
  ): AIStrategyLiveHandoffPackage | null {
    return liveHandoffForRunId(record.run_id) ?? record.live_handoff ?? null
  }

  function liveHandoffStatusForRecord(record: AIStrategyResearchRunRecord) {
    const handoff = liveHandoffForRecord(record)
    return String(handoff?.status || record.pipeline?.live_handoff_status || '').trim()
  }

  function liveHandoffLocksPaperActions(record: AIStrategyResearchRunRecord) {
    const status = liveHandoffStatusForRecord(record)
    return Boolean(
      isLiveTradingPreparedForRecord(record)
      || record.live_handoff_approval
      || ['ready_for_approval', 'approved_for_live', 'approval_rejected'].includes(status),
    )
  }

  function isLiveHandoffRejected(record: AIStrategyResearchRunRecord) {
    const handoff = liveHandoffForRecord(record) ?? record.live_handoff
    const approval = handoff?.approval ?? record.live_handoff_approval
    return Boolean(
      approval?.decision === 'rejected'
      || handoff?.approval_status === 'rejected'
      || handoff?.status === 'approval_rejected'
      || record.pipeline?.live_handoff_status === 'approval_rejected',
    )
  }

  function canStartPaperFromRecord(record: AIStrategyResearchRunRecord) {
    return Boolean(
      record.achieved
      && deps.bestStrategyIdForRecord(record)
      && (!record.paper_trading_started || isPaperTradingTargetMissing(record)),
    )
  }

  function canReviewPaperFromRecord(record: AIStrategyResearchRunRecord) {
    return Boolean(
      record.paper_trading_started
      && record.paper_workspace_id
      && record.paper_unit_id
      && !isPaperTradingTargetMissing(record)
      && !liveHandoffLocksPaperActions(record),
    )
  }

  function paperReviewForRecord(
    record: AIStrategyResearchRunRecord,
  ): AIStrategyPaperTradingReview | null {
    const review = deps.aiResearchPaperReviews[record.run_id]
    if (review) return review
    if (!record.paper_review_status) return null
    return {
      run_id: record.run_id,
      research_workspace_id: record.research_workspace_id,
      paper_workspace_id: record.paper_workspace_id,
      paper_unit_id: record.paper_unit_id,
      paper_trading_started: record.paper_trading_started,
      monitoring_plan: record.paper_monitoring_plan ?? [],
      evaluations: record.paper_review_evaluations ?? [],
      ready_for_live: Boolean(record.paper_review_ready_for_live),
      status: record.paper_review_status,
      reviewed_at: record.paper_reviewed_at,
      live_readiness_checklist: liveReadinessChecklistForRecord(record),
      live_readiness_expires_at: liveReadinessExpiresAtForRecord(record),
      pipeline: record.pipeline,
      next_actions: record.paper_review_next_actions ?? [],
    } satisfies AIStrategyPaperTradingReview
  }

  function canBuildLiveHandoffFromRecord(record: AIStrategyResearchRunRecord) {
    const review = paperReviewForRecord(record)
    return Boolean(
      record.paper_trading_started
      && review?.ready_for_live
      && review.status === 'ready_for_live_candidate'
      && !liveHandoffLocksPaperActions(record),
    )
  }

  function canPrepareLiveTradingFromRecord(record: AIStrategyResearchRunRecord) {
    const handoff = liveHandoffForRecord(record)
    return Boolean(
      handoff
      && handoff.ready_for_live
      && handoff.status === 'approved_for_live'
      && handoff.approval?.approved
      && !isLiveTradingPreparedForRecord(record),
    )
  }

  function canActivateLiveTradingFromRecord(record: AIStrategyResearchRunRecord) {
    const handoff = liveHandoffForRecord(record)
    const approval = handoff?.approval ?? record.live_handoff_approval
    return Boolean(
      isLiveTradingPreparedForRecord(record)
      && !isLiveTradingActivatedForRecord(record)
      && approval?.approved,
    )
  }

  function canDeactivateLiveTradingFromRecord(record: AIStrategyResearchRunRecord) {
    return Boolean(isLiveTradingPreparedForRecord(record))
  }

  function canContinueResearchFromRunRecord(record: AIStrategyResearchRunRecord) {
    return Boolean(
      deps.bestStrategyIdForRecord(record)
      && !record.achieved
      && (
        record.iteration_count > 0
        || (record.iterations ?? []).length > 0
        || record.status === 'backtest_submission_failed'
        || record.status === 'cancelled'
        || record.status === 'interrupted'
        || record.pipeline?.current_stage === 'backtest_failed'
        || record.pipeline?.current_stage === 'cancelled'
        || record.pipeline?.current_stage === 'interrupted'
      ),
    )
  }

  function continuationSourceForRecord(record: AIStrategyResearchRunRecord) {
    if (isLiveHandoffRejected(record)) return 'live_handoff_rejected'
    if (
      ['needs_research_review', 'live_readiness_expired'].includes(
        String(record.paper_review_status || ''),
      )
      && !record.paper_review_ready_for_live
    ) {
      return 'paper_review'
    }
    if (isPaperTradingStartFailure(record)) return 'paper_trading_failed'
    if (
      canContinueResearchFromRunRecord(record)
      && (record.status === 'cancelled' || record.pipeline?.current_stage === 'cancelled')
    ) {
      return 'research_cancelled'
    }
    if (
      canContinueResearchFromRunRecord(record)
      && (record.status === 'interrupted' || record.pipeline?.current_stage === 'interrupted')
    ) {
      return 'research_interrupted'
    }
    if (canContinueResearchFromRunRecord(record)) return 'research_failure'
    return ''
  }

  function canContinueResearchFromPaperIssue(record: AIStrategyResearchRunRecord) {
    const source = continuationSourceForRecord(record)
    return Boolean(
      deps.bestStrategyIdForRecord(record) &&
      (
        source === 'paper_review'
        || source === 'paper_trading_failed'
        || source === 'live_handoff_rejected'
      ),
    )
  }

  function canContinueResearchFromPaperReview(record: AIStrategyResearchRunRecord) {
    return canContinueResearchFromPaperIssue(record)
  }

  function continuationSummaryForRecord(record: AIStrategyResearchRunRecord) {
    const context = isRecord(record.continuation_context) ? record.continuation_context : {}
    const source = stringFromUnknown(record.continuation_source, stringFromUnknown(context.source))
    const parentRunId = stringFromUnknown(record.continued_from_run_id, stringFromUnknown(context.run_id))
    if (!source && !parentRunId) return ''
    const label = continuationSourceLabel(source)
    return parentRunId ? `${label} · 上轮 ${parentRunId}` : label
  }

  function aiResearchContinuationRecord(runId: string) {
    const currentRecord = deps.aiResearchResult.value?.run_record
    if (currentRecord?.run_id === runId) return currentRecord
    return deps.aiResearchRuns.value.find(record => record.run_id === runId) ?? null
  }

  function continuationQualityGateFailures(
    record: AIStrategyResearchRunRecord,
    source: string,
  ) {
    const failures = new Set<string>()
    if (source === 'paper_review') {
      const failedEvaluations = (record.paper_review_evaluations ?? []).filter(
        item => String(item.status || '') === 'failed' || item.passed === false,
      )
      failedEvaluations.forEach(item => {
        const failure = paperReviewFailureText(item)
        if (failure) failures.add(failure)
      })
      if (!failures.size && record.paper_review_status === 'live_readiness_expired') {
        failures.add('实盘候选复核已过期，需要重新复核模拟交易指标后再进入实盘审批。')
      }
      for (const item of record.paper_review_next_actions ?? []) {
        if (item.trim()) failures.add(item.trim())
      }
    } else if (source === 'paper_trading_failed') {
      const error = stringFromUnknown(record.pipeline?.paper_trading_error)
      failures.add(error ? `模拟交易启动失败：${error}` : '模拟交易启动失败。')
    } else if (source === 'live_handoff_rejected') {
      failures.add('实盘交接审批被驳回，需要处理审批意见后重新投研并重新进入模拟复核。')
      const comment = stringFromUnknown(record.live_handoff_approval?.comment)
      if (comment) failures.add(`实盘交接驳回意见：${comment}`)
      for (const item of record.next_actions ?? []) {
        if (item.trim()) failures.add(item.trim())
      }
    } else {
      const iteration = continuationIterationPayload(record)
      stringListFromUnknown(iteration?.quality_gate_failures).forEach(item => failures.add(item))
      const reason = stringFromUnknown(iteration?.failure_reason)
      if (reason) failures.add(reason)
      for (const item of record.next_actions ?? []) {
        if (item.trim()) failures.add(item.trim())
      }
    }
    return [...failures]
  }

  function aiResearchContinuationContextForRecord(
    record: AIStrategyResearchRunRecord,
    source = continuationSourceForRecord(record),
  ): Record<string, unknown> | undefined {
    const runId = record.run_id.trim()
    if (!runId || !source) return undefined

    const context: Record<string, unknown> = { source, run_id: runId }

    const failures = continuationQualityGateFailures(record, source)
    if (failures.length) context.quality_gate_failures = failures
    if (isRecord(record.best_metrics)) context.metrics = { ...record.best_metrics }
    if (record.next_actions?.length) context.next_actions = [...record.next_actions]
    if (record.pipeline) context.pipeline = { ...record.pipeline }
    if (record.asset_specs) context.asset_specs = { ...record.asset_specs }
    if (record.backtest_environment) context.backtest_environment = { ...record.backtest_environment }
    if (record.best_diagnostics) context.diagnostics = { ...record.best_diagnostics }

    if (source === 'paper_review') {
      context.paper_review_status = record.paper_review_status
      context.paper_reviewed_at = record.paper_reviewed_at
      const evaluations = [...(record.paper_review_evaluations ?? [])].map(item => ({ ...item }))
      if (evaluations.length) context.paper_review_evaluations = evaluations
      if (record.paper_review_next_actions?.length) {
        context.paper_review_next_actions = [...record.paper_review_next_actions]
      }
    } else if (source === 'paper_trading_failed') {
      context.paper_trading_error = stringFromUnknown(record.pipeline?.paper_trading_error)
    } else if (source === 'live_handoff_rejected') {
      const handoff = liveHandoffForRecord(record) ?? record.live_handoff
      context.live_handoff_status = liveHandoffStatusForRecord(record) || 'approval_rejected'
      if (handoff) context.live_handoff = { ...handoff }
      if (record.live_handoff_approval) {
        context.live_handoff_approval = { ...record.live_handoff_approval }
      }
      if (record.live_readiness_checklist?.length) {
        context.live_readiness_checklist = record.live_readiness_checklist.map(item => ({ ...item }))
      }
      if (record.paper_review_evaluations?.length) {
        context.paper_review_evaluations = record.paper_review_evaluations.map(item => ({ ...item }))
      }
      context.paper_review_status = record.paper_review_status
      context.paper_reviewed_at = record.paper_reviewed_at
    } else {
      const iteration = continuationIterationPayload(record)
      if (iteration?.failure_reason) {
        context.failure_reason = stringFromUnknown(iteration.failure_reason)
      }
      if (iteration?.quality_gate_failures) {
        context.previous_quality_gate_failures = stringListFromUnknown(
          iteration.quality_gate_failures,
        )
      }
    }

    return context
  }

  function aiResearchContinuationContext(): Record<string, unknown> | undefined {
    const runId = aiResearchForm.continue_from_run_id.trim()
    const source = aiResearchForm.continuation_source.trim()
    if (!runId || !source) return undefined

    const record = aiResearchContinuationRecord(runId)
    if (!record) return { source, run_id: runId }
    return aiResearchContinuationContextForRecord(record, source)
  }

  function pipelineStepDetailText(
    step: AIStrategyPipelineStep,
    pipeline?: AIStrategyPipelineSummary | null,
  ) {
    const details: string[] = []
    const iteration = pipelineStepIterationText(step)
    if (iteration) details.push(iteration)
    if (step.key === 'validation' && step.validation_status) {
      details.push(`样本外 ${deps.outOfSampleStatusLabel(step.validation_status)}`)
    }
    if (step.review_status) details.push(`复核 ${paperReviewStatusLabel(step.review_status)}`)
    if (step.key === 'live_handoff') {
      const handoffStatus = stringFromUnknown(pipeline?.live_handoff_status)
      if (handoffStatus) details.push(`交接 ${liveHandoffStatusLabel(handoffStatus)}`)
      const blockerCount = optionalNumber(pipeline?.live_handoff_blocker_count)
      if (blockerCount !== null && blockerCount > 0) details.push(`${formatMetric(blockerCount, 0)} 项阻塞`)
    }
    return details.join(' ')
  }

  function paperStartedRunRecord(
    record: AIStrategyResearchRunRecord,
    paper: AIStrategyPaperTradingStart,
  ) {
    return buildPaperStartedRunRecord(record, paper, t)
  }

  function paperStartFailedRunRecord(
    record: AIStrategyResearchRunRecord,
    paper: AIStrategyPaperTradingStart,
  ) {
    return buildPaperStartFailedRunRecord(record, paper, t)
  }

  function applyPaperStartToCurrentResult(
    runId: string,
    paper: AIStrategyPaperTradingStart,
    runRecord: AIStrategyResearchRunRecord,
  ) {
    const current = deps.aiResearchResult.value
    if (!current || current.run_id !== runId) return
    deps.aiResearchResult.value = {
      ...current,
      paper_trading: paper,
      paper_monitoring_plan:
        paperMonitoringPlanFromHandoff(paper.handoff) ?? current.paper_monitoring_plan,
      pipeline: runRecord.pipeline ?? current.pipeline,
      promotion_audit: runRecord.promotion_audit ?? current.promotion_audit,
      next_actions: runRecord.next_actions ?? current.next_actions,
      run_record: runRecord,
    }
  }

  function applyResearchRunRecordToCurrentResult(runRecord: AIStrategyResearchRunRecord) {
    const current = deps.aiResearchResult.value
    if (!current || current.run_id !== runRecord.run_id) return
    deps.hydrateLiveHandoffFromRunRecord(runRecord)
    const restored = deps.researchResultFromRunRecord(runRecord)
    const keepLocalFailedPaper = Boolean(
      !restored.paper_trading
      && isPaperTradingStartFailure(runRecord)
      && current.paper_trading?.started === false,
    )
    deps.aiResearchResult.value = {
      ...current,
      ...restored,
      research_workspace: current.research_workspace ?? restored.research_workspace,
      iterations: restored.iterations.length ? restored.iterations : current.iterations,
      best_strategy: current.best_strategy ?? restored.best_strategy,
      paper_trading: restored.paper_trading ?? (keepLocalFailedPaper ? current.paper_trading : null),
      message: current.message,
    }
  }

  function applyPaperReviewToCurrentResult(
    runId: string,
    runRecord: AIStrategyResearchRunRecord,
  ) {
    const current = deps.aiResearchResult.value
    if (!current || current.run_id !== runId) return
    deps.aiResearchResult.value = {
      ...current,
      run_record: runRecord,
      pipeline: runRecord.pipeline ?? current.pipeline,
      next_actions: runRecord.next_actions ?? current.next_actions,
    }
  }

  const aiBestSharpe = computed(() => {
    const metrics = deps.aiResearchResult.value?.best_metrics
    const raw = metrics?.sharpe_ratio ?? metrics?.sharpe ?? null
    if (typeof raw === 'number') return raw
    if (typeof raw === 'string' && raw.trim()) return Number(raw)
    const bestIteration = deps.aiResearchResult.value?.iterations.find(
      item => item.iteration === deps.aiResearchResult.value?.best_iteration,
    )
    return bestIteration?.sharpe_ratio ?? null
  })

  const aiResearchNextActions = computed(() => deps.aiResearchResult.value?.next_actions ?? [])

  const aiResearchBestDiagnostics = computed(() => {
    const diagnostics = deps.aiResearchResult.value?.best_diagnostics
    if (!diagnostics) return null
    const summary = String(diagnostics.summary || '').trim()
    const failureCategories = diagnostics.failure_categories ?? []
    const strengths = diagnostics.strengths ?? []
    const weaknesses = diagnostics.weaknesses ?? []
    const improvementPlan = diagnostics.improvement_plan ?? []
    const diagnosticsPayload = diagnostics as Record<string, unknown>
    const gateGaps = gateGapListFromUnknown(diagnosticsPayload.gate_gaps).slice(0, 4)
    const generationText = strategyGenerationText(diagnosticsPayload.strategy_generation)
    const promotionReady = typeof diagnostics.promotion_ready === 'boolean'
      ? diagnostics.promotion_ready
      : null
    if (
      !summary
      && !failureCategories.length
      && !strengths.length
      && !weaknesses.length
      && !gateGaps.length
      && !improvementPlan.length
      && !generationText
      && promotionReady === null
    ) {
      return null
    }
    return {
      summary,
      failureCategories,
      strengths,
      weaknesses,
      gateGaps,
      improvementPlan,
      generationText,
      promotionReady,
    }
  })

  const aiResearchPipelineSteps = computed<AIStrategyPipelineStep[]>(() => {
    const pipeline = deps.aiResearchResult.value?.pipeline
    if (!pipeline) return []
    if (pipeline.steps?.length) return pipeline.steps
    if (!pipeline.current_stage) return []
    return [
      {
        key: pipeline.current_stage,
        label: aiResearchStageLabel(pipeline.current_stage),
        status: pipeline.ready_for_live ? 'completed' : 'running',
        error: pipeline.paper_trading_error,
      },
    ]
  })

  const aiResearchPromotionAudit = computed<AIStrategyPromotionAuditItem[]>(() =>
    promotionAuditFromPayload(
      deps.aiResearchResult.value?.promotion_audit
        ?? deps.aiResearchResult.value?.run_record?.promotion_audit,
    ),
  )

  const aiResearchCurrentPaperFailed = computed(() => {
    const pipeline = deps.aiResearchResult.value?.pipeline
    return Boolean(
      pipeline?.current_stage === 'paper_trading_failed'
      || pipeline?.paper_trading_error,
    )
  })

  const aiResearchCurrentPaperTargetMissing = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && isPaperTradingTargetMissing(record))
  })

  const aiResearchPaperStatusText = computed(() => {
    if (aiResearchCurrentPaperFailed.value) return '模拟启动失败'
    if (aiResearchCurrentPaperTargetMissing.value) return '模拟目标丢失'
    return deps.aiResearchResult.value?.paper_trading?.started
      || deps.aiResearchResult.value?.run_record?.paper_trading_started
      ? t('strategy.aiResearchPaperStarted')
      : t('strategy.aiResearchPaperNotStarted')
  })

  const aiResearchTaskStageLabel = computed(() =>
    aiResearchStageLabel(deps.aiResearchTaskStage.value || deps.aiResearchTaskStatus.value),
  )

  const aiResearchTaskContinuationSummary = computed(() => {
    const snapshot = deps.aiResearchTaskRequestSnapshot.value ?? {}
    const context = Object.keys(deps.aiResearchTaskContinuationContext.value).length
      ? deps.aiResearchTaskContinuationContext.value
      : isRecord(snapshot.continuation_context)
        ? snapshot.continuation_context
        : {}
    const source = stringFromUnknown(
      deps.aiResearchTaskContinuationSource.value,
      stringFromUnknown(context.source),
    )
    const parentRunId = stringFromUnknown(
      deps.aiResearchTaskContinuedFromRunId.value,
      stringFromUnknown(snapshot.continue_from_run_id, stringFromUnknown(context.run_id)),
    )
    if (!source && !parentRunId) return ''
    const label = continuationSourceLabel(source)
    return parentRunId ? `${label} · 上轮 ${parentRunId}` : label
  })

  const aiResearchTaskPaperStatusText = computed(() => {
    const error = String(deps.aiResearchTaskPipeline.value?.paper_trading_error || '').trim()
    if (error) return `模拟失败 ${error}`
    if (deps.aiResearchTaskPaperStarted.value) return '模拟已启动'
    if (deps.aiResearchTaskPaperWorkspaceId.value || deps.aiResearchTaskPaperUnitId.value) return '模拟已创建'
    return ''
  })

  const aiResearchTaskLiveStatusText = computed(() => {
    const pipeline = deps.aiResearchTaskPipeline.value
    if (deps.aiResearchTaskLivePrepared.value || pipeline?.live_trading_prepared) return '实盘已准备'
    if (
      deps.aiResearchTaskLiveWorkspaceId.value
      || deps.aiResearchTaskLiveUnitId.value
      || pipeline?.live_workspace_id
      || pipeline?.live_unit_id
    ) {
      return '实盘已创建'
    }
    return ''
  })

  const aiResearchTaskPipelineSteps = computed<AIStrategyPipelineStep[]>(() => {
    const pipeline = deps.aiResearchTaskPipeline.value
    if (!pipeline) return []
    if (pipeline.steps?.length) return pipeline.steps
    if (!pipeline.current_stage) return []
    return [
      {
        key: pipeline.current_stage,
        label: aiResearchStageLabel(pipeline.current_stage),
        status: pipeline.ready_for_live ? 'completed' : 'running',
        error: pipeline.paper_trading_error,
      },
    ]
  })

  const aiResearchTaskLatestDiagnostics = computed(() =>
    taskLatestIterationDiagnostics(deps.aiResearchTaskLatestIteration.value),
  )

  const aiResearchTaskBestIterationDisplay = computed(() => {
    const best = deps.aiResearchTaskBestIteration.value
    if (!best) return null
    const latest = deps.aiResearchTaskLatestIteration.value
    if (!latest) return best
    const bestIteration = optionalNumber(best.iteration)
    const latestIteration = optionalNumber(latest.iteration)
    if (bestIteration === null || latestIteration === null) return best
    return bestIteration === latestIteration ? null : best
  })

  const aiResearchContinuationEnabled = computed(() =>
    Boolean(aiResearchForm.seed_strategy_id || aiResearchForm.continue_from_run_id),
  )

  const aiResearchContinuationLabel = computed(() =>
    continuationSourceLabel(aiResearchForm.continuation_source || ''),
  )

  const aiResearchCurrentContinuationSummary = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return record ? continuationSummaryForRecord(record) : ''
  })

  const canCancelAIResearchTask = computed(() =>
    deps.aiResearchRunning.value
    && Boolean(deps.aiResearchTaskId.value)
    && typeof (strategyApi as { cancelAIResearchTask?: unknown }).cancelAIResearchTask === 'function',
  )

  const canContinueAIResearchTask = computed(() =>
    !deps.aiResearchRunning.value
    && Boolean(deps.aiResearchTaskId.value)
    && ['failed', 'cancelled'].includes(String(deps.aiResearchTaskStatus.value || '').toLowerCase())
    && Boolean(
      (
        deps.aiResearchResult.value?.run_record
        && (
          canContinueResearchFromRunRecord(deps.aiResearchResult.value.run_record)
          || canContinueResearchFromPaperIssue(deps.aiResearchResult.value.run_record)
        )
      )
      || deps.aiResearchTaskBestIteration.value
      || deps.aiResearchTaskLatestIteration.value,
    )
    && typeof (strategyApi as { continueAIResearchTask?: unknown }).continueAIResearchTask === 'function',
  )

  const canRetryAIResearchTask = computed(() =>
    !deps.aiResearchRunning.value
    && Boolean(deps.aiResearchTaskId.value)
    && ['failed', 'cancelled'].includes(String(deps.aiResearchTaskStatus.value || '').toLowerCase())
    && isRecord(deps.aiResearchTaskRequestSnapshot.value)
    && !canContinueAIResearchTask.value,
  )

  const canViewBestStrategyFromCurrentResult = computed(() =>
    Boolean(
      deps.aiResearchResult.value?.best_strategy
      || (
        deps.aiResearchResult.value?.run_record
        && deps.bestStrategyIdForRecord(deps.aiResearchResult.value.run_record)
      ),
    ),
  )

  const canStartPaperFromCurrentResult = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && canStartPaperFromRecord(record))
  })

  const canOpenPaperFromCurrentResult = computed(() =>
    Boolean(
      !(
        deps.aiResearchResult.value?.run_record
        && isPaperTradingTargetMissing(deps.aiResearchResult.value.run_record)
      )
      && (
        deps.aiResearchResult.value?.paper_trading?.started
        || (
          deps.aiResearchResult.value?.run_record?.paper_trading_started
          && deps.aiResearchResult.value?.run_record?.paper_workspace_id
        )
      ),
    ),
  )

  const canReviewPaperFromCurrentResult = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && canReviewPaperFromRecord(record))
  })

  const canContinueResearchFromCurrentPaperReview = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && canContinueResearchFromPaperReview(record))
  })

  const canContinueResearchFromCurrentPaperIssue = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && canContinueResearchFromPaperIssue(record))
  })

  const canContinueResearchFromCurrentRunRecord = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && canContinueResearchFromRunRecord(record))
  })

  const aiResearchCurrentPaperReview = computed(() => {
    const result = deps.aiResearchResult.value
    const record = result?.run_record
    if (!result || !record) return null
    return paperReviewForRecord(record)
  })

  const aiResearchCurrentPaperReviewLock = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return record ? paperReviewLockForRecord(record) : null
  })

  const canBuildLiveHandoffFromCurrentResult = computed(() => {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && canBuildLiveHandoffFromRecord(record))
  })

  const aiResearchCurrentLiveHandoff = computed(() => {
    const result = deps.aiResearchResult.value
    if (!result) return null
    return result.run_record ? liveHandoffForRecord(result.run_record) : liveHandoffForRunId(result.run_id)
  })

  const aiResearchCurrentPaperEnvironment = computed(() => {
    const result = deps.aiResearchResult.value
    if (!result) return []
    return deps.paperEnvironmentItems(result.paper_trading?.handoff ?? result.run_record?.paper_handoff)
  })

  const aiResearchCurrentRuntimeEnvironment = computed(() => {
    const result = deps.aiResearchResult.value
    if (!result) return []
    return deps.researchRuntimeItems(
      result.run_record,
      result.paper_trading?.handoff ?? result.run_record?.paper_handoff ?? null,
    )
  })

  const aiResearchBestGateEvaluations = computed(
    () => deps.aiResearchResult.value?.best_quality_gate_evaluations ?? [],
  )

  const aiResearchOutOfSampleValidation = computed(() => {
    const result = deps.aiResearchResult.value
    if (!result) return null
    const handoffValidation = deps.outOfSampleValidationFromHandoff(result.paper_trading?.handoff)
    if (handoffValidation) return handoffValidation
    const bestIteration = result.iterations.find(item => item.iteration === result.best_iteration)
      ?? result.iterations.find(item => item.passed)
      ?? result.iterations[result.iterations.length - 1]
    return bestIteration ? deps.iterationOutOfSampleValidation(bestIteration) : null
  })

  return {
    aiBestSharpe,
    aiResearchNextActions,
    aiResearchBestDiagnostics,
    aiResearchPipelineSteps,
    aiResearchPromotionAudit,
    aiResearchCurrentPaperFailed,
    aiResearchCurrentPaperTargetMissing,
    aiResearchPaperStatusText,
    aiResearchTaskStageLabel,
    aiResearchTaskContinuationSummary,
    aiResearchTaskPaperStatusText,
    aiResearchTaskLiveStatusText,
    aiResearchTaskPipelineSteps,
    aiResearchTaskLatestDiagnostics,
    aiResearchTaskBestIterationDisplay,
    aiResearchContinuationEnabled,
    aiResearchContinuationLabel,
    aiResearchCurrentContinuationSummary,
    canCancelAIResearchTask,
    canContinueAIResearchTask,
    canRetryAIResearchTask,
    canViewBestStrategyFromCurrentResult,
    canStartPaperFromCurrentResult,
    canOpenPaperFromCurrentResult,
    canReviewPaperFromCurrentResult,
    canContinueResearchFromCurrentPaperReview,
    canContinueResearchFromCurrentPaperIssue,
    canContinueResearchFromCurrentRunRecord,
    aiResearchCurrentPaperReview,
    aiResearchCurrentPaperReviewLock,
    canBuildLiveHandoffFromCurrentResult,
    aiResearchCurrentLiveHandoff,
    aiResearchCurrentPaperEnvironment,
    aiResearchCurrentRuntimeEnvironment,
    aiResearchBestGateEvaluations,
    aiResearchOutOfSampleValidation,
    liveHandoffForRunId,
    liveHandoffForRecord,
    liveHandoffStatusForRecord,
    liveHandoffLocksPaperActions,
    isLiveHandoffRejected,
    canStartPaperFromRecord,
    canReviewPaperFromRecord,
    paperReviewForRecord,
    canBuildLiveHandoffFromRecord,
    canPrepareLiveTradingFromRecord,
    canActivateLiveTradingFromRecord,
    canDeactivateLiveTradingFromRecord,
    canContinueResearchFromRunRecord,
    continuationSourceForRecord,
    canContinueResearchFromPaperIssue,
    canContinueResearchFromPaperReview,
    continuationSummaryForRecord,
    aiResearchContinuationRecord,
    continuationQualityGateFailures,
    aiResearchContinuationContextForRecord,
    aiResearchContinuationContext,
    pipelineStepDetailText,
    paperStartedRunRecord,
    paperStartFailedRunRecord,
    applyPaperStartToCurrentResult,
    applyResearchRunRecordToCurrentResult,
    reviewedRunRecord,
    applyPaperReviewToCurrentResult,
  }
}
