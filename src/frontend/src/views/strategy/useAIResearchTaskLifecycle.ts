import type { Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type {
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
  AIStrategyResearchTaskResponse,
} from '@/api/strategy'
import type { strategyApi } from '@/api/strategy'
import type { AIResearchTaskState } from './useAIResearchTaskState'

export const AI_RESEARCH_TASK_POLL_INTERVAL_MS = 1500
export const AI_RESEARCH_TASK_MIN_TIMEOUT_MS = 10 * 60 * 1000
export const AI_RESEARCH_TASK_MAX_TIMEOUT_MS = 8 * 60 * 60 * 1000

export type AIResearchTaskApi = Pick<typeof strategyApi, 'runAIResearchLoop'> & Partial<Pick<
  typeof strategyApi,
  | 'submitAIResearchTask'
  | 'getAIResearchTask'
  | 'listAIResearchTasks'
  | 'cancelAIResearchTask'
  | 'continueAIResearchTask'
>>

export interface AIResearchTaskLifecycleOptions {
  t: (key: string) => string
  api: AIResearchTaskApi
  taskState: AIResearchTaskState
  aiResearchRunning: Ref<boolean>
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  restoreAIResearchResultFromTask: (
    task: AIStrategyResearchTaskResponse
  ) => Promise<AIStrategyResearchRunResponse | null>
  syncAIResearchFormFromResult: (
    result: AIStrategyResearchRunResponse | null | undefined
  ) => void
  setAIResearchConfigProfileFromRunRecord: (record: AIStrategyResearchRunRecord) => void
  upsertAIResearchRunRecord: (record: AIStrategyResearchRunRecord) => void
  loadAIResearchRuns: () => Promise<unknown>
  refreshAIResearchRunRecord: (
    runId: string,
    workspaceId?: string | null
  ) => Promise<AIStrategyResearchRunRecord | null>
  researchResultFromRunRecord: (
    record: AIStrategyResearchRunRecord
  ) => AIStrategyResearchRunResponse
  notifyAIResearchResult: (result: AIStrategyResearchRunResponse) => void
  scheduleAIResearchRunsAutoRefresh: () => void
}

export function sleep(ms: number) {
  return new Promise(resolve => window.setTimeout(resolve, ms))
}

export function useAIResearchTaskLifecycle({
  t,
  api,
  taskState,
  aiResearchRunning,
  aiResearchResult,
  restoreAIResearchResultFromTask,
  syncAIResearchFormFromResult,
  setAIResearchConfigProfileFromRunRecord,
  upsertAIResearchRunRecord,
  loadAIResearchRuns,
  refreshAIResearchRunRecord,
  researchResultFromRunRecord,
  notifyAIResearchResult,
  scheduleAIResearchRunsAutoRefresh,
}: AIResearchTaskLifecycleOptions) {
  function aiResearchErrorMessage(error: unknown) {
    if (error instanceof Error && error.message.trim()) return error.message.trim()
    const message = String(error || '').trim()
    return message || t('strategy.aiResearchRunFailed')
  }

  async function runAIResearchRequest(
    payload: Parameters<typeof strategyApi.runAIResearchLoop>[0]
  ): Promise<AIStrategyResearchRunResponse> {
    if (typeof api.submitAIResearchTask !== 'function' || typeof api.getAIResearchTask !== 'function') {
      return api.runAIResearchLoop(payload)
    }

    const task = await api.submitAIResearchTask(payload)
    return pollAIResearchTask(task, taskState.aiResearchTaskPollTimeoutMs(payload, task))
  }

  async function pollAIResearchTask(
    initialTask: AIStrategyResearchTaskResponse,
    timeoutMs = taskState.aiResearchTaskPollTimeoutMs(undefined, initialTask)
  ): Promise<AIStrategyResearchRunResponse> {
    let task = initialTask
    taskState.applyAIResearchTaskStatus(task)
    const deadline = Date.now() + timeoutMs
    const maxPolls = Math.max(
      240,
      Math.ceil(timeoutMs / AI_RESEARCH_TASK_POLL_INTERVAL_MS) + 2
    )
    for (let attempt = 0; attempt < maxPolls; attempt += 1) {
      if (task.status === 'completed') {
        if (task.result) return task.result
        const restoredResult = await restoreAIResearchResultFromTask(task)
        if (restoredResult) return restoredResult
        throw new Error('AI research task completed without a result')
      }
      if (taskState.isAIResearchTaskCancelled(task)) {
        const restoredResult = await restoreAIResearchResultFromTask(task)
        if (restoredResult) return restoredResult
        throw new Error('AI_RESEARCH_CANCELLED')
      }
      if (taskState.isAIResearchTaskTerminal(task)) {
        const restoredResult = await restoreAIResearchResultFromTask(task)
        if (restoredResult) return restoredResult
        throw new Error(task.error || task.message || 'AI research task failed')
      }
      if (Date.now() > deadline) {
        break
      }
      if (typeof api.getAIResearchTask !== 'function') {
        throw new Error('AI research task polling is unavailable')
      }
      task = await api.getAIResearchTask(task.task_id)
      taskState.applyAIResearchTaskStatus(task)
      if (!taskState.isAIResearchTaskTerminal(task)) {
        await sleep(AI_RESEARCH_TASK_POLL_INTERVAL_MS)
      }
    }
    throw new Error(`AI research task polling timed out after ${Math.round(timeoutMs / 1000)}s`)
  }

  async function restoreActiveAIResearchTask() {
    if (aiResearchRunning.value || typeof api.listAIResearchTasks !== 'function') return
    try {
      const response = await api.listAIResearchTasks(true, 5)
      const task = response.items.find(item => !taskState.isAIResearchTaskTerminal(item))
      if (task) {
        aiResearchRunning.value = true
        taskState.applyAIResearchTaskSnapshotToForm(task)
        aiResearchResult.value = await pollAIResearchTask(task)
      } else {
        if (aiResearchResult.value) return
        const recentResponse = await api.listAIResearchTasks(false, 5)
        const restoredTask = recentResponse.items.find(taskState.isRestorableAIResearchTask)
        if (!restoredTask) return
        taskState.applyAIResearchTaskSnapshotToForm(restoredTask)
        taskState.applyAIResearchTaskStatus(restoredTask)
        aiResearchResult.value = restoredTask.result ?? await restoreAIResearchResultFromTask(restoredTask)
      }
      if (!aiResearchResult.value) return
      syncAIResearchFormFromResult(aiResearchResult.value)
      if (aiResearchResult.value.run_record) {
        setAIResearchConfigProfileFromRunRecord(aiResearchResult.value.run_record)
        upsertAIResearchRunRecord(aiResearchResult.value.run_record)
      } else {
        await loadAIResearchRuns()
      }
      notifyAIResearchResult(aiResearchResult.value)
    } catch (error) {
      taskState.aiResearchTaskError.value = aiResearchErrorMessage(error)
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      aiResearchRunning.value = false
      scheduleAIResearchRunsAutoRefresh()
    }
  }

  async function cancelAIResearchTask() {
    const taskId = taskState.aiResearchTaskId.value
    const cancelTask = api.cancelAIResearchTask
    if (!taskId || typeof cancelTask !== 'function') return
    taskState.aiResearchCancelling.value = true
    taskState.aiResearchCancelRequested.value = true
    try {
      const task = await cancelTask(taskId)
      taskState.applyAIResearchTaskStatus(task)
      taskState.aiResearchTaskError.value = ''
      aiResearchRunning.value = false
      if (task.run_id) {
        try {
          const record = await refreshAIResearchRunRecord(task.run_id, task.research_workspace_id)
          if (record) {
            aiResearchResult.value = researchResultFromRunRecord(record)
          }
        } catch {
          await loadAIResearchRuns()
        }
      }
      ElMessage.success(
        task.child_cancelled && task.cancelled_backtest_task_id
          ? 'AI投研任务已取消，当前回测任务已同步取消'
          : 'AI投研任务已取消'
      )
    } catch {
      ElMessage.error(t('strategy.aiResearchRunFailed'))
    } finally {
      taskState.aiResearchCancelling.value = false
    }
  }

  return {
    aiResearchErrorMessage,
    runAIResearchRequest,
    pollAIResearchTask,
    restoreActiveAIResearchTask,
    cancelAIResearchTask,
  }
}
