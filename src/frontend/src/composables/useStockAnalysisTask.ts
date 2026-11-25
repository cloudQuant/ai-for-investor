import { onBeforeUnmount, ref } from 'vue'

import {
  stockAnalysisApi,
  type StockAnalysisResult,
  type StockAnalysisTask,
} from '@/api/stockAnalysis'

const TERMINAL_STATUSES: Array<StockAnalysisTask['status']> = ['completed', 'failed', 'cancelled']
const STATUS_RANK: Record<StockAnalysisTask['status'], number> = {
  pending: 0,
  running: 1,
  completed: 2,
  failed: 2,
  cancelled: 2,
}

export function isStockAnalysisTerminalStatus(status?: StockAnalysisTask['status'] | null): boolean {
  return Boolean(status && TERMINAL_STATUSES.includes(status))
}

export function useStockAnalysisTask(taskId: string, options?: { intervalMs?: number }) {
  const task = ref<StockAnalysisTask | null>(null)
  const result = ref<StockAnalysisResult | null>(null)
  const loading = ref(false)
  const error = ref<unknown>(null)
  const polling = ref(false)
  let timer: number | null = null
  let generation = 0
  let inFlight: Promise<StockAnalysisTask | null> | null = null
  let activeRequestToken: object | null = null

  function refreshTask(): Promise<StockAnalysisTask | null> {
    if (inFlight) return inFlight
    const requestGeneration = generation
    const requestToken = {}
    const request = (async () => {
      loading.value = true
      error.value = null
      try {
        const nextTask = await stockAnalysisApi.getTask(taskId)
        if (requestGeneration !== generation || nextTask.task_id !== taskId) return null
        const previous = task.value
        if (
          previous
          && (
            STATUS_RANK[nextTask.status] < STATUS_RANK[previous.status]
            || (
              STATUS_RANK[nextTask.status] === STATUS_RANK[previous.status]
              && nextTask.progress < previous.progress
            )
          )
        ) return previous
        task.value = nextTask
        if (nextTask.status === 'completed') {
          const nextResult = await stockAnalysisApi.getTaskResult(taskId)
          if (requestGeneration !== generation || nextResult.task_id !== taskId) return null
          result.value = nextResult
        }
        if (isStockAnalysisTerminalStatus(nextTask.status)) {
          stopPolling()
        }
        return nextTask
      } catch (caught) {
        if (requestGeneration === generation) {
          error.value = caught
          stopPolling()
        }
        throw caught
      } finally {
        if (activeRequestToken === requestToken) {
          activeRequestToken = null
          inFlight = null
        }
        if (activeRequestToken === null) {
          loading.value = false
        }
      }
    })()
    activeRequestToken = requestToken
    inFlight = request
    return request
  }

  function scheduleNext() {
    if (!polling.value || timer !== null) return
    timer = window.setTimeout(() => {
      timer = null
      void refreshTask().catch(() => undefined).finally(() => {
        if (polling.value && !isStockAnalysisTerminalStatus(task.value?.status)) {
          scheduleNext()
        }
      })
    }, options?.intervalMs ?? 2500)
  }

  function startPolling() {
    if (polling.value) return
    polling.value = true
    void refreshTask().catch(() => undefined)
    scheduleNext()
  }

  function stopPolling() {
    generation++
    activeRequestToken = null
    inFlight = null
    polling.value = false
    if (timer !== null) {
      window.clearTimeout(timer)
      timer = null
    }
  }

  onBeforeUnmount(stopPolling)

  return {
    task,
    result,
    loading,
    error,
    polling,
    refreshTask,
    startPolling,
    stopPolling,
  }
}
