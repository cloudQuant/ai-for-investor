import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import api from '@/api/index'
import type {
  PortfolioAnalyticsTask,
  PortfolioAnalyticsTaskCreate,
} from '@/api/portfolioAnalyticsTasks'
import PortfolioAnalyticsTaskPanel from '@/components/portfolio/PortfolioAnalyticsTaskPanel.vue'

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

const input: PortfolioAnalyticsTaskCreate = {
  idempotency_key: 'generated-at-submit',
  facts: {
    version: 2,
    portfolio_ref: 'portfolio-01',
    source_mode: 'research',
    source_ref: 'research-run-01',
    source_version: 'research-v3',
    source_generation: 'generation-8',
    facts_snapshot_ref: 'facts-cut-2026-10-16',
    spot: { as_of_utc: '2026-10-16T12:00:00Z', rows: [] },
    nav_history: { rows: [] },
    loss_history: { rows: [] },
    scenario: { ref: 'scenario-1', version: 'scenario-v1', shocks: [] },
  },
  request: {
    version: 2,
    portfolio_ref: 'portfolio-01',
    reporting_currency: 'USD',
    loss_horizon_ref: 'horizon-1d',
    confidence: '0.95',
    scenario_ref: 'scenario-1',
    scenario_version: 'scenario-v1',
  },
}
const inputEnvelope = { facts: input.facts, request: input.request }

function task(
  state: PortfolioAnalyticsTask['state'],
  overrides: Partial<PortfolioAnalyticsTask> = {},
): PortfolioAnalyticsTask {
  return {
    task_ref: 'analytics-task-01',
    portfolio_ref: 'portfolio-01',
    membership_version: 7,
    membership_sha256: 'a'.repeat(64),
    input_snapshot_id: 'snapshot-01',
    input_sha256: 'b'.repeat(64),
    state,
    detail_code: null,
    created_ns: '1792152000000000000',
    state_ns: '1792152000000000000',
    result: null,
    ...overrides,
  }
}

function mountPanel(sourceType = 'research') {
  return mount(PortfolioAnalyticsTaskPanel, {
    props: { portfolioRef: 'portfolio-01', membershipVersion: 7, sourceType },
  })
}

describe('PortfolioAnalyticsTaskPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('crypto', { randomUUID: () => 'generated-at-submit' })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('submits the selected offline cut, polls the real task route, and renders the report', async () => {
    const pending = task('pending')
    const succeeded = task('succeeded', {
      result: {
        schema_version: 2,
        metrics: {
          net_reporting_notional: 216,
          gross_reporting_notional: 316,
          max_drawdown: -0.25,
          historical_var: 4,
          historical_expected_shortfall: 5,
        },
        scenario: { pnl: 20.28, currency: 'USD' },
      },
    })
    vi.mocked(api.post).mockResolvedValueOnce(pending)
    vi.mocked(api.get).mockResolvedValueOnce(succeeded)
    vi.useFakeTimers()

    const wrapper = mountPanel()
    await wrapper.get('[data-test="portfolio-analytics-input"]').setValue(JSON.stringify(inputEnvelope))
    await wrapper.get('[data-test="portfolio-analytics-submit"]').trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenCalledWith(
      '/portfolio/compositions/portfolio-01/versions/7/analytics-tasks',
      input,
    )
    expect(wrapper.get('[data-test="portfolio-analytics-task"]').text()).toContain('pending')

    await vi.advanceTimersByTimeAsync(2_500)
    await flushPromises()

    expect(api.get).toHaveBeenCalledWith(
      '/portfolio/compositions/portfolio-01/versions/7/analytics-tasks/analytics-task-01',
    )
    expect(wrapper.get('[data-test="portfolio-analytics-task"]').text()).toContain('succeeded')
    const report = wrapper.get('[data-test="portfolio-analytics-result"]').text()
    expect(report).toContain('net_reporting_notional')
    expect(report).toContain('216')
    expect(report).toContain('historical_expected_shortfall')
    expect(report).toContain('20.28')

    wrapper.unmount()
    vi.useRealTimers()
  })

  it('shows unavailable metrics as null with their reason instead of filling zero', async () => {
    const unavailable = task('unavailable', {
      detail_code: 'METRIC_INPUT_UNAVAILABLE',
      result: {
        schema_version: 2,
        metrics: {
          historical_var: {
            status: 'unavailable',
            value: null,
            reason: 'LOSS_HISTORY_NOT_AVAILABLE',
          },
        },
      },
    })
    vi.mocked(api.post).mockResolvedValueOnce(unavailable)

    const wrapper = mountPanel()
    await wrapper.get('[data-test="portfolio-analytics-input"]').setValue(JSON.stringify(inputEnvelope))
    await wrapper.get('[data-test="portfolio-analytics-submit"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="portfolio-analytics-task"]').text()).toContain('unavailable')
    expect(wrapper.get('[data-test="portfolio-analytics-task"]').text())
      .toContain('METRIC_INPUT_UNAVAILABLE')
    const report = wrapper.get('[data-test="portfolio-analytics-result"]').text()
    expect(report).toContain('LOSS_HISTORY_NOT_AVAILABLE')
    expect(report).toContain('"value": null')
    expect(report).not.toContain('"value": 0')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('cancels a pending task through its exact membership route and retains the terminal result', async () => {
    vi.mocked(api.post)
      .mockResolvedValueOnce(task('pending'))
      .mockResolvedValueOnce(task('cancelled', { detail_code: 'TASK_CANCELLED' }))

    const wrapper = mountPanel('imported')
    const importedInput = {
      facts: { ...input.facts, source_mode: 'imported' as const },
      request: input.request,
    }
    await wrapper.get('[data-test="portfolio-analytics-input"]').setValue(JSON.stringify(importedInput))
    await wrapper.get('[data-test="portfolio-analytics-submit"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="portfolio-analytics-cancel"]').trigger('click')
    await flushPromises()

    expect(api.post).toHaveBeenNthCalledWith(
      2,
      '/portfolio/compositions/portfolio-01/versions/7/analytics-tasks/analytics-task-01/cancel',
    )
    expect(wrapper.get('[data-test="portfolio-analytics-task"]').text()).toContain('cancelled')
    expect(wrapper.get('[data-test="portfolio-analytics-task"]').text()).toContain('TASK_CANCELLED')
    expect(api.get).not.toHaveBeenCalled()
  })

  it('never exposes the offline input form for a live composition', () => {
    const wrapper = mountPanel('live')

    expect(wrapper.get('[role="status"]').text()).toContain('Live')
    expect(wrapper.find('[data-test="portfolio-analytics-input"]').exists()).toBe(false)
    expect(api.post).not.toHaveBeenCalled()
  })
})
