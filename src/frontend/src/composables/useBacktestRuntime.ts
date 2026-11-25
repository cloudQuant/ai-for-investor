import { ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'

import i18n from '@/i18n'
import { getErrorMessage } from '@/api/index'
import { backtestApi } from '@/api/backtest'
import type { BacktestResult, BacktestRuntimeEvent } from '@/types'
import { getAccessToken } from '@/utils/session'

function tt(key: string, named?: Record<string, unknown>): string {
  return named ? i18n.global.t(key, named) : i18n.global.t(key)
}

const WS_TOKEN_PROTOCOL = 'access-token'
const POLL_BASE_DELAY_MS = 1000
const POLL_MAX_DELAY_MS = 5000
const POLL_MAX_ATTEMPTS = 60

interface UseBacktestRuntimeOptions {
  currentResult: Ref<BacktestResult | null>
  fetchResult: (taskId: string) => Promise<BacktestResult | null>
  refreshResults: () => Promise<void>
}

export function useBacktestRuntime(options: UseBacktestRuntimeOptions) {
  const loading = ref(false)
  const currentTaskId = ref('')
  const progressInfo = ref({ progress: 0, message: '' })

  let ws: WebSocket | null = null
  let heartbeatTimer: ReturnType<typeof setInterval> | null = null
  let pollingStarted = false
  let pollAbortController: AbortController | null = null
  let runtimeGeneration = 0
  let activeTaskId = ''

  function isCurrent(taskId: string, generation: number): boolean {
    return activeTaskId === taskId && runtimeGeneration === generation
  }

  function createBacktestWebSocketProtocols(): string[] {
    const token = getAccessToken()
    if (!token) {
      return []
    }
    return [WS_TOKEN_PROTOCOL, token]
  }

  function getPollingDelayMs(attempt: number): number {
    return Math.min(POLL_BASE_DELAY_MS * 2 ** attempt, POLL_MAX_DELAY_MS)
  }

  function sleep(ms: number, signal?: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
      if (signal?.aborted) {
        reject(signal.reason)
        return
      }
      const timer = window.setTimeout(resolve, ms)
      signal?.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(signal.reason)
      }, { once: true })
    })
  }

  function parseRuntimeEvent(payload: string): BacktestRuntimeEvent | null {
    try {
      const parsed = JSON.parse(payload) as unknown
      if (!parsed || typeof parsed !== 'object' || !('type' in parsed)) {
        return null
      }
      return parsed as BacktestRuntimeEvent
    } catch {
      return null
    }
  }

  function closeWebSocket() {
    // Abort any active polling
    if (pollAbortController) {
      pollAbortController.abort()
      pollAbortController = null
    }
    if (heartbeatTimer) {
      clearInterval(heartbeatTimer)
      heartbeatTimer = null
    }
    if (ws) {
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      ws.close()
      ws = null
    }
  }

  async function finishWithResult(taskId: string, generation: number) {
    const result = await options.fetchResult(taskId)
    if (!isCurrent(taskId, generation)) return
    if (!result || result.task_id !== taskId) {
      throw new Error(tt('backtestRt.msgNoResult'))
    }
    options.currentResult.value = result
    await options.refreshResults()
    if (!isCurrent(taskId, generation)) return
    loading.value = false
    currentTaskId.value = ''
    activeTaskId = ''
    closeWebSocket()
    ElMessage.success(tt('backtestRt.msgCompleted'))
  }

  function finishAsFailed(message: string, generation: number) {
    if (!isCurrent(activeTaskId, generation)) return
    loading.value = false
    currentTaskId.value = ''
    activeTaskId = ''
    closeWebSocket()
    ElMessage.error(tt('backtestRt.msgFailedTpl', { message }))
  }

  function finishAsCancelled(generation: number) {
    if (!isCurrent(activeTaskId, generation)) return
    loading.value = false
    currentTaskId.value = ''
    activeTaskId = ''
    closeWebSocket()
    ElMessage.warning(tt('backtestRt.msgCancelled'))
  }

  function startPollingFallback(taskId: string, generation = runtimeGeneration): void {
    if (pollingStarted || !loading.value || !isCurrent(taskId, generation)) {
      return
    }
    pollingStarted = true
    void pollResult(taskId, generation)
  }

  function connectWebSocket(taskId: string) {
    closeWebSocket()
    const generation = ++runtimeGeneration
    activeTaskId = taskId
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/backtest/${taskId}`
    const protocols = createBacktestWebSocketProtocols()
    pollingStarted = false
    const currentWs = protocols.length > 0 ? new WebSocket(wsUrl, protocols) : new WebSocket(wsUrl)
    ws = currentWs

    heartbeatTimer = setInterval(() => {
      if (ws === currentWs && currentWs.readyState === WebSocket.OPEN) {
        currentWs.send('ping')
      }
    }, 30000)

    currentWs.onmessage = async (event) => {
      if (ws !== currentWs || !isCurrent(taskId, generation)) return
      try {
        const data = parseRuntimeEvent(event.data)
        if (!data || data.type === 'pong' || data.type === 'connected') {
          return
        }
        if (data.type === 'task_created') {
          progressInfo.value = {
            progress: 0,
            message: data.message || tt('backtestRt.msgTaskSubmitted'),
          }
          return
        }
        if (data.type === 'progress') {
          progressInfo.value = {
            progress: typeof data.progress === 'number' ? data.progress : progressInfo.value.progress,
            message: typeof data.message === 'string' ? data.message : tt('backtestRt.msgRunning'),
          }
          return
        }
        if (data.type === 'completed') {
          progressInfo.value = {
            progress: typeof data.progress === 'number' ? data.progress : 100,
            message: typeof data.message === 'string' ? data.message : tt('backtestRt.msgCompleted'),
          }
          await finishWithResult(taskId, generation)
          return
        }
        if (data.type === 'failed') {
          const message = typeof data.error === 'string'
            ? data.error
            : typeof data.message === 'string'
              ? data.message
              : tt('backtestRt.msgUnknownError')
          finishAsFailed(message, generation)
          return
        }
        if (data.type === 'cancelled') {
          finishAsCancelled(generation)
        }
      } catch (error) {
        finishAsFailed(
          error instanceof Error && error.message
            ? error.message
            : tt('backtestRt.msgUnknownError'),
          generation,
        )
      }
    }

    currentWs.onerror = () => {
      if (ws !== currentWs || !isCurrent(taskId, generation)) return
      closeWebSocket()
      startPollingFallback(taskId, generation)
    }

    currentWs.onclose = (event) => {
      if (ws !== currentWs || !isCurrent(taskId, generation)) return
      const shouldFallback = loading.value && event.code !== 1000
      closeWebSocket()
      if (shouldFallback) {
        startPollingFallback(taskId, generation)
      }
    }
  }

  async function pollResult(taskId: string, generation = runtimeGeneration) {
    pollAbortController = new AbortController()
    const { signal } = pollAbortController
    let attempts = 0

    while (attempts < POLL_MAX_ATTEMPTS && loading.value && !signal.aborted && isCurrent(taskId, generation)) {
      try {
        const statusResp = await backtestApi.getStatus(taskId, { signal })
        if (!isCurrent(taskId, generation)) return
        if (statusResp.status === 'completed') {
          try {
            await finishWithResult(taskId, generation)
          } catch (error) {
            finishAsFailed(
              error instanceof Error && error.message ? error.message : tt('backtestRt.msgUnknownError'),
              generation,
            )
          }
          return
        }
        if (statusResp.status === 'failed') {
          const result = await options.fetchResult(taskId).catch(() => null)
          if (!isCurrent(taskId, generation)) return
          finishAsFailed(result?.error_message || tt('backtestRt.msgUnknownError'), generation)
          return
        }
        if (statusResp.status === 'cancelled') {
          finishAsCancelled(generation)
          return
        }
        progressInfo.value = {
          progress: Math.min(progressInfo.value.progress + 5, 95),
          message: tt('backtestRt.msgFetchingProgress'),
        }
      } catch (e: unknown) {
        if (signal.aborted || !isCurrent(taskId, generation)) return
        if (attempts >= POLL_MAX_ATTEMPTS - 1) {
          loading.value = false
          currentTaskId.value = ''
          activeTaskId = ''
          closeWebSocket()
          ElMessage.error(getErrorMessage(e, tt('backtestRt.msgQueryFailed')))
          return
        }
      }

      try {
        await sleep(getPollingDelayMs(attempts), signal)
      } catch {
        return
      }
      attempts++
    }

    if (loading.value && !signal.aborted && isCurrent(taskId, generation)) {
      loading.value = false
      currentTaskId.value = ''
      activeTaskId = ''
      closeWebSocket()
      ElMessage.warning(tt('backtestRt.msgTimeout'))
    }
  }

  async function cancelBacktest() {
    const taskId = currentTaskId.value
    if (!taskId) return
    const generation = runtimeGeneration
    try {
      await backtestApi.cancel(taskId)
      if (!isCurrent(taskId, generation)) return
      loading.value = false
      currentTaskId.value = ''
      activeTaskId = ''
      closeWebSocket()
      ElMessage.success(tt('backtestRt.msgCancelDone'))
    } catch (e: unknown) {
      if (isCurrent(taskId, generation)) {
        ElMessage.error(getErrorMessage(e, tt('backtestRt.msgCancelFailed')))
      }
    }
  }

  function startRuntime(taskId: string) {
    loading.value = true
    currentTaskId.value = taskId
    progressInfo.value = { progress: 0, message: tt('backtestRt.msgSubmitting') }
    connectWebSocket(taskId)
  }

  function stopRuntime() {
    runtimeGeneration++
    activeTaskId = ''
    loading.value = false
    currentTaskId.value = ''
    closeWebSocket()
  }

  function disposeRuntime() {
    runtimeGeneration++
    activeTaskId = ''
    closeWebSocket()
  }

  return {
    loading,
    currentTaskId,
    progressInfo,
    cancelBacktest,
    closeWebSocket,
    connectWebSocket,
    disposeRuntime,
    pollResult,
    startPollingFallback,
    startRuntime,
    stopRuntime,
  }
}
