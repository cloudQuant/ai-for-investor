import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import BacktestResultPage from '@/views/BacktestResultPage.vue'
import { analyticsApi } from '@/api/analytics'
import { elStubs } from '@/test/stubs'

const mockPush = vi.fn()
const mockRoute = {
  params: { id: 't1' },
  query: {} as Record<string, unknown>,
}

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush, back: vi.fn() }),
  useRoute: () => mockRoute,
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

// Use the actual zh-CN locale so assertions like toContain('策略评分') work
// against rendered template strings. Aligns with the global setup.ts mock.
vi.mock('vue-i18n', async () => {
  const { ref } = await import('vue')
  const zhCN = (await import('@/i18n/locales/zh-CN')).default
  function flatten(obj: Record<string, unknown>, prefix = ''): Record<string, string> {
    const out: Record<string, string> = {}
    for (const [k, v] of Object.entries(obj)) {
      const key = prefix ? `${prefix}.${k}` : k
      if (v && typeof v === 'object') Object.assign(out, flatten(v as Record<string, unknown>, key))
      else out[key] = String(v)
    }
    return out
  }
  const flat = flatten(zhCN as Record<string, unknown>)
  const t = (key: string, named?: Record<string, unknown>) => {
    const tpl = flat[key] ?? key
    if (!named) return tpl
    return tpl.replace(/\{(\w+)\}/g, (_, n) => (n in named ? String(named[n]) : `{${n}}`))
  }
  return {
    createI18n: vi.fn(() => ({ global: { t, locale: ref('zh-CN') }, install: vi.fn() })),
    useI18n: vi.fn(() => ({ t, locale: ref('zh-CN') })),
  }
})

vi.mock('@/utils/session', () => ({
  getAccessToken: vi.fn(() => null),
}))

vi.mock('@/api/strategy', () => ({
  strategyApi: {
    getTemplates: vi.fn().mockResolvedValue({ templates: [], total: 0 }),
    createScore: vi.fn().mockResolvedValue({
      backtest_id: 't1',
      total_score: 78,
      level: 'A',
      model_version: 'v1',
      disclaimer: '评分仅供研究参考，不构成投资建议。',
      dimensions: [
        {
          key: 'profitability',
          label: '收益质量',
          score: 80,
          weight: 0.2,
          explanation: '收益表现较好。',
          sub_metrics: { annual_return: 0.2 },
          degraded: false,
        },
      ],
    }),
    createOverfittingTask: vi.fn().mockResolvedValue({
      task_id: 'ot-1',
      backtest_id: 't1',
      status: 'pending',
      methods: ['monte_carlo'],
    }),
    getOverfittingTask: vi.fn().mockResolvedValue({
      task_id: 'ot-1',
      backtest_id: 't1',
      status: 'completed',
      overall_level: 'low',
      robustness_score: 82,
      summary: 'Monte Carlo 检测完成。',
      methods: [
        {
          method: 'monte_carlo',
          status: 'completed',
          risk_level: 'low',
          score: 82,
          explanation: '实际收益位于高分位。',
          metrics: { bootstrap_percentile: 96 },
          degraded: false,
        },
      ],
      error_message: null,
    }),
    explainStrategy: vi.fn().mockResolvedValue({
      code_hash: 'abc123',
      strategy_name: 'SMA',
      summary: 'SMA 策略通过均线交叉识别趋势。',
      indicators_explanation: '使用 SMA 指标。',
      entry_explanation: '金叉时买入。',
      exit_explanation: '死叉时卖出。',
      params_explanation: 'fast_period 控制快线。',
      market_fit: '适合趋势市场。',
      risk_notes: ['震荡市场可能假信号'],
      ast: {
        parsable: true,
        indicators: [],
        entry_signals: [],
        exit_signals: [],
        risk_controls: [],
        params: [],
        data_sources: [],
        raw_code: null,
        parse_error: null,
      },
      reason_code: 'static_fallback',
      model_id: null,
      cached: false,
      disclaimer: '解释仅供研究参考，不构成投资建议。',
    }),
  },
}))

vi.mock('@/stores/backtest', () => ({
  useBacktestStore: () => ({
    fetchResult: vi.fn().mockResolvedValue({
      task_id: 't1',
      strategy_id: 's1',
      symbol: 'BTC',
      start_date: '2024-01-01',
      end_date: '2024-01-31',
      status: 'completed',
      total_return: 15,
      annual_return: 20,
      sharpe_ratio: 1.5,
      max_drawdown: -10,
      win_rate: 60,
      total_trades: 50,
      profitable_trades: 30,
      losing_trades: 20,
      equity_curve: [100000],
      equity_dates: ['2024-01-01'],
      drawdown_curve: [0],
      trades: [],
      created_at: '2024-02-01T00:00:00',
    }),
    currentResult: null,
  }),
}))

vi.mock('@/api/analytics', () => ({
  analyticsApi: {
    getBacktestDetail: vi.fn().mockResolvedValue({
      task_id: 't1',
      strategy_name: 'SMA',
      symbol: 'BTC',
      start_date: '2024-01-01',
      end_date: '2024-01-31',
      metrics: {
        initial_capital: 100000,
        final_assets: 115000,
        total_return: 0.15,
        annualized_return: 0.2,
        max_drawdown: -0.1,
        max_drawdown_duration: 3,
        sharpe_ratio: 1.5,
        sortino_ratio: 1.2,
        calmar_ratio: 1.1,
        win_rate: 0.6,
        profit_factor: 1.8,
        trade_count: 50,
        avg_trade_return: 0.01,
        avg_holding_days: 5,
        avg_win: 0.02,
        avg_loss: -0.01,
        max_consecutive_wins: 4,
        max_consecutive_losses: 2,
      },
      equity_curve: [{ date: '2024-01-01', total_assets: 100000, cash: 100000, position_value: 0 }],
      drawdown_curve: [{ date: '2024-01-01', drawdown: 0, peak: 100000, trough: 100000 }],
      trades: [],
      created_at: '2024-02-01T00:00:00',
    }),
    getKlineWithSignals: vi.fn().mockResolvedValue({
      symbol: 'BTC',
      klines: [{ date: '2024-01-01', open: 1, high: 2, low: 0.5, close: 1.5, volume: 100 }],
      signals: [],
      indicators: {},
    }),
    getMonthlyReturns: vi.fn().mockResolvedValue({ returns: [], years: [], summary: {} }),
    exportResults: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('@/api/backtest', () => ({
  backtestApi: {
    getSummary: vi.fn().mockResolvedValue({
      task_id: 't1',
      strategy_id: 's1',
      symbol: 'BTC',
      status: 'completed',
      metrics: {
        total_return: 15,
        annual_return: 20,
        sharpe_ratio: 1.5,
        max_drawdown: -10,
        win_rate: 60,
        total_trades: 50,
        profitable_trades: 30,
        losing_trades: 20,
        break_even_trades: 0,
        avg_holding_bars: 0,
        avg_holding_period: 0,
        max_consecutive_wins: 0,
        max_consecutive_losses: 0,
        profit_loss_ratio: 1.8,
        initial_cash: 100000,
        final_value: 115000,
        metrics_source: 'test',
      },
      data_precheck: null,
      robustness: null,
    }),
    getResult: vi.fn().mockResolvedValue({
      task_id: 't1',
      strategy_id: 's1',
      symbol: 'BTC',
      start_date: '2024-01-01',
      end_date: '2024-01-31',
      status: 'completed',
      total_return: 15,
      annual_return: 20,
      sharpe_ratio: 1.5,
      max_drawdown: -10,
      win_rate: 60,
      total_trades: 50,
      profitable_trades: 30,
      losing_trades: 20,
      equity_curve: [100000],
      equity_dates: ['2024-01-01'],
      drawdown_curve: [0],
      trades: [],
      created_at: '2024-02-01T00:00:00',
      result_summary: {
        strategy_id: 's1',
        symbol: 'BTC',
        total_trades: 50,
        sharpe_ratio: 1.5,
      },
      data_precheck: {
        passed: true,
        status: 'pass',
        asset_type: 'crypto',
        symbol: 'BTC',
        timeframe: '1d',
        provider: 'local_csv',
        reasons: [],
        warnings: [],
        quality_reports: [],
        gate_evaluations: [],
      },
      robustness: null,
    }),
    runRobustness: vi.fn().mockResolvedValue({
      id: 'robust-1',
      user_id: 'u1',
      backtest_id: 't1',
      method: 'overfitting_suite',
      status: 'passed',
      metrics: { robustness_score: 82 },
      gate_evaluations: [],
      report: {},
      error_message: null,
      created_at: '2024-02-01T00:00:00',
    }),
  },
}))

describe('BacktestResultPage', () => {
  beforeEach(async () => {
    const { backtestApi } = await import('@/api/backtest')
    const { strategyApi } = await import('@/api/strategy')
    setActivePinia(createPinia())
    mockPush.mockReset()
    mockRoute.params = { id: 't1' }
    mockRoute.query = {}
    vi.mocked(analyticsApi.getBacktestDetail).mockClear()
    vi.mocked(analyticsApi.getKlineWithSignals).mockClear()
    vi.mocked(analyticsApi.getMonthlyReturns).mockClear()
    vi.mocked(analyticsApi.exportResults).mockClear()
    vi.mocked(backtestApi.getSummary).mockClear()
    vi.mocked(backtestApi.getResult).mockClear()
    vi.mocked(backtestApi.runRobustness).mockClear()
    vi.mocked(strategyApi.createScore).mockClear()
    vi.mocked(strategyApi.createOverfittingTask).mockClear()
    vi.mocked(strategyApi.getOverfittingTask).mockClear()
    vi.mocked(strategyApi.explainStrategy).mockClear()
  })

  it('mounts without error', () => {
    const wrapper = mount(BacktestResultPage, { global: { stubs: { ...elStubs, EquityCurve: true, DrawdownChart: true, TradeRecordsTable: true, TradeSignalChart: true, ReturnHeatmap: true, MetricCard: true, PerformancePanel: true } } })
    expect(wrapper.exists()).toBe(true)
  })

  it('renders the compact summary before a delayed detail response', async () => {
    const { analyticsApi } = await import('@/api/analytics')
    const { backtestApi } = await import('@/api/backtest')
    vi.mocked(analyticsApi.getBacktestDetail).mockImplementationOnce(
      () => new Promise(() => undefined) as never,
    )
    vi.mocked(backtestApi.getSummary).mockResolvedValueOnce({
      task_id: 't1',
      strategy_id: 'summary-strategy',
      symbol: 'RB0',
      status: 'completed',
      metrics: {
        total_return: 12.5,
        annual_return: 6.2,
        sharpe_ratio: 1.4,
        max_drawdown: -4.1,
        win_rate: 55,
        total_trades: 7,
        profitable_trades: 4,
        losing_trades: 3,
        break_even_trades: 0,
        avg_holding_bars: 0,
        avg_holding_period: 0,
        max_consecutive_wins: 0,
        max_consecutive_losses: 0,
        profit_loss_ratio: 1.7,
        initial_cash: 100000,
        final_value: 112500,
        metrics_source: 'test',
      },
      data_precheck: null,
      robustness: null,
    } as any)

    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    const summary = wrapper.get('[data-test="backtest-summary-first"]')
    expect(summary.text()).toContain('summary-strategy')
    expect(summary.text()).toContain('RB0')
    expect(backtestApi.getSummary).toHaveBeenCalledWith('t1')
  })

  it('renders strategy score section when score loads', async () => {
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('策略评分')
    expect(wrapper.text()).toContain('78')
    expect(wrapper.text()).toContain('评分仅供研究参考')
    expect(wrapper.text()).toContain('过拟合诊断')
    expect(wrapper.text()).toContain('暂无过拟合检测结果')
    expect(wrapper.text()).toContain('策略解释')
    expect(wrapper.text()).toContain('SMA 策略通过均线交叉识别趋势')
  })

  it('shows a completed research workflow and returns to the canonical backtest list', async () => {
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })

    await flushPromises()

    const guide = wrapper.get('[data-test="backtest-workflow-guide"]')
    expect(guide.text()).toContain('审阅并决定下一步')
    await guide.find('button').trigger('click')
    expect(mockPush).toHaveBeenCalledWith('/backtest')
  })

  it('treats a cancelled result as an attention state', async () => {
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    const vm = wrapper.vm as any
    vm.detail = { ...vm.detail, artifact_status: 'cancelled', artifact_error: 'Stopped by user' }
    await wrapper.vm.$nextTick()

    expect(vm.resultStatusLabel).toBe('已取消')
    expect(vm.statusTagType).toBe('danger')
    expect(wrapper.find('.research-workflow-guide__step--attention').exists()).toBe(true)
  })

  it('opens the mobile diagnostics drawer and restores focus after closing it', async () => {
    const wrapper = mount(BacktestResultPage, {
      attachTo: document.body,
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    const trigger = wrapper.get('[data-test="backtest-open-diagnostics"]')
    await trigger.trigger('click')
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.backtest-result-panel--mobile-open').attributes('role')).toBe('dialog')
    expect(document.activeElement?.getAttribute('aria-label')).toBe('关闭诊断')

    await wrapper.find('.backtest-mobile-diagnostics-close').trigger('click')
    await wrapper.vm.$nextTick()

    expect(document.activeElement).toBe(trigger.element)
    wrapper.unmount()
  })

  it('closes the mobile diagnostics drawer with Escape', async () => {
    const wrapper = mount(BacktestResultPage, {
      attachTo: document.body,
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    await wrapper.get('[data-test="backtest-open-diagnostics"]').trigger('click')
    await wrapper.find('.backtest-result-panel--diagnostics').trigger('keydown', { key: 'Escape' })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.backtest-result-panel--mobile-open').exists()).toBe(false)
    wrapper.unmount()
  })

  it('loads heavy report data lazily', async () => {
    const { analyticsApi } = await import('@/api/analytics')
    const { strategyApi } = await import('@/api/strategy')
    mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })

    await flushPromises()

    expect(analyticsApi.getBacktestDetail).toHaveBeenCalledTimes(1)
    expect(analyticsApi.getKlineWithSignals).not.toHaveBeenCalled()
    expect(analyticsApi.getMonthlyReturns).not.toHaveBeenCalled()
    expect(strategyApi.createOverfittingTask).not.toHaveBeenCalled()
  })

  it('reruns overfitting analysis from the panel action', async () => {
    const { strategyApi } = await import('@/api/strategy')
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })

    await flushPromises()

    const button = wrapper.findAll('button').find((item) => item.text().includes('重新检测'))
    expect(button).toBeTruthy()
    await button?.trigger('click')
    await flushPromises()

    expect(strategyApi.createOverfittingTask).toHaveBeenLastCalledWith('t1', expect.objectContaining({
      methods: ['walk_forward', 'out_of_sample', 'monte_carlo', 'parameter_sensitivity'],
      walk_forward_max_concurrency: 4,
    }))
  })

  it('returns to workspace detail when workspaceId is present', async () => {
    mockRoute.query = { workspaceId: 'ws-1' }
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    const buttons = wrapper.findAll('.el-button')
    await buttons[1].trigger('click')

    expect(mockPush).toHaveBeenCalledWith({
      name: 'BacktestWorkspaceDetail',
      params: { id: 'ws-1' },
    })
  })

  it('shows a detail request error and retries the request from the error state', async () => {
    const { backtestApi } = await import('@/api/backtest')
    vi.mocked(analyticsApi.getBacktestDetail).mockRejectedValueOnce(new Error('detail unavailable'))
    vi.mocked(backtestApi.getSummary).mockRejectedValueOnce(new Error('summary unavailable'))

    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    expect(analyticsApi.getBacktestDetail).toHaveBeenCalledWith('t1')
    expect(backtestApi.getSummary).toHaveBeenCalledWith('t1')
    expect(wrapper.get('[role="alert"]').text()).toContain('detail unavailable')

    await wrapper.get('[role="alert"] .el-button').trigger('click')
    await flushPromises()

    expect(analyticsApi.getBacktestDetail).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="backtest-detail"]').text()).toContain('SMA')
  })

  it('keeps the compact summary visible when the full detail request fails', async () => {
    const { backtestApi } = await import('@/api/backtest')
    vi.mocked(analyticsApi.getBacktestDetail).mockRejectedValueOnce(new Error('detail timed out'))
    vi.mocked(backtestApi.getSummary).mockResolvedValueOnce({
      task_id: 't1',
      strategy_id: 'summary-sma',
      symbol: 'RB0',
      status: 'completed',
      metrics: {
        total_return: 0.12,
        annual_return: 0.08,
        sharpe_ratio: 1.2,
        max_drawdown: -0.04,
        win_rate: 55,
        total_trades: 7,
        profitable_trades: 4,
        losing_trades: 3,
        break_even_trades: 0,
        avg_holding_bars: 0,
        avg_holding_period: 0,
        max_consecutive_wins: 0,
        max_consecutive_losses: 0,
        profit_loss_ratio: 1.7,
        initial_cash: 100000,
        final_value: 112000,
        metrics_source: 'test',
      },
      data_precheck: null,
      robustness: null,
    } as any)

    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    const summary = wrapper.get('[data-test="backtest-summary-first"]')
    expect(summary.text()).toContain('summary-sma')
    expect(summary.text()).toContain('detail timed out')
    expect(summary.find('.el-button').text()).toContain('重试')
  })

  it('renders signed return metrics and maps a running artifact to an in-progress status', async () => {
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.detail = {
      ...vm.detail,
      artifact_status: 'running',
      metrics: {
        ...vm.detail.metrics,
        total_return: -0.12,
        annualized_return: -0.04,
      },
    }
    await wrapper.vm.$nextTick()

    expect(vm.resultStatusLabel).toBe('运行中')
    expect(vm.statusTagType).toBe('warning')
    expect(wrapper.get('[data-test="backtest-status"]').text()).toBe('running')
    expect(wrapper.find('.backtest-result-metric--negative').text()).toContain('-12.00%')
    expect(wrapper.find('.backtest-result-metric--positive').exists()).toBe(false)
  })

  it('falls back to sparse detail metrics when the summary request fails and shows failed status', async () => {
    const { backtestApi } = await import('@/api/backtest')
    vi.mocked(backtestApi.getSummary).mockRejectedValueOnce(new Error('summary unavailable'))
    vi.mocked(analyticsApi.getBacktestDetail).mockResolvedValueOnce({
      task_id: 't1',
      strategy_name: 'Sparse SMA',
      symbol: 'RB0',
      start_date: '2024-01-01',
      end_date: '2024-01-31',
      artifact_status: 'failed',
      artifact_error: 'worker failed to produce a result',
      metrics: {
        initial_capital: 100000,
        final_assets: 100000,
        total_return: null,
        annualized_return: undefined,
        max_drawdown: null,
        sharpe_ratio: null,
      },
      result_summary: {
        strategy_id: 'sparse-sma',
        symbol: 'RB0',
        total_trades: 0,
        sharpe_ratio: null,
        total_return: null,
        max_drawdown: null,
      },
      data_precheck: null,
      robustness: null,
      equity_curve: [],
      drawdown_curve: [],
      trades: [],
      created_at: '2024-02-01T00:00:00',
    } as any)

    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    expect(backtestApi.getSummary).toHaveBeenCalledWith('t1')
    expect(analyticsApi.getBacktestDetail).toHaveBeenCalledWith('t1')
    expect(wrapper.get('[data-test="backtest-detail"]').text()).toContain('Sparse SMA')
    expect(wrapper.get('[data-test="backtest-status"]').text()).toBe('failed')
    expect(wrapper.get('[data-test="backtest-detail"]').text()).toContain('失败')
    expect(wrapper.findAll('.backtest-result-metric strong').map(metric => metric.text())).toEqual([
      '--', '--', '--', '--',
    ])
    expect(wrapper.get('[data-test="backtest-trust-summary"]').text()).toContain('sparse-sma')
    expect(wrapper.get('[data-test="backtest-trust-summary"]').text()).toContain('RB0')
    expect(wrapper.get('[data-test="backtest-trust-summary"]').text()).toContain('0')
    expect(wrapper.get('[data-test="backtest-workflow-guide"]').text())
      .toContain('worker failed to produce a result')
  })

  it('loads and displays chart data when switching between analysis and kline views', async () => {
    vi.mocked(analyticsApi.getMonthlyReturns).mockResolvedValueOnce({
      returns: [],
      years: [2023, 2024],
      summary: { 2024: -0.02, 2023: 0.1 },
    } as any)
    vi.mocked(analyticsApi.getKlineWithSignals).mockResolvedValueOnce({
      symbol: 'BTC',
      klines: [{ date: '2024-01-02', open: 1, high: 2, low: 0.5, close: 1.5, volume: 100 }],
      signals: [],
      indicators: {},
    } as any)
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()
    const vm = wrapper.vm as any

    vm.activeTab = 'analysis'
    await flushPromises()
    expect(analyticsApi.getMonthlyReturns).toHaveBeenCalledWith('t1')
    expect(vm.annualReturnEntries).toEqual([
      { year: '2023', value: 0.1 },
      { year: '2024', value: -0.02 },
    ])
    expect(wrapper.find('.backtest-annual-item').text()).toContain('2023')
    const negativeAnnualRow = wrapper.findAll('.backtest-annual-item')
      .find((item) => item.text().includes('-2.00%'))
    expect(negativeAnnualRow?.text()).toContain('2024')

    vm.activeTab = 'kline'
    await flushPromises()
    expect(analyticsApi.getKlineWithSignals).toHaveBeenCalledWith('t1')
    expect(vm.klineData.klines[0].date).toBe('2024-01-02')

    vm.activeTab = 'equity'
    await wrapper.vm.$nextTick()
    expect(wrapper.find('.backtest-analysis-grid').exists()).toBe(false)
    expect(wrapper.find('[data-test="equity-curve"]').exists()).toBe(true)
  })

  it('keeps chart sections usable when lazy chart requests fail', async () => {
    vi.mocked(analyticsApi.getKlineWithSignals).mockRejectedValueOnce(new Error('kline unavailable'))
    vi.mocked(analyticsApi.getMonthlyReturns).mockRejectedValueOnce(new Error('returns unavailable'))
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()
    const vm = wrapper.vm as any

    vm.activeTab = 'kline'
    await flushPromises()
    expect(analyticsApi.getKlineWithSignals).toHaveBeenCalledWith('t1')
    expect(vm.klineData).toEqual({ symbol: 'BTC', klines: [], signals: [], indicators: {} })

    vm.activeTab = 'analysis'
    await flushPromises()
    expect(analyticsApi.getMonthlyReturns).toHaveBeenCalledWith('t1')
    expect(vm.monthlyReturns).toEqual({ returns: [], years: [], summary: {} })
    expect(wrapper.find('.backtest-annual-empty').exists()).toBe(true)
  })

  it('exports the displayed backtest as CSV', async () => {
    const wrapper = mount(BacktestResultPage, {
      global: {
        stubs: {
          ...elStubs,
          EquityCurve: true,
          DrawdownChart: true,
          TradeRecordsTable: true,
          TradeSignalChart: true,
          ReturnHeatmap: true,
          MetricCard: true,
          PerformancePanel: true,
        },
      },
    })
    await flushPromises()

    const exportButton = wrapper.get('.backtest-result-actions .el-button')
    expect(exportButton.text()).toContain('导出CSV')
    await exportButton.trigger('click')

    expect(analyticsApi.exportResults).toHaveBeenCalledWith('t1', 'csv')
  })
})
