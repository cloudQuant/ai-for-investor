import { getCurrentScope, onScopeDispose, ref } from 'vue'

import {
  portfolioAnalyticsTasksApi,
  type PortfolioAnalyticsTask,
  type PortfolioAnalyticsTaskCreate,
} from '@/api/portfolioAnalyticsTasks'

const TERMINAL_STATES: ReadonlySet<PortfolioAnalyticsTask['state']> = new Set([
  'succeeded',
  'unavailable',
  'failed',
  'cancelled',
  'expired',
])

const MAX_CONSECUTIVE_POLL_ERRORS = 5
const NON_RETRYABLE_HTTP_STATUSES = new Set([400, 401, 403, 404, 422])

function isRetryablePollError(caught: unknown): boolean {
  if (!caught || typeof caught !== 'object') return true
  const maybeStatus = (caught as { response?: { status?: unknown }; status?: unknown })
  const status = typeof maybeStatus.response?.status === 'number'
    ? maybeStatus.response.status
    : typeof maybeStatus.status === 'number'
      ? maybeStatus.status
      : null
  return status === null || !NON_RETRYABLE_HTTP_STATUSES.has(status)
}

interface TaskSelection {
  portfolioRef: string
  membershipVersion: number
}

export function usePortfolioAnalyticsTask(options?: { intervalMs?: number }) {
  const task = ref<PortfolioAnalyticsTask | null>(null)
  const loading = ref(false)
  const error = ref<unknown>(null)
  const polling = ref(false)

  let selection: TaskSelection | null = null
  let timer: number | null = null
  let generation = 0
  let consecutivePollErrors = 0

  function isTerminal(value: PortfolioAnalyticsTask | null): boolean {
    return Boolean(value && TERMINAL_STATES.has(value.state))
  }

  function stopPolling() {
    polling.value = false
    if (timer !== null && typeof window !== 'undefined') {
      window.clearTimeout(timer)
      timer = null
    }
  }

  function schedulePoll(expectedGeneration: number) {
    if (
      typeof window === 'undefined'
      || !selection
      || !task.value
      || isTerminal(task.value)
      || expectedGeneration !== generation
    ) {
      stopPolling()
      return
    }
    stopPolling()
    polling.value = true
    timer = window.setTimeout(() => {
      timer = null
      polling.value = false
      void refresh()
    }, options?.intervalMs ?? 2_500)
  }

  async function start(
    selected: TaskSelection,
    payload: PortfolioAnalyticsTaskCreate,
  ): Promise<PortfolioAnalyticsTask | null> {
    generation += 1
    consecutivePollErrors = 0
    const current = generation
    stopPolling()
    selection = { ...selected }
    task.value = null
    error.value = null
    loading.value = true
    try {
      const response = await portfolioAnalyticsTasksApi.createTask(
        selected.portfolioRef,
        selected.membershipVersion,
        payload,
      )
      if (current !== generation) return null
      task.value = response
      schedulePoll(current)
      return response
    } catch (caught) {
      if (current === generation) error.value = caught
      return null
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function refresh(): Promise<PortfolioAnalyticsTask | null> {
    const selected = selection
    const currentTask = task.value
    const current = generation
    if (!selected || !currentTask || currentTask.state === 'cancelled') return currentTask

    loading.value = true
    error.value = null
    try {
      const response = await portfolioAnalyticsTasksApi.getTask(
        selected.portfolioRef,
        selected.membershipVersion,
        currentTask.task_ref,
      )
      if (current !== generation) return null
      consecutivePollErrors = 0
      task.value = response
      if (!isTerminal(response)) schedulePoll(current)
      else stopPolling()
      return response
    } catch (caught) {
      if (current === generation) {
        error.value = caught
        consecutivePollErrors += 1
        if (isRetryablePollError(caught) && consecutivePollErrors < MAX_CONSECUTIVE_POLL_ERRORS) {
          schedulePoll(current)
        } else {
          stopPolling()
        }
      }
      return null
    } finally {
      if (current === generation) loading.value = false
    }
  }

  async function cancel(): Promise<PortfolioAnalyticsTask | null> {
    const selected = selection
    const currentTask = task.value
    if (!selected || !currentTask) return null
    generation += 1
    consecutivePollErrors = 0
    const current = generation
    stopPolling()
    loading.value = true
    error.value = null
    try {
      const response = await portfolioAnalyticsTasksApi.cancelTask(
        selected.portfolioRef,
        selected.membershipVersion,
        currentTask.task_ref,
      )
      if (current !== generation) return null
      task.value = response
      if (!isTerminal(response)) schedulePoll(current)
      return response
    } catch (caught) {
      if (current === generation) error.value = caught
      return null
    } finally {
      if (current === generation) loading.value = false
    }
  }

  function reset() {
    generation += 1
    consecutivePollErrors = 0
    stopPolling()
    selection = null
    task.value = null
    error.value = null
    loading.value = false
  }

  function dispose() {
    reset()
  }

  if (getCurrentScope()) onScopeDispose(dispose)

  return { task, loading, error, polling, start, refresh, cancel, reset, dispose }
}
