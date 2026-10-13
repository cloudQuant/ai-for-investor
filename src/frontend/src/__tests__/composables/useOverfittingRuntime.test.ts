import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'

import { strategyApi } from '@/api/strategy'
import type { StrategyOverfittingTaskResult } from '@/api/strategy'
import { useOverfittingRuntime } from '@/composables/useOverfittingRuntime'
import { getAccessToken } from '@/utils/session'

vi.mock('@/api/strategy', () => ({
  strategyApi: {
    getOverfittingTask: vi.fn(),
  },
}))

vi.mock('@/utils/session', () => ({
  getAccessToken: vi.fn(() => 'mock-token'),
}))

function makeResult(
  overrides: Partial<StrategyOverfittingTaskResult> = {},
): StrategyOverfittingTaskResult {
  return {
    task_id: 'ot-123',
    backtest_id: 'bt-1',
    status: 'completed',
    overall_level: 'low',
    robustness_score: 81,
    summary: '检测完成',
    methods: [],
    error_message: null,
    ...overrides,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })

  return { promise, resolve }
}

const WS_CONNECTING = 0
const WS_OPEN = 1
const WS_CLOSED = 3

class MockWebSocket {
  static instances: MockWebSocket[] = []

  static clearInstances() {
    MockWebSocket.instances = []
  }

  static readonly CONNECTING = WS_CONNECTING
  static readonly OPEN = WS_OPEN
  static readonly CLOSED = WS_CLOSED

  readyState: number = WS_CONNECTING
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onopen: (() => void) | null = null
  protocols: string[] = []
  url: string

  constructor(url: string, protocols?: string | string[]) {
    this.url = url
    this.protocols = protocols ? (Array.isArray(protocols) ? protocols : [protocols]) : []
    MockWebSocket.instances.push(this)
    setTimeout(() => {
      this.readyState = WS_OPEN
      this.onopen?.()
    }, 0)
  }

  send = vi.fn()
  close = vi.fn(() => {
    this.readyState = WS_CLOSED
  })

  simulateMessage(data: object) {
    this.simulateRawMessage(JSON.stringify(data))
  }

  simulateRawMessage(data: string) {
    this.onmessage?.({ data } as MessageEvent)
  }

  simulateError() {
    this.onerror?.(new Event('error'))
  }

  simulateClose(code: number) {
    this.readyState = WS_CLOSED
    this.onclose?.({ code } as CloseEvent)
  }
}

vi.stubGlobal('WebSocket', MockWebSocket)

describe('useOverfittingRuntime', () => {
  let runtime: ReturnType<typeof useOverfittingRuntime>
  let currentResult = ref<StrategyOverfittingTaskResult | null>(null)

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(getAccessToken).mockReturnValue('mock-token')
    vi.mocked(strategyApi.getOverfittingTask).mockReset()
    MockWebSocket.clearInstances()
    currentResult = ref<StrategyOverfittingTaskResult | null>(null)
    runtime = useOverfittingRuntime({ currentResult })
  })

  afterEach(() => {
    runtime.stopRuntime()
    vi.useRealTimers()
    vi.stubGlobal('WebSocket', MockWebSocket)
  })

  it('connects websocket with auth token', async () => {
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1)
    })

    const ws = MockWebSocket.instances[0]
    expect(ws.url).toContain('/ws/overfitting/ot-123')
    expect(ws.protocols).toEqual(['access-token', 'mock-token'])
  })

  it('stores completed result from websocket event', async () => {
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances.length).toBe(1)
    })

    const ws = MockWebSocket.instances[0]
    ws.simulateMessage({
      type: 'completed',
      task_id: 'ot-123',
      result: {
        task_id: 'ot-123',
        backtest_id: 'bt-1',
        status: 'completed',
        overall_level: 'low',
        robustness_score: 81,
        summary: '检测完成',
        methods: [],
        error_message: null,
      },
    })

    await vi.waitFor(() => {
      expect(runtime.loading.value).toBe(false)
      expect(currentResult.value?.task_id).toBe('ot-123')
      expect(currentResult.value?.robustness_score).toBe(81)
    })
  })

  it('ignores malformed and connection messages while tracking task progress', async () => {
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    const ws = MockWebSocket.instances[0]
    ws.simulateRawMessage('{invalid json')
    ws.simulateMessage({})
    ws.simulateMessage({ type: 'connected' })
    ws.simulateMessage({ type: 'pong' })
    expect(runtime.progressInfo.value.progress).toBe(0)

    ws.simulateMessage({ type: 'task_created', message: 42 })
    expect(runtime.progressInfo.value.progress).toBe(0)
    expect(runtime.progressInfo.value.message).not.toBe('')

    ws.simulateMessage({ type: 'progress', progress: 35, message: '正在分析' })
    expect(runtime.progressInfo.value).toEqual({ progress: 35, message: '正在分析' })

    ws.simulateMessage({ type: 'progress', progress: 'not-a-number' })
    expect(runtime.progressInfo.value.progress).toBe(35)
    expect(runtime.progressInfo.value.message).not.toBe('正在分析')
    expect(runtime.loading.value).toBe(true)
    expect(strategyApi.getOverfittingTask).not.toHaveBeenCalled()
  })

  it('fetches the result when a websocket completion event omits its payload', async () => {
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(makeResult())
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    MockWebSocket.instances[0].simulateMessage({ type: 'completed' })

    await vi.waitFor(() => {
      expect(strategyApi.getOverfittingTask).toHaveBeenCalledWith('ot-123')
      expect(currentResult.value?.status).toBe('completed')
      expect(runtime.loading.value).toBe(false)
    })
    expect(runtime.progressInfo.value.progress).toBe(100)
    expect(runtime.progressInfo.value.message).not.toBe('')
  })

  it('uses the websocket failure detail and clears the active task', async () => {
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    MockWebSocket.instances[0].simulateMessage({ type: 'failed', error: 'worker failed' })

    expect(runtime.progressInfo.value.message).toBe('worker failed')
    expect(runtime.loading.value).toBe(false)
    expect(runtime.currentTaskId.value).toBe('')
    expect(currentResult.value).toBeNull()
  })

  it('falls back to polling when the websocket reports an error', async () => {
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(makeResult({ summary: 'fallback result' }))
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    const ws = MockWebSocket.instances[0]
    ws.simulateError()

    await vi.waitFor(() => {
      expect(strategyApi.getOverfittingTask).toHaveBeenCalledWith('ot-123')
      expect(currentResult.value?.summary).toBe('fallback result')
      expect(runtime.loading.value).toBe(false)
    })
    expect(ws.close).toHaveBeenCalledOnce()
  })

  it('falls back after an abnormal websocket close but ignores a normal close', async () => {
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(makeResult())
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    const ws = MockWebSocket.instances[0]
    ws.simulateClose(1000)
    expect(strategyApi.getOverfittingTask).not.toHaveBeenCalled()
    expect(runtime.loading.value).toBe(true)

    ws.simulateClose(1006)
    await vi.waitFor(() => {
      expect(strategyApi.getOverfittingTask).toHaveBeenCalledWith('ot-123')
      expect(runtime.loading.value).toBe(false)
    })
  })

  it('ignores a websocket completion delivered after the runtime is stopped', async () => {
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(MockWebSocket.instances).toHaveLength(1)
    })

    const ws = MockWebSocket.instances[0]
    runtime.stopRuntime()
    ws.simulateMessage({ type: 'completed', result: makeResult() })

    expect(runtime.loading.value).toBe(false)
    expect(runtime.currentTaskId.value).toBe('')
    expect(currentResult.value).toBeNull()
    expect(strategyApi.getOverfittingTask).not.toHaveBeenCalled()
  })

  it('falls back to polling when token is missing', async () => {
    vi.mocked(getAccessToken).mockReturnValue(null)
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(
      makeResult({ overall_level: 'medium', robustness_score: 63, summary: '轮询完成' }),
    )

    runtime = useOverfittingRuntime({ currentResult })
    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(strategyApi.getOverfittingTask).toHaveBeenCalledWith('ot-123')
      expect(currentResult.value?.summary).toBe('轮询完成')
      expect(runtime.loading.value).toBe(false)
    })

    expect(MockWebSocket.instances.length).toBe(0)
  })

  it.each([
    { status: 'failed', error_message: '任务失败', summary: '失败摘要', expected: '任务失败' },
    { status: 'cancelled', error_message: '', summary: '任务已取消', expected: '任务已取消' },
  ])('surfaces the $status status from polling', async ({ status, error_message, summary, expected }) => {
    vi.mocked(getAccessToken).mockReturnValue(null)
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(
      makeResult({ status, error_message, summary }),
    )

    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(runtime.loading.value).toBe(false)
    })

    expect(runtime.progressInfo.value.message).toBe(expected)
    expect(runtime.currentTaskId.value).toBe('')
    expect(currentResult.value).toBeNull()
  })

  it('aborts the polling delay when stopped while a task is still running', async () => {
    vi.mocked(getAccessToken).mockReturnValue(null)
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(
      makeResult({ status: 'running', summary: 'still running' }),
    )

    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(runtime.progressInfo.value.message).toBe('still running')
    })

    runtime.stopRuntime()
    await Promise.resolve()

    expect(strategyApi.getOverfittingTask).toHaveBeenCalledTimes(1)
    expect(runtime.loading.value).toBe(false)
    expect(runtime.currentTaskId.value).toBe('')
  })

  it.each([
    {
      name: 'stopRuntime',
      stop: (target: ReturnType<typeof useOverfittingRuntime>) => target.stopRuntime(),
      expectedLoading: false,
      expectedTaskId: '',
    },
    {
      name: 'disposeRuntime',
      stop: (target: ReturnType<typeof useOverfittingRuntime>) => target.disposeRuntime(),
      expectedLoading: true,
      expectedTaskId: 'ot-123',
    },
  ])('$name ignores a result returned after polling is aborted', async ({
    stop,
    expectedLoading,
    expectedTaskId,
  }) => {
    vi.mocked(getAccessToken).mockReturnValue(null)
    const previousResult = makeResult({ status: 'running', summary: 'previous result' })
    const pendingRequest = deferred<StrategyOverfittingTaskResult>()
    currentResult.value = previousResult
    const previousResultRef = currentResult.value
    vi.mocked(strategyApi.getOverfittingTask).mockReturnValue(pendingRequest.promise)

    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(strategyApi.getOverfittingTask).toHaveBeenCalledTimes(1)
    })
    const progressBeforeLateResponse = { ...runtime.progressInfo.value }

    stop(runtime)
    pendingRequest.resolve(makeResult({ summary: 'late completion' }))
    await pendingRequest.promise
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(currentResult.value).toBe(previousResultRef)
    expect(runtime.progressInfo.value).toEqual(progressBeforeLateResponse)
    expect(runtime.loading.value).toBe(expectedLoading)
    expect(runtime.currentTaskId.value).toBe(expectedTaskId)
    expect(strategyApi.getOverfittingTask).toHaveBeenCalledTimes(1)
  })

  it('uses the polling fallback when the browser does not expose WebSocket', async () => {
    vi.stubGlobal('WebSocket', undefined)
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(makeResult())

    runtime.startRuntime('ot-123')

    await vi.waitFor(() => {
      expect(currentResult.value?.status).toBe('completed')
      expect(runtime.loading.value).toBe(false)
    })

    expect(strategyApi.getOverfittingTask).toHaveBeenCalledWith('ot-123')
  })

  it('stops polling after the bounded retry window', async () => {
    vi.useFakeTimers()
    vi.mocked(getAccessToken).mockReturnValue(null)
    vi.mocked(strategyApi.getOverfittingTask).mockResolvedValue(
      makeResult({ status: 'running', summary: 'still running' }),
    )

    runtime.startRuntime('ot-123')
    await vi.runAllTimersAsync()

    expect(strategyApi.getOverfittingTask).toHaveBeenCalledTimes(60)
    expect(runtime.loading.value).toBe(false)
    expect(runtime.currentTaskId.value).toBe('')
    expect(runtime.progressInfo.value.message).not.toBe('still running')
  })
})
