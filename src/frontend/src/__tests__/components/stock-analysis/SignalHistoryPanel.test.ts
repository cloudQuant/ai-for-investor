import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'

import type { StockSignalRecord } from '@/api/stockAnalysis'
import SignalHistoryPanel from '@/components/stock-analysis/SignalHistoryPanel.vue'

function createSignal(overrides: Partial<StockSignalRecord> = {}): StockSignalRecord {
  return {
    id: 'signal-1',
    source: 'nightly_sse50',
    universe_code: 'SSE50',
    symbol: '600000.SH',
    symbol_name: '浦发银行',
    market_type: 'A股',
    as_of_date: '2026-07-01',
    available_at: '2026-07-01T15:00:00+08:00',
    signal_action: 'BUY',
    action_label: '买入',
    confidence_score: 0.8,
    risk_score: 0.2,
    eligibility_status: 'eligible',
    quality_reasons: [],
    feature_version: 'features-v1',
    decision_policy_version: 'policy-v1',
    model_version: 'model-v1',
    outcome_status: 'scored',
    horizon_20d_return: 0.12,
    ...overrides,
  }
}

function mountPanel(items: StockSignalRecord[]) {
  return mount(SignalHistoryPanel, {
    props: { items },
  })
}

describe('SignalHistoryPanel benchmark display', () => {
  it('shows the benchmark return when available and preserves the stock outcome', () => {
    const wrapper = mountPanel([
      createSignal({ benchmark_status: 'available', benchmark_20d_return: 0.08 }),
    ])

    const rowText = wrapper.get('tbody tr').text()
    expect(rowText).toContain('个股：12.0%')
    expect(rowText).toContain('基准：8.0%')
    expect(rowText).toContain('已评分')
    expect(wrapper.get('.benchmark-return').attributes('data-benchmark-status')).toBe('available')
  })

  it('uses a legacy benchmark value when status is omitted', () => {
    const wrapper = mountPanel([
      createSignal({ benchmark_20d_return: -0.025 }),
    ])

    expect(wrapper.get('tbody tr').text()).toContain('基准：-2.5%')
    expect(wrapper.get('.benchmark-return').attributes('data-benchmark-status')).toBe('available')
  })

  it('labels a missing legacy status and value as unknown, not unavailable', () => {
    const wrapper = mountPanel([
      createSignal({ benchmark_20d_return: null }),
      createSignal({
        id: 'signal-2',
        benchmark_status: 'unknown',
        benchmark_20d_return: null,
      }),
    ])

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    for (const row of rows) {
      expect(row.text()).toContain('基准收益未知')
      expect(row.text()).toContain('个股：12.0%')
      expect(row.text()).not.toContain('缺失')
      expect(row.text()).not.toContain('不可用')
    }
    expect(wrapper.findAll('.benchmark-return').map(item =>
      item.attributes('data-benchmark-status'),
    )).toEqual(['unknown', 'unknown'])
  })

  it('uses the available return value when status metadata conflicts', () => {
    const wrapper = mountPanel([
      createSignal({
        id: 'signal-available-without-value',
        benchmark_status: 'available',
        benchmark_status_reason: 'benchmark_return_not_present',
        benchmark_20d_return: null,
      }),
      createSignal({
        id: 'signal-unknown-with-value',
        benchmark_status: 'unknown',
        benchmark_status_reason: 'legacy_status_unknown',
        benchmark_20d_return: 0.08,
      }),
    ])

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('个股：12.0%')
    expect(rows[0].text()).toContain('基准收益未知')
    expect(rows[0].get('.benchmark-return').attributes('data-benchmark-status')).toBe('unknown')
    expect(rows[1].text()).toContain('个股：12.0%')
    expect(rows[1].text()).toContain('基准：8.0%')
    expect(rows[1].get('.benchmark-return').attributes('data-benchmark-status')).toBe('available')
  })
})
