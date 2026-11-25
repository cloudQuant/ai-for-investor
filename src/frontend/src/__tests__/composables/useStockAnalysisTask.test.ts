import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { stockAnalysisApi } from '@/api/stockAnalysis'
import { useStockAnalysisTask } from '@/composables/useStockAnalysisTask'

vi.mock('@/api/stockAnalysis', () => ({
  stockAnalysisApi: {
    getTask: vi.fn(),
    getTaskResult: vi.fn(),
  },
}))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

function setupRuntime() {
  let runtime!: ReturnType<typeof useStockAnalysisTask>
  const wrapper = mount(defineComponent({
    setup() {
      runtime = useStockAnalysisTask('task-1', { intervalMs: 50 })
      return () => h('div')
    },
  }))
  return { wrapper, runtime }
}

const running = {
  task_id: 'task-1', status: 'running', symbol: '000001.SZ', progress: 40,
} as any

describe('iteration207 stock analysis polling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.mocked(stockAnalysisApi.getTask).mockReset()
    vi.mocked(stockAnalysisApi.getTaskResult).mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not overlap a slow request with the next polling tick', async () => {
    const first = deferred<any>()
    vi.mocked(stockAnalysisApi.getTask).mockReturnValueOnce(first.promise).mockResolvedValue(running)
    const { wrapper, runtime } = setupRuntime()
    runtime.startPolling()
    await flushPromises()
    expect(stockAnalysisApi.getTask).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(100)
    expect(stockAnalysisApi.getTask).toHaveBeenCalledTimes(1)
    first.resolve(running)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(50)
    expect(stockAnalysisApi.getTask).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('does not regress a running task to an older pending snapshot', async () => {
    vi.mocked(stockAnalysisApi.getTask)
      .mockResolvedValueOnce(running)
      .mockResolvedValueOnce({ ...running, status: 'pending', progress: 0 })
    const { wrapper, runtime } = setupRuntime()
    runtime.startPolling()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(50)
    await flushPromises()

    expect(runtime.task.value).toMatchObject({ status: 'running', progress: 40 })
    wrapper.unmount()
  })

  it('handles network rejection without an unhandled promise and stops polling', async () => {
    vi.mocked(stockAnalysisApi.getTask).mockRejectedValue(new Error('network down'))
    const { wrapper, runtime } = setupRuntime()
    runtime.startPolling()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(100)

    expect(runtime.error.value).toBeInstanceOf(Error)
    expect(runtime.polling.value).toBe(false)
    expect(stockAnalysisApi.getTask).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
