import { ElMessage, ElMessageBox } from 'element-plus'
import type { Ref } from 'vue'
import { strategyApi } from '@/api/strategy'
import type {
  AIStrategyLiveHandoffApprovalRequest,
  AIStrategyLiveHandoffPackage,
  AIStrategyLiveTradingPrepare,
  AIStrategyPaperTradingReview,
  AIStrategyPaperTradingStart,
  AIStrategyPipelineStep,
  AIStrategyResearchIteration,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
  AIStrategyResearchVersion,
} from '@/api/strategy'
import type { Strategy } from '@/types'
import { isRecord, stringFromUnknown } from './aiResearchValueAdapters'
import type { useAIResearchRuntimeProjections } from './useAIResearchRuntimeProjections'
import type { useStrategyPageDialogs } from './useStrategyPageDialogs'

type ViewStrategy = ReturnType<typeof useStrategyPageDialogs>['viewStrategy']
type BestStrategyIdForRecord = ReturnType<typeof useAIResearchRuntimeProjections>['bestStrategyIdForRecord']
type PaperStartRequest = Parameters<typeof strategyApi.startAIResearchPaperTrading>[1]
type LivePrepareRequest = Parameters<typeof strategyApi.prepareAIResearchLiveTrading>[1]

export interface AIResearchRuntimeOperationsOptions {
  t: (key: string) => string
  aiResearchPaperStartingRunId: Ref<string>
  aiResearchStrategyViewingRunId: Ref<string>
  aiResearchPaperReviewingRunId: Ref<string>
  aiResearchLiveHandoffLoadingRunId: Ref<string>
  aiResearchLiveHandoffApprovingRunId: Ref<string>
  aiResearchLiveTradingPreparingRunId: Ref<string>
  aiResearchLiveTradingActivatingRunId: Ref<string>
  aiResearchLiveTradingDeactivatingRunId: Ref<string>
  aiResearchLiveHandoffs: Record<string, AIStrategyLiveHandoffPackage>
  aiResearchPaperReviews: Record<string, AIStrategyPaperTradingReview>
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  aiResearchPaperStartRequest: (record: AIStrategyResearchRunRecord) => PaperStartRequest
  aiResearchLivePrepareRequest: (record: AIStrategyResearchRunRecord) => LivePrepareRequest
  refreshAIResearchRunRecord: (
    runId: string,
    researchWorkspaceId?: string | null
  ) => Promise<AIStrategyResearchRunRecord | null>
  upsertAIResearchRunRecord: (record: AIStrategyResearchRunRecord) => void
  applyPaperStartToCurrentResult: (
    runId: string,
    paper: AIStrategyPaperTradingStart,
    runRecord: AIStrategyResearchRunRecord
  ) => void
  applyPaperReviewToCurrentResult: (
    runId: string,
    runRecord: AIStrategyResearchRunRecord
  ) => void
  applyResearchRunRecordToCurrentResult: (runRecord: AIStrategyResearchRunRecord) => void
  paperStartFailedRunRecord: (
    record: AIStrategyResearchRunRecord,
    paper: AIStrategyPaperTradingStart
  ) => AIStrategyResearchRunRecord
  paperStartedRunRecord: (
    record: AIStrategyResearchRunRecord,
    paper: AIStrategyPaperTradingStart
  ) => AIStrategyResearchRunRecord
  reviewedRunRecord: (
    record: AIStrategyResearchRunRecord,
    review: AIStrategyPaperTradingReview
  ) => AIStrategyResearchRunRecord
  bestStrategyFromRunRecord: (record: AIStrategyResearchRunRecord) => Strategy | null
  bestStrategyIdForRecord: BestStrategyIdForRecord
  liveHandoffForRecord: (
    record: AIStrategyResearchRunRecord
  ) => AIStrategyLiveHandoffPackage | null
  canApproveLiveHandoff: (
    handoff: AIStrategyLiveHandoffPackage | null | undefined
  ) => boolean
  canPrepareLiveTradingFromRecord: (record: AIStrategyResearchRunRecord) => boolean
  canActivateLiveTradingFromRecord: (record: AIStrategyResearchRunRecord) => boolean
  canDeactivateLiveTradingFromRecord: (record: AIStrategyResearchRunRecord) => boolean
  notifyAIResearchConfigError: (error: unknown) => boolean
  viewStrategy: ViewStrategy
}

export function useAIResearchRuntimeOperations(options: AIResearchRuntimeOperationsOptions) {
  const {
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
    aiResearchPaperStartRequest,
    aiResearchLivePrepareRequest,
    refreshAIResearchRunRecord,
    upsertAIResearchRunRecord,
    applyPaperStartToCurrentResult,
    applyPaperReviewToCurrentResult,
    applyResearchRunRecordToCurrentResult,
    paperStartFailedRunRecord,
    paperStartedRunRecord,
    reviewedRunRecord,
    bestStrategyFromRunRecord,
    bestStrategyIdForRecord,
    liveHandoffForRecord,
    canApproveLiveHandoff,
    canPrepareLiveTradingFromRecord,
    canActivateLiveTradingFromRecord,
    canDeactivateLiveTradingFromRecord,
    notifyAIResearchConfigError,
    viewStrategy,
  } = options

async function startPaperFromResearchRecord(record: AIStrategyResearchRunRecord) {
    aiResearchPaperStartingRunId.value = record.run_id
    try {
      const paper = await strategyApi.startAIResearchPaperTrading(
        record.run_id,
        aiResearchPaperStartRequest(record)
      )
      const responseRecord = paper.run_record ?? null
      if (!paper.started) {
        const failedRecord = responseRecord ?? paperStartFailedRunRecord(record, paper)
        upsertAIResearchRunRecord(failedRecord)
        applyPaperStartToCurrentResult(record.run_id, paper, failedRecord)
        try {
          await refreshAIResearchRunRecord(record.run_id, record.research_workspace_id)
        } catch {
          // Keep the local failed start state visible even if history refresh fails.
        }
        ElMessage.error(t('strategy.aiResearchPaperStartFailed'))
        return
      }
      const updatedRecord = responseRecord ?? paperStartedRunRecord(record, paper)
      upsertAIResearchRunRecord(updatedRecord)
      applyPaperStartToCurrentResult(record.run_id, paper, updatedRecord)
      try {
        await refreshAIResearchRunRecord(record.run_id, record.research_workspace_id)
      } catch {
        // Keep the local started state visible even if history refresh fails.
      }
      ElMessage.success(t('strategy.aiResearchPaperStartedSuccess'))
    } catch (error) {
      if (notifyAIResearchConfigError(error)) return
      try {
        await refreshAIResearchRunRecord(record.run_id, record.research_workspace_id)
      } catch {
        // Keep the original start failure visible even if history refresh fails.
      }
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchPaperStartingRunId.value = ''
    }
  }

async function startPaperFromCurrentResult() {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await startPaperFromResearchRecord(record)
  }

async function viewBestStrategyFromCurrentResult() {
    const result = aiResearchResult.value
    if (!result) return
    if (result.best_strategy) {
      viewStrategy(result.best_strategy)
      return
    }
    const record = result.run_record
    if (!record) return
    await viewStrategyFromResearchRecord(record)
  }

async function viewResearchIterationStrategy(item: AIStrategyResearchIteration) {
    if (item.strategy.code.trim()) {
      viewStrategy(item.strategy)
      return
    }
    if (!item.strategy.id) return
    aiResearchStrategyViewingRunId.value = aiResearchResult.value?.run_id || item.strategy.id
    try {
      const strategy = await strategyApi.get(item.strategy.id)
      viewStrategy(strategy)
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchStrategyViewingRunId.value = ''
    }
  }

async function viewStrategyFromResearchRecord(record: AIStrategyResearchRunRecord) {
    const snapshotStrategy = bestStrategyFromRunRecord(record)
    if (snapshotStrategy?.code?.trim()) {
      viewStrategy(snapshotStrategy)
      return
    }
    const strategyId = bestStrategyIdForRecord(record)
    if (!strategyId) return
    aiResearchStrategyViewingRunId.value = record.run_id
    try {
      const strategy = await strategyApi.get(strategyId)
      viewStrategy(strategy)
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchStrategyViewingRunId.value = ''
    }
  }

function viewAIResearchVersionCode(version: AIStrategyResearchVersion) {
    viewStrategy({
      id: version.strategy_id || version.id,
      user_id: '',
      name: version.strategy_name || version.version_name,
      description: version.change_summary || version.ai_rationale || '',
      code: version.code,
      params: {},
      category: 'custom',
      created_at: version.created_at,
      updated_at: version.updated_at,
    })
  }

async function reviewPaperFromResearchRecord(record: AIStrategyResearchRunRecord) {
    aiResearchPaperReviewingRunId.value = record.run_id
    try {
      const review = await strategyApi.reviewAIResearchPaperTrading(
        record.run_id,
        record.research_workspace_id
      )
      aiResearchPaperReviews[record.run_id] = review
      delete aiResearchLiveHandoffs[record.run_id]
      let updatedRecord = reviewedRunRecord(record, review)
      if (review.live_handoff) {
        aiResearchLiveHandoffs[record.run_id] = review.live_handoff
        updatedRecord = liveHandoffRunRecord(updatedRecord, review.live_handoff)
      }
      upsertAIResearchRunRecord(updatedRecord)
      applyPaperReviewToCurrentResult(record.run_id, updatedRecord)
      ElMessage.success(review.ready_for_live ? t('strategy.aiResearchPaperReadyForLive') : t('strategy.aiResearchPaperReviewUpdated'))
      if (review.live_handoff) {
        ElMessage.success(review.live_handoff.ready_for_live ? t('strategy.aiResearchLiveHandoffGenerated') : t('strategy.aiResearchLiveHandoffBlocked'))
      } else if (review.ready_for_live) {
        await buildLiveHandoffFromResearchRecord(updatedRecord)
      }
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchPaperReviewingRunId.value = ''
    }
  }

async function reviewPaperFromCurrentResult() {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await reviewPaperFromResearchRecord(record)
  }

async function buildLiveHandoffFromCurrentResult() {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await buildLiveHandoffFromResearchRecord(record)
  }

async function approveCurrentLiveHandoff(decision: 'approved' | 'rejected') {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await approveLiveHandoffFromResearchRecord(record, decision)
  }

async function prepareLiveTradingFromCurrentResult() {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await prepareLiveTradingFromResearchRecord(record)
  }

async function activateLiveTradingFromCurrentResult() {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await activateLiveTradingFromResearchRecord(record)
  }

async function deactivateLiveTradingFromCurrentResult() {
    const record = aiResearchResult.value?.run_record
    if (!record) return
    await deactivateLiveTradingFromResearchRecord(record)
  }

async function buildLiveHandoffFromResearchRecord(record: AIStrategyResearchRunRecord) {
    aiResearchLiveHandoffLoadingRunId.value = record.run_id
    try {
      const handoff = await strategyApi.buildAIResearchLiveHandoff(
        record.run_id,
        record.research_workspace_id
      )
      aiResearchLiveHandoffs[record.run_id] = handoff
      const updatedRecord = liveHandoffRunRecord(record, handoff)
      upsertAIResearchRunRecord(updatedRecord)
      applyResearchRunRecordToCurrentResult(updatedRecord)
      ElMessage.success(handoff.ready_for_live ? t('strategy.aiResearchLiveHandoffGenerated') : t('strategy.aiResearchLiveHandoffBlocked'))
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchLiveHandoffLoadingRunId.value = ''
    }
  }

async function approveLiveHandoffFromResearchRecord(
    record: AIStrategyResearchRunRecord,
    decision: 'approved' | 'rejected'
  ) {
    const handoff = liveHandoffForRecord(record)
    if (!handoff || !canApproveLiveHandoff(handoff)) return
    const confirmMessage = decision === 'approved'
      ? t('strategy.aiResearchApproveLiveHandoffConfirm')
      : t('strategy.aiResearchRejectLiveHandoffConfirm')
    try {
      await ElMessageBox.confirm(confirmMessage, t('strategy.aiResearchLiveHandoffApproval'), {
        type: decision === 'approved' ? 'success' : 'warning',
      })
    } catch {
      return
    }

    aiResearchLiveHandoffApprovingRunId.value = `${record.run_id}:${decision}`
    const payload: AIStrategyLiveHandoffApprovalRequest = decision === 'approved'
      ? {
          decision,
          approver: 'web',
          comment: '前端人工审批通过',
          account_confirmed: true,
          risk_limit_confirmed: true,
          deployment_window: '人工审批通过后执行',
        }
      : {
          decision,
          approver: 'web',
          comment: '前端人工驳回',
          account_confirmed: false,
          risk_limit_confirmed: false,
        }
    try {
      const updatedHandoff = await strategyApi.approveAIResearchLiveHandoff(
        record.run_id,
        payload,
        record.research_workspace_id
      )
      aiResearchLiveHandoffs[record.run_id] = updatedHandoff
      const updatedRecord = liveHandoffRunRecord(record, updatedHandoff)
      upsertAIResearchRunRecord(updatedRecord)
      applyResearchRunRecordToCurrentResult(updatedRecord)
      ElMessage.success(decision === 'approved' ? t('strategy.aiResearchLiveHandoffApproved') : t('strategy.aiResearchLiveHandoffRejected'))
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchLiveHandoffApprovingRunId.value = ''
    }
  }

async function prepareLiveTradingFromResearchRecord(record: AIStrategyResearchRunRecord) {
    if (!canPrepareLiveTradingFromRecord(record)) return
    aiResearchLiveTradingPreparingRunId.value = record.run_id
    try {
      const prepared = await strategyApi.prepareAIResearchLiveTrading(
        record.run_id,
        aiResearchLivePrepareRequest(record),
        record.research_workspace_id
      )
      const updatedRecord = liveTradingPreparedRunRecord(record, prepared)
      upsertAIResearchRunRecord(updatedRecord)
      applyResearchRunRecordToCurrentResult(updatedRecord)
      ElMessage.success(t('strategy.aiResearchLiveUnitPrepared'))
    } catch (error) {
      if (notifyAIResearchConfigError(error)) return
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchLiveTradingPreparingRunId.value = ''
    }
  }

async function activateLiveTradingFromResearchRecord(record: AIStrategyResearchRunRecord) {
    if (!canActivateLiveTradingFromRecord(record)) return
    aiResearchLiveTradingActivatingRunId.value = record.run_id
    try {
      const activated = await strategyApi.activateAIResearchLiveTrading(
        record.run_id,
        record.research_workspace_id
      )
      if (activated.activated !== true || activated.activation_status !== 'running') {
        throw new Error('AI research live activation was not confirmed by the server')
      }
      const updatedRecord = liveTradingActivatedRunRecord(record, activated)
      upsertAIResearchRunRecord(updatedRecord)
      applyResearchRunRecordToCurrentResult(updatedRecord)
      ElMessage.success(t('strategy.aiResearchLiveUnitActivated'))
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchLiveTradingActivatingRunId.value = ''
    }
  }

async function deactivateLiveTradingFromResearchRecord(record: AIStrategyResearchRunRecord) {
    if (!canDeactivateLiveTradingFromRecord(record)) return
    aiResearchLiveTradingDeactivatingRunId.value = record.run_id
    try {
      const deactivated = await strategyApi.deactivateAIResearchLiveTrading(
        record.run_id,
        record.research_workspace_id
      )
      if (deactivated.prepared !== false || deactivated.activation_status !== 'deactivated') {
        throw new Error('AI research live deactivation was not confirmed by the server')
      }
      delete aiResearchLiveHandoffs[record.run_id]
      const updatedRecord = liveTradingDeactivatedRunRecord(record, deactivated)
      upsertAIResearchRunRecord(updatedRecord)
      applyResearchRunRecordToCurrentResult(updatedRecord)
      ElMessage.success(t('strategy.aiResearchLiveUnitDeactivated'))
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchLiveTradingDeactivatingRunId.value = ''
    }
  }

function liveHandoffRunRecord(
    record: AIStrategyResearchRunRecord,
    handoff: AIStrategyLiveHandoffPackage
  ): AIStrategyResearchRunRecord {
    const approval = handoff.approval ?? record.live_handoff_approval ?? null
    const recordPipeline = record.pipeline ?? null
    const handoffPipeline = handoff.pipeline ?? null
    return {
      ...record,
      live_handoff: handoff,
      live_handoff_approval: approval,
      pipeline: {
        ...(recordPipeline ?? {}),
        ...(handoffPipeline ?? {}),
        current_stage: handoffPipeline?.current_stage ?? recordPipeline?.current_stage ?? 'live_candidate',
        status: handoffPipeline?.status ?? recordPipeline?.status ?? record.status,
        progress: handoffPipeline?.progress ?? recordPipeline?.progress ?? (handoff.ready_for_live ? 100 : 90),
        ready_for_live: handoffPipeline?.ready_for_live ?? recordPipeline?.ready_for_live ?? handoff.ready_for_live,
        steps: handoffPipeline?.steps ?? recordPipeline?.steps ?? [],
        live_handoff_status: handoff.status,
        live_handoff_generated_at: handoff.generated_at,
        live_handoff_ready_for_live: handoff.ready_for_live,
        live_handoff_approval_required: handoff.approval_required,
        live_handoff_blocker_count: handoff.deployment_blockers.length,
        live_handoff_approval_status: approval?.decision
          ?? handoffPipeline?.live_handoff_approval_status
          ?? recordPipeline?.live_handoff_approval_status,
        live_handoff_approved: approval?.approved
          ?? handoffPipeline?.live_handoff_approved
          ?? recordPipeline?.live_handoff_approved,
        live_handoff_approved_at: approval?.approved
          ? approval.decided_at
          : handoffPipeline?.live_handoff_approved_at ?? recordPipeline?.live_handoff_approved_at,
        live_handoff_rejected_at: approval && !approval.approved
          ? approval.decided_at
          : handoffPipeline?.live_handoff_rejected_at ?? recordPipeline?.live_handoff_rejected_at,
      },
      next_actions: handoff.next_actions?.length ? handoff.next_actions : record.next_actions,
    }
  }

function liveTradingPreparedRunRecord(
    record: AIStrategyResearchRunRecord,
    prepared: AIStrategyLiveTradingPrepare
  ): AIStrategyResearchRunRecord {
    const handoff = isRecord(prepared.handoff) ? prepared.handoff : {}
    const preparedAt = stringFromUnknown(
      handoff.live_trading_prepared_at,
      new Date().toISOString()
    )
    const previousSteps = record.pipeline?.steps ?? []
    const nextSteps = upsertPipelineStep(
      upsertPipelineStep(previousSteps, {
        key: 'live_handoff',
        label: t('strategy.aiResearchLiveHandoff'),
        status: 'completed',
      }),
      {
        key: 'live_trading_prepare',
        label: t('strategy.aiResearchLivePreparation'),
        status: 'completed',
        live_trading_prepared: prepared.prepared,
        live_workspace_id: prepared.workspace.id,
        live_unit_id: prepared.unit.id,
        live_unit_locked: Boolean(prepared.unit.lock_trading || prepared.unit.lock_running),
        prepared_at: preparedAt,
      }
    )
    const liveHandoff = record.live_handoff
      ? {
          ...record.live_handoff,
          handoff: {
            ...(record.live_handoff.handoff ?? {}),
            live_trading_prepare: handoff,
          },
          next_actions: prepared.next_actions,
        }
      : record.live_handoff
    return {
      ...record,
      live_handoff: liveHandoff,
      live_workspace_id: prepared.workspace.id,
      live_workspace_name: prepared.workspace.name,
      live_unit_id: prepared.unit.id,
      live_trading_prepared: prepared.prepared,
      live_trading_prepared_at: preparedAt,
      pipeline: {
        ...(record.pipeline ?? {}),
        current_stage: 'live_trading_prepare',
        status: record.pipeline?.status ?? record.live_handoff?.status ?? record.status,
        progress: record.pipeline?.progress ?? 100,
        ready_for_live: record.pipeline?.ready_for_live ?? true,
        live_trading_prepared: prepared.prepared,
        live_trading_prepared_at: preparedAt,
        live_workspace_id: prepared.workspace.id,
        live_unit_id: prepared.unit.id,
        live_unit_locked: Boolean(prepared.unit.lock_trading || prepared.unit.lock_running),
        steps: nextSteps,
      },
      next_actions: prepared.next_actions?.length ? prepared.next_actions : record.next_actions,
    }
  }

function liveTradingActivatedRunRecord(
    record: AIStrategyResearchRunRecord,
    activated: AIStrategyLiveTradingPrepare
  ): AIStrategyResearchRunRecord {
    const preparedRecord = liveTradingPreparedRunRecord(record, activated)
    const steps = upsertPipelineStep(preparedRecord.pipeline?.steps ?? [], {
      key: 'live_trading_activation',
      label: t('strategy.livePipeline.activation'),
      status: 'completed',
    })
    return {
      ...preparedRecord,
      pipeline: {
        ...(preparedRecord.pipeline ?? {}),
        current_stage: 'live_trading_active',
        status: preparedRecord.pipeline?.status ?? preparedRecord.status,
        progress: preparedRecord.pipeline?.progress ?? 100,
        ready_for_live: preparedRecord.pipeline?.ready_for_live ?? true,
        live_handoff_activated: true,
        live_handoff_activation_status: 'running',
        live_handoff_activation_instance_id: activated.activation_instance_id ?? null,
        steps,
      },
      next_actions: activated.next_actions?.length ? activated.next_actions : preparedRecord.next_actions,
    }
  }

function liveTradingDeactivatedRunRecord(
    record: AIStrategyResearchRunRecord,
    deactivated: AIStrategyLiveTradingPrepare
  ): AIStrategyResearchRunRecord {
    const deactivatedAt = new Date().toISOString()
    const steps = upsertPipelineStep(record.pipeline?.steps ?? [], {
      key: 'live_trading_deactivation',
      label: t('strategy.livePipeline.deactivation'),
      status: 'completed',
    })
    return {
      ...record,
      live_handoff: null,
      live_handoff_approval: null,
      live_workspace_id: null,
      live_workspace_name: null,
      live_unit_id: null,
      live_trading_prepared: false,
      live_trading_prepared_at: null,
      pipeline: {
        ...(record.pipeline ?? {}),
        current_stage: 'live_handoff_deactivated',
        status: record.pipeline?.status ?? record.status,
        progress: record.pipeline?.progress ?? 100,
        ready_for_live: false,
        live_handoff_activated: false,
        live_handoff_activation_status: 'deactivated',
        live_handoff_activation_instance_id: deactivated.activation_instance_id ?? null,
        live_handoff_deactivated_at: deactivatedAt,
        live_trading_prepared: false,
        live_trading_prepared_at: null,
        live_workspace_id: null,
        live_unit_id: null,
        live_unit_locked: true,
        steps,
      },
      next_actions: deactivated.next_actions?.length ? deactivated.next_actions : record.next_actions,
    }
  }

function upsertPipelineStep(
    steps: AIStrategyPipelineStep[],
    nextStep: AIStrategyPipelineStep
  ): AIStrategyPipelineStep[] {
    const index = steps.findIndex(step => step.key === nextStep.key)
    if (index < 0) return [...steps, nextStep]
    return steps.map((step, currentIndex) =>
      currentIndex === index ? { ...step, ...nextStep } : step
    )
  }
  return {
    startPaperFromResearchRecord,
    startPaperFromCurrentResult,
    viewBestStrategyFromCurrentResult,
    viewResearchIterationStrategy,
    viewStrategyFromResearchRecord,
    viewAIResearchVersionCode,
    reviewPaperFromResearchRecord,
    reviewPaperFromCurrentResult,
    buildLiveHandoffFromCurrentResult,
    approveCurrentLiveHandoff,
    prepareLiveTradingFromCurrentResult,
    activateLiveTradingFromCurrentResult,
    deactivateLiveTradingFromCurrentResult,
    buildLiveHandoffFromResearchRecord,
    approveLiveHandoffFromResearchRecord,
    prepareLiveTradingFromResearchRecord,
    activateLiveTradingFromResearchRecord,
    deactivateLiveTradingFromResearchRecord,
    liveHandoffRunRecord,
    liveTradingPreparedRunRecord,
    liveTradingActivatedRunRecord,
    liveTradingDeactivatedRunRecord,
    upsertPipelineStep,
  }
}
