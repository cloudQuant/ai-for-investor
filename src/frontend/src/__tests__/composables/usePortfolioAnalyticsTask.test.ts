import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { usePortfolioAnalyticsTask } from '@/composables/usePortfolioAnalyticsTask'
import { portfolioAnalyticsTasksApi } from '@/api/portfolioAnalyticsTasks'

vi.mock('@/api/portfolioAnalyticsTasks', () => ({
  portfolioAnalyticsTasksApi: {
    createTask: vi.fn(),
    getTask: vi.fn(),
    cancelTask: vi.fn(),
  },
}))

describe('usePortfolioAnalyticsTask', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('stops polling immediately on non-retryable 4xx error', async () => {
    vi.mocked(portfolioAnalyticsTasksApi.createTask).mockResolvedValueOnce({
      task_ref: 'task-404',
      state: 'running',
    } as never)
    vi.mocked(portfolioAnalyticsTasksApi.getTask).mockRejectedValueOnce({
      response: { status: 404 },
    })

    const runner = usePortfolioAnalyticsTask({ intervalMs: 1000 })
    await runner.start({ portfolioRef: 'primary', membershipVersion: 1 }, { analysis_kind: 'risk' } as never)
    expect(runner.polling.value).toBe(true)

    await vi.advanceTimersByTimeAsync(1000)
    expect(portfolioAnalyticsTasksApi.getTask).toHaveBeenCalledTimes(1)
    expect(runner.polling.value).toBe(false)

    await vi.advanceTimersByTimeAsync(5000)
    expect(portfolioAnalyticsTasksApi.getTask).toHaveBeenCalledTimes(1)
  })

  it('stops polling after consecutive transient poll errors reach the cap', async () => {
    vi.mocked(portfolioAnalyticsTasksApi.createTask).mockResolvedValueOnce({
      task_ref: 'task-500',
      state: 'running',
    } as never)
    vi.mocked(portfolioAnalyticsTasksApi.getTask).mockRejectedValue(new Error('network down'))

    const runner = usePortfolioAnalyticsTask({ intervalMs: 100 })
    await runner.start({ portfolioRef: 'primary', membershipVersion: 1 }, { analysis_kind: 'risk' } as never)

    for (let i = 0; i < 6; i += 1) {
      await vi.advanceTimersByTimeAsync(100)
    }

    expect(portfolioAnalyticsTasksApi.getTask).toHaveBeenCalledTimes(5)
    expect(runner.polling.value).toBe(false)
  })
})
