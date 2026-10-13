import type { Ref } from 'vue'
import type { MarketAssetType, MarketDataCapabilitiesResponse } from '@/api/marketData'
import type {
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunRequest,
  AIStrategyResearchRunResponse,
  AIStrategyResearchTaskResponse,
  InvestmentMandateResponse,
} from '@/api/strategy'
import type { strategyApi } from '@/api/strategy'
import { stringFromUnknown } from './aiResearchValueAdapters'
import type {
  AIResearchMandateSnapshot,
  AIResearchPreparedSubmission,
  AIResearchRunnableInput,
  AIResearchSubmissionSnapshot,
  AIResearchTaskFormState,
} from './aiResearchTaskTypes'
import type { AIResearchTaskState } from './useAIResearchTaskState'
import type { AIResearchTaskApi } from './useAIResearchTaskLifecycle'

export interface AIResearchRunExecutionOptions {
  api: AIResearchTaskApi
  taskState: AIResearchTaskState
  aiResearchForm: Pick<AIResearchTaskFormState, 'prompt'>
  aiResearchRunning: Ref<boolean>
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  aiResearchMandate: Ref<InvestmentMandateResponse | null>
  canRetryAIResearchTask: () => boolean
  aiResearchRunnableInput: () => AIResearchRunnableInput | null
  aiResearchContinuationRunnableInput: (
    source: AIResearchTaskState['aiResearchTaskAutoContinuationSource']['value']
  ) => AIResearchRunnableInput | null
  captureAIResearchSubmission: (input: AIResearchRunnableInput) => AIResearchSubmissionSnapshot
  loadAIResearchMandate: (mandateId: string) => Promise<unknown>
  ensureAIResearchMandateConfirmed: (
    snapshot: AIResearchMandateSnapshot
  ) => Promise<InvestmentMandateResponse | null>
  resolveAIResearchMarketDataCapabilitiesForAction: () => Promise<{
    capabilities: MarketDataCapabilitiesResponse | null
    lastKnownBridgeEnabled: boolean
  }>
  ensureAIResearchStrictLocalMarketDataReady: (
    submission: AIResearchSubmissionSnapshot,
    capabilities: MarketDataCapabilitiesResponse | null,
    lastKnownBridgeEnabled: boolean
  ) => Promise<boolean>
  applyAIResearchMarketDataBridgeIntent: (
    request: AIStrategyResearchRunRequest,
    capabilities: MarketDataCapabilitiesResponse | null,
    assetType: MarketAssetType | undefined
  ) => AIStrategyResearchRunRequest
  prepareAIResearchOutputForRun: () => void
  runAIResearchRequest: (
    payload: AIStrategyResearchRunRequest
  ) => Promise<AIStrategyResearchRunResponse>
  applyCompletedAIResearchResult: (result: AIStrategyResearchRunResponse) => Promise<void>
  handleAIResearchRunError: (error: unknown) => boolean
  clearAIResearchContinuation: () => void
  scheduleAIResearchRunsAutoRefresh: () => void
  aiResearchTaskPollTimeoutMs: (
    payload?: AIStrategyResearchRunRequest,
    task?: AIStrategyResearchTaskResponse
  ) => number
  pollAIResearchTask: (
    task: AIStrategyResearchTaskResponse,
    timeoutMs?: number
  ) => Promise<AIStrategyResearchRunResponse>
  setAIResearchConfigProfileFromRunRecord: (record: AIStrategyResearchRunRecord) => void
  upsertAIResearchRunRecord: (record: AIStrategyResearchRunRecord) => void
  loadAIResearchRuns: () => Promise<unknown>
  notifyAIResearchResult: (result: AIStrategyResearchRunResponse) => void
}

type ContinueAIResearchRun = NonNullable<typeof strategyApi.continueAIResearchRun>

export function useAIResearchRunExecution({
  api,
  taskState,
  aiResearchForm,
  aiResearchRunning,
  aiResearchResult,
  aiResearchMandate,
  canRetryAIResearchTask,
  aiResearchRunnableInput,
  aiResearchContinuationRunnableInput,
  captureAIResearchSubmission,
  loadAIResearchMandate,
  ensureAIResearchMandateConfirmed,
  resolveAIResearchMarketDataCapabilitiesForAction,
  ensureAIResearchStrictLocalMarketDataReady,
  applyAIResearchMarketDataBridgeIntent,
  prepareAIResearchOutputForRun,
  runAIResearchRequest,
  applyCompletedAIResearchResult,
  handleAIResearchRunError,
  clearAIResearchContinuation,
  scheduleAIResearchRunsAutoRefresh,
  aiResearchTaskPollTimeoutMs,
  pollAIResearchTask,
  setAIResearchConfigProfileFromRunRecord,
  upsertAIResearchRunRecord,
  loadAIResearchRuns,
  notifyAIResearchResult,
}: AIResearchRunExecutionOptions) {
  function applyCanonicalAIResearchPrompt(
    result: AIStrategyResearchRunResponse,
    shouldUseServerGeneratedPrompt: boolean
  ) {
    if (!shouldUseServerGeneratedPrompt) return
    const canonicalPrompt = stringFromUnknown(result.run_record?.prompt)
    if (canonicalPrompt) aiResearchForm.prompt = canonicalPrompt
  }

  async function continueAIResearchFromRunRecord(
    record: AIStrategyResearchRunRecord,
    continueRun: ContinueAIResearchRun,
    prepared?: AIResearchPreparedSubmission
  ) {
    const input = prepared?.input ?? aiResearchRunnableInput()
    if (!input) return
    let submission = prepared?.submission
    if (!submission) {
      try {
        submission = captureAIResearchSubmission(input)
      } catch (error) {
        handleAIResearchRunError(error)
        return
      }
    }
    const mandate = await ensureAIResearchMandateConfirmed(submission.mandate)
    if (!mandate) return
    let request: AIStrategyResearchRunRequest = {
      ...submission.request,
      mandate_id: mandate.id,
    }
    const capabilityDecision = await resolveAIResearchMarketDataCapabilitiesForAction()
    if (!await ensureAIResearchStrictLocalMarketDataReady(
      submission,
      capabilityDecision.capabilities,
      capabilityDecision.lastKnownBridgeEnabled,
    )) return
    request = applyAIResearchMarketDataBridgeIntent(
      request,
      capabilityDecision.capabilities,
      submission.marketDataAssetType,
    )

    prepareAIResearchOutputForRun()
    aiResearchRunning.value = true
    taskState.resetAIResearchTaskState()
    taskState.aiResearchCancelRequested.value = false
    try {
      const overrides: Partial<AIStrategyResearchRunRequest> & Record<string, unknown> = {
        ...request,
      }
      delete overrides.continue_from_run_id
      delete overrides.seed_strategy_id
      delete overrides.continuation_context
      const task = await continueRun(
        record.run_id,
        { overrides },
        record.research_workspace_id
      )
      const result = await pollAIResearchTask(
        task,
        aiResearchTaskPollTimeoutMs(request, task)
      )
      applyCanonicalAIResearchPrompt(result, input.shouldUseServerGeneratedPrompt)
      await applyCompletedAIResearchResult(result)
    } catch (error) {
      handleAIResearchRunError(error)
    } finally {
      aiResearchRunning.value = false
      scheduleAIResearchRunsAutoRefresh()
    }
  }

  async function continueAIResearchFromTaskSnapshot() {
    const taskId = taskState.aiResearchTaskId.value
    const continueTask = api.continueAIResearchTask
    if (!taskId || typeof continueTask !== 'function' || aiResearchRunning.value) return
    const autoContinuationSource = taskState.aiResearchTaskAutoContinuationSource.value
    const input = aiResearchContinuationRunnableInput(autoContinuationSource)
    if (!input) return
    let submission: AIResearchSubmissionSnapshot
    try {
      submission = captureAIResearchSubmission(input)
    } catch (error) {
      handleAIResearchRunError(error)
      return
    }
    if (
      autoContinuationSource
      && aiResearchMandate.value?.id !== autoContinuationSource.mandateId
    ) {
      await loadAIResearchMandate(autoContinuationSource.mandateId)
    }
    const mandate = await ensureAIResearchMandateConfirmed(submission.mandate)
    if (!mandate) return
    let request: AIStrategyResearchRunRequest = {
      ...submission.request,
      mandate_id: mandate.id,
    }
    const capabilityDecision = await resolveAIResearchMarketDataCapabilitiesForAction()
    if (!await ensureAIResearchStrictLocalMarketDataReady(
      submission,
      capabilityDecision.capabilities,
      capabilityDecision.lastKnownBridgeEnabled,
    )) return
    request = applyAIResearchMarketDataBridgeIntent(
      request,
      capabilityDecision.capabilities,
      submission.marketDataAssetType,
    )

    prepareAIResearchOutputForRun()
    aiResearchRunning.value = true
    taskState.aiResearchCancelRequested.value = false
    taskState.aiResearchTaskError.value = ''
    try {
      const overrides: Partial<AIStrategyResearchRunRequest> & Record<string, unknown> = { ...request }
      const task = await continueTask(taskId, { overrides })
      aiResearchResult.value = await pollAIResearchTask(
        task,
        aiResearchTaskPollTimeoutMs(request, task)
      )
      if (input.shouldUseServerGeneratedPrompt) {
        const canonicalPrompt = stringFromUnknown(aiResearchResult.value.run_record?.prompt)
        if (canonicalPrompt) aiResearchForm.prompt = canonicalPrompt
      }
      if (aiResearchResult.value.run_record) {
        setAIResearchConfigProfileFromRunRecord(aiResearchResult.value.run_record)
        upsertAIResearchRunRecord(aiResearchResult.value.run_record)
      } else {
        await loadAIResearchRuns()
      }
      notifyAIResearchResult(aiResearchResult.value)
    } catch (error) {
      handleAIResearchRunError(error)
    } finally {
      aiResearchRunning.value = false
      scheduleAIResearchRunsAutoRefresh()
    }
  }

  async function retryAIResearchFromTaskSnapshot() {
    if (!canRetryAIResearchTask() || aiResearchRunning.value) return
    clearAIResearchContinuation()
    await runAIResearchLoop()
  }

  async function runAIResearchLoop() {
    await runAIResearchPreparedLoop()
  }

  async function runAIResearchPreparedLoop(prepared?: AIResearchPreparedSubmission) {
    const input = prepared?.input ?? aiResearchRunnableInput()
    if (!input) return
    let submission = prepared?.submission
    if (!submission) {
      try {
        submission = captureAIResearchSubmission(input)
      } catch (error) {
        handleAIResearchRunError(error)
        return
      }
    }
    const mandate = await ensureAIResearchMandateConfirmed(submission.mandate)
    if (!mandate) return
    let request: AIStrategyResearchRunRequest = {
      ...submission.request,
      mandate_id: mandate.id,
    }
    const capabilityDecision = await resolveAIResearchMarketDataCapabilitiesForAction()
    if (!await ensureAIResearchStrictLocalMarketDataReady(
      submission,
      capabilityDecision.capabilities,
      capabilityDecision.lastKnownBridgeEnabled,
    )) return
    request = applyAIResearchMarketDataBridgeIntent(
      request,
      capabilityDecision.capabilities,
      submission.marketDataAssetType,
    )

    prepareAIResearchOutputForRun()
    aiResearchRunning.value = true
    taskState.resetAIResearchTaskState()
    taskState.aiResearchCancelRequested.value = false
    try {
      const result = await runAIResearchRequest(request)
      applyCanonicalAIResearchPrompt(result, input.shouldUseServerGeneratedPrompt)
      await applyCompletedAIResearchResult(result)
    } catch (error) {
      handleAIResearchRunError(error)
    } finally {
      aiResearchRunning.value = false
      scheduleAIResearchRunsAutoRefresh()
    }
  }

  return {
    applyCanonicalAIResearchPrompt,
    continueAIResearchFromRunRecord,
    continueAIResearchFromTaskSnapshot,
    retryAIResearchFromTaskSnapshot,
    runAIResearchLoop,
    runAIResearchPreparedLoop,
  }
}
