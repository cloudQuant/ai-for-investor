import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ScannerPage from '@/views/ScannerPage.vue'
import { mountWithPlugins } from '../mountWithPlugins'

const apiMocks = vi.hoisted(() => ({
  runScanner: vi.fn(),
  getScannerTask: vi.fn(),
  listScannerUniversePools: vi.fn(),
  refreshScannerUniversePool: vi.fn(),
  saveCustomScannerUniversePool: vi.fn(),
  precomputeScannerUniversePool: vi.fn(),
  listScannerPlans: vi.fn(),
  createScannerPlan: vi.fn(),
  updateScannerPlan: vi.fn(),
  deleteScannerPlan: vi.fn(),
  createScannerPlanResultTable: vi.fn(),
  deleteScannerPlanResultTable: vi.fn(),
  runScannerPlan: vi.fn(),
  runDailyScannerPlans: vi.fn(),
  listScannerPlanRuns: vi.fn(),
}))

vi.mock('@/api/marketIntel', () => ({
  marketIntelApi: apiMocks,
}))

describe('ScannerPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.listScannerUniversePools.mockResolvedValue({
      items: [
        {
          id: 'hs300',
          name: '沪深300',
          description: '最新沪深300成分股',
          category: 'equity_index',
          source: 'akshare',
          instrument_count: 2,
          updated_at: '2026-06-19T04:00:00+00:00',
          is_custom: false,
          refreshable: true,
          instruments: [
            { symbol: '000001.SZ', name: '平安银行', asset_type: 'equity', exchange: 'SZSE' },
            { symbol: '600519.SH', name: '贵州茅台', asset_type: 'equity', exchange: 'SSE' },
          ],
        },
        {
          id: 'convertible_bond',
          name: '可转债',
          description: '沪深可转债实时行情',
          category: 'convertible_bond',
          source: 'akshare',
          instrument_count: 1,
          updated_at: '2026-06-19T04:00:00+00:00',
          is_custom: false,
          refreshable: true,
          instruments: [
            { symbol: '110000.SH', name: '测试转债', asset_type: 'convertible_bond', exchange: 'SSE' },
          ],
        },
      ],
      total: 2,
    })
    apiMocks.refreshScannerUniversePool.mockResolvedValue({
      id: 'hs300',
      name: '沪深300',
      description: '最新沪深300成分股',
      category: 'equity_index',
      source: 'akshare',
      instrument_count: 3,
      updated_at: '2026-06-19T05:00:00+00:00',
      is_custom: false,
      refreshable: true,
      last_refresh_status: 'ok',
      instruments: [
        { symbol: '000001.SZ', name: '平安银行', asset_type: 'equity', exchange: 'SZSE' },
        { symbol: '600519.SH', name: '贵州茅台', asset_type: 'equity', exchange: 'SSE' },
        { symbol: '300750.SZ', name: '宁德时代', asset_type: 'equity', exchange: 'SZSE' },
      ],
    })
    apiMocks.precomputeScannerUniversePool.mockResolvedValue({
      pool_id: 'hs300',
      lookback_days: 20,
      timeframe: '1d',
      total: 2,
      computed_at: '2026-06-19T05:10:00+00:00',
      cache_status: 'updated',
    })
    apiMocks.listScannerPlans.mockResolvedValue({
      items: [
        {
          id: 'plan-1',
          name: '沪深300动量日报',
          universe_pool_id: 'hs300',
          indicator_rules: [
            { metric: 'indicator', operator: '>=', value: 0.5, enabled: true },
            { metric: 'news_sentiment', operator: '>=', value: 0.4, enabled: true },
          ],
          condition: 'indicator >= 0.5 and news_sentiment >= 0.4',
          lookback_days: 20,
          timeframe: '1d',
          schedule_enabled: true,
          schedule_frequency: 'daily',
          status: 'active',
          result_table_status: 'missing',
        },
      ],
      total: 1,
    })
    apiMocks.createScannerPlan.mockResolvedValue({
      id: 'plan-2',
      name: '沪深300精选方案',
      universe_pool_id: 'hs300',
      indicator_rules: [
        { metric: 'indicator', operator: '>=', value: 0.5, enabled: true },
        { metric: 'news_sentiment', operator: '>=', value: 0.4, enabled: true },
      ],
      condition: 'indicator >= 0.5 and news_sentiment >= 0.4',
      lookback_days: 20,
      timeframe: '1d',
      schedule_enabled: true,
      schedule_frequency: 'daily',
      status: 'active',
      result_table_status: 'missing',
    })
    apiMocks.updateScannerPlan.mockResolvedValue({
      id: 'plan-1',
      name: '沪深300质量动量',
      universe_pool_id: 'hs300',
      indicator_rules: [
        { metric: 'factor', operator: '>=', value: 0.65, enabled: true },
        { metric: 'portfolio_exposure', operator: '<=', value: 0.2, enabled: true },
      ],
      condition: 'factor >= 0.65 and portfolio_exposure <= 0.2',
      lookback_days: 60,
      timeframe: '4h',
      schedule_enabled: true,
      schedule_frequency: 'daily',
      status: 'active',
      result_table_status: 'missing',
    })
    apiMocks.deleteScannerPlan.mockResolvedValue({ deleted: true })
    apiMocks.createScannerPlanResultTable.mockResolvedValue({
      id: 'plan-1',
      name: '沪深300动量日报',
      universe_pool_id: 'hs300',
      indicator_rules: [
        { metric: 'indicator', operator: '>=', value: 0.5, enabled: true },
        { metric: 'news_sentiment', operator: '>=', value: 0.4, enabled: true },
      ],
      condition: 'indicator >= 0.5 and news_sentiment >= 0.4',
      lookback_days: 20,
      timeframe: '1d',
      schedule_enabled: false,
      schedule_frequency: 'daily',
      status: 'active',
      result_table_name: 'scanner_plan_result_plan_1',
      result_table_status: 'ready',
    })
    apiMocks.deleteScannerPlanResultTable.mockResolvedValue({
      id: 'plan-1',
      name: '沪深300动量日报',
      universe_pool_id: 'hs300',
      indicator_rules: [
        { metric: 'indicator', operator: '>=', value: 0.5, enabled: true },
        { metric: 'news_sentiment', operator: '>=', value: 0.4, enabled: true },
      ],
      condition: 'indicator >= 0.5 and news_sentiment >= 0.4',
      lookback_days: 20,
      timeframe: '1d',
      schedule_enabled: false,
      schedule_frequency: 'daily',
      status: 'active',
      result_table_status: 'dropped',
    })
    apiMocks.runScannerPlan.mockResolvedValue({
      id: 'run-1',
      plan_id: 'plan-2',
      run_date: '2026-06-19',
      status: 'unavailable',
      data_status: 'unavailable',
      match_count: 1,
      matches: [{ symbol: '000001.SZ', name: '平安银行', price: 12.36, volume: 4200, indicator: 0.77, factor: 0.71, news_sentiment: 0.65, portfolio_exposure: 0.18, provider: 'akshare' }],
      metrics: { factor_cache_status: 'hit' },
    })
    apiMocks.runDailyScannerPlans.mockResolvedValue({
      run_date: '2026-06-19',
      total: 1,
      items: [
        {
          id: 'run-daily-1',
          plan_id: 'plan-2',
          run_date: '2026-06-19',
          status: 'legacy_unverified',
          data_status: 'legacy_unverified',
          match_count: 1,
          matches: [{ symbol: '000001.SZ', name: '平安银行', indicator: 0.77 }],
          metrics: { factor_cache_status: 'hit' },
        },
      ],
    })
    apiMocks.listScannerPlanRuns.mockResolvedValue({
      items: [
        {
          id: 'run-1',
          plan_id: 'plan-2',
          run_date: '2026-06-19',
          status: 'legacy_unverified',
          data_status: 'legacy_unverified',
          match_count: 1,
          matches: [{ symbol: '000001.SZ', name: '平安银行', indicator: 0.77 }],
          metrics: { factor_cache_status: 'hit' },
        },
      ],
      total: 1,
    })
    apiMocks.saveCustomScannerUniversePool.mockResolvedValue({
      id: 'custom-watch',
      name: '我的观察池',
      description: '用户自定义',
      category: 'custom',
      source: 'custom',
      instrument_count: 2,
      updated_at: '2026-06-19T05:00:00+00:00',
      is_custom: true,
      refreshable: false,
      instruments: [
        { symbol: '300750.SZ', name: '300750.SZ', asset_type: 'custom' },
        { symbol: '110000.SH', name: '110000.SH', asset_type: 'custom' },
      ],
    })
    apiMocks.runScanner.mockResolvedValue({
      task_id: 'task-1',
      status: 'completed',
      lookback_days: 20,
      timeframe: '1d',
      universe_pool_id: 'hs300',
      universe_count: 2,
      matches: [{ symbol: '000001.SZ', name: '平安银行', price: 12.36, volume: 4200, indicator: 0.77, factor: 0.71, news_sentiment: 0.65, portfolio_exposure: 0.18, provider: 'akshare' }],
    })
    apiMocks.getScannerTask.mockResolvedValue({
      task_id: 'task-1',
      status: 'completed',
      lookback_days: 20,
      timeframe: '1d',
      universe_pool_id: 'hs300',
      universe_count: 2,
      matches: [{ symbol: '000001.SZ', name: '平安银行', price: 12.36, volume: 4200, indicator: 0.77, factor: 0.71, news_sentiment: 0.65, portfolio_exposure: 0.18, provider: 'akshare' }],
    })
  })

  it('keeps scanner execution disabled and hides legacy matches from the current board', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()
    expect(wrapper.text()).toContain('条件扫描')
    expect(apiMocks.listScannerUniversePools).toHaveBeenCalled()
    expect(apiMocks.listScannerPlans).toHaveBeenCalled()

    await (wrapper.vm as any).run()
    await flushPromises()

    expect(apiMocks.runScanner).not.toHaveBeenCalled()
    expect(apiMocks.getScannerTask).not.toHaveBeenCalled()
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    expect((wrapper.vm as any).matches).toEqual([])
    expect(wrapper.text()).toContain('扫描执行暂不可用')
    expect(wrapper.find('.scanner-workbench').exists()).toBe(true)
    expect(wrapper.find('.scanner-query-panel').exists()).toBe(true)
    expect(wrapper.find('.scanner-metric-grid').exists()).toBe(false)
    expect(wrapper.find('.scanner-results-panel').exists()).toBe(false)
    expect(wrapper.find('.scanner-pool-selector').exists()).toBe(false)
    expect(wrapper.find('.scanner-plan-summary').exists()).toBe(false)
    expect(wrapper.find('.scanner-pool-manager-panel').exists()).toBe(false)
    expect(wrapper.text()).toContain('沪深300')
    expect(wrapper.text()).toContain('新建方案')
    expect(wrapper.text()).toContain('编辑方案')
    expect(wrapper.text()).toContain('未验证的历史记录')
    expect(wrapper.text()).not.toContain('77.00%')
    expect(wrapper.text()).not.toContain('18.00%')
    expect(wrapper.text()).not.toContain('命中数')
    expect(wrapper.text()).not.toContain('条命中')
  })

  it('does not start a scan automatically when no saved plan exists', async () => {
    apiMocks.listScannerPlans.mockResolvedValueOnce({ items: [], total: 0 })

    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    expect(apiMocks.listScannerUniversePools).toHaveBeenCalled()
    expect(apiMocks.listScannerPlans).toHaveBeenCalled()
    expect(apiMocks.runScanner).not.toHaveBeenCalled()
    expect(wrapper.find('.scanner-workbench').exists()).toBe(true)
  })

  it('manages real universe pools in a dialog and saves a custom pool', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    ;(wrapper.vm as any).openEditPlanDialog('plan-1')
    await flushPromises()

    expect(wrapper.find('.scanner-pool-manager-panel').exists()).toBe(true)
    expect(wrapper.find('.scanner-manager-toolbar').exists()).toBe(true)
    expect(wrapper.find('.scanner-manager-pool-list').exists()).toBe(false)
    expect(wrapper.find('.scanner-manager-detail').exists()).toBe(true)
    await (wrapper.vm as any).refreshPool('hs300')
    await flushPromises()

    expect(apiMocks.refreshScannerUniversePool).toHaveBeenCalledWith('hs300')
    expect((wrapper.vm as any).selectedPool?.instrument_count).toBe(3)

    ;(wrapper.vm as any).customPoolName = '我的观察池'
    ;(wrapper.vm as any).customSymbolText = '300750.SZ, 110000.SH'
    await (wrapper.vm as any).saveCustomPool()
    await flushPromises()

    expect(apiMocks.saveCustomScannerUniversePool).toHaveBeenCalledWith({
      name: '我的观察池',
      description: '',
      instruments: [
        { symbol: '300750.SZ', name: '300750.SZ', asset_type: 'custom' },
        { symbol: '110000.SH', name: '110000.SH', asset_type: 'custom' },
      ],
    })
    expect((wrapper.vm as any).selectedPoolId).toBe('custom-watch')
  })

  it('retains rule configuration while keeping metric precomputation and execution closed', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    ;(wrapper.vm as any).openEditPlanDialog('plan-1')
    await flushPromises()

    expect(wrapper.find('.scanner-indicator-manager-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('管理指标')

    ;(wrapper.vm as any).indicatorRules = [
      { id: 'rule-1', metric: 'change_pct', operator: '>=', value: 0.01, enabled: true },
      { id: 'rule-2', metric: 'factor', operator: '>=', value: 0.65, enabled: true },
      { id: 'rule-3', metric: 'portfolio_exposure', operator: '<=', value: 0.2, enabled: false },
    ]
    await flushPromises()

    await (wrapper.vm as any).precomputePoolMetrics('hs300')
    await flushPromises()

    expect(apiMocks.precomputeScannerUniversePool).not.toHaveBeenCalled()
    expect((wrapper.vm as any).metricSnapshotInfo).toBeNull()

    await (wrapper.vm as any).run()
    await flushPromises()

    expect(apiMocks.runScanner).not.toHaveBeenCalled()
    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
  })

  it('saves a scanner plan with scheduling disabled and keeps batch runs unavailable', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    expect(wrapper.find('.scanner-plan-panel').exists()).toBe(true)
    expect(wrapper.text()).toContain('方案中心')
    expect(wrapper.text()).toContain('新建方案')
    expect(wrapper.find('.scanner-plan-summary').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('生成条件')

    ;(wrapper.vm as any).planName = '沪深300精选方案'
    await (wrapper.vm as any).saveScannerPlan()
    await flushPromises()

    expect(apiMocks.createScannerPlan).toHaveBeenCalledWith({
      name: '沪深300精选方案',
      universe_pool_id: 'hs300',
      indicator_rules: [
        { id: 'plan-rule-0', metric: 'indicator', operator: '>=', value: 0.5, enabled: true },
        { id: 'plan-rule-1', metric: 'news_sentiment', operator: '>=', value: 0.4, enabled: true },
      ],
      condition: 'indicator >= 0.5 and news_sentiment >= 0.4',
      lookback_days: 20,
      timeframe: '1d',
      schedule_enabled: false,
      schedule_frequency: 'daily',
    })
    expect((wrapper.vm as any).selectedPlanId).toBe('plan-2')

    await (wrapper.vm as any).runSelectedPlan()
    await flushPromises()

    expect(apiMocks.runScannerPlan).not.toHaveBeenCalled()
    expect(apiMocks.listScannerPlanRuns).toHaveBeenCalledWith('plan-2')
    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).planRuns[0].run_date).toBe('2026-06-19')

    await (wrapper.vm as any).runDailyPlans()
    await flushPromises()

    expect(apiMocks.runDailyScannerPlans).not.toHaveBeenCalled()
  })

  it('does not present unverified legacy metadata as completed or current', async () => {
    apiMocks.listScannerUniversePools.mockResolvedValueOnce({
      items: [
        {
          id: 'hs300',
          name: '沪深300',
          instrument_count: 1,
          metric_snapshot: {
            data_status: 'unavailable',
            computed_at: '2026-06-19T04:00:00+00:00',
            total: 1,
          },
          instruments: [{ symbol: '000001.SZ', name: '平安银行' }],
        },
      ],
      total: 1,
    })
    apiMocks.listScannerPlanRuns.mockResolvedValueOnce({
      items: [
        {
          id: 'old-unlabeled-run',
          plan_id: 'plan-1',
          run_date: '2026-06-19',
          status: 'completed',
          matches: [{ symbol: '000001.SZ', indicator: 0.91 }],
          match_count: 1,
        },
      ],
      total: 1,
    })

    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    expect((wrapper.vm as any).metricSnapshotLabel).toBe('不可用；预计算已暂停')
    expect((wrapper.vm as any).latestPlanRunLabel).toContain('暂不可用')

    ;(wrapper.vm as any).scannerPlans[0].result_table_name = 'scanner_plan_result_plan_1'
    ;(wrapper.vm as any).scannerPlans[0].result_table_status = 'ready'
    ;(wrapper.vm as any).scannerPlans[0].result_table_data_status = 'unavailable'
    expect((wrapper.vm as any).selectedPlanResultTableLabel).toContain('历史内容未验证')

    ;(wrapper.vm as any).matches = [{ symbol: '000001.SZ' }]
    ;(wrapper.vm as any).taskStatus = 'completed'
    ;(wrapper.vm as any).selectedPlanId = 'plan-2'
    ;(wrapper.vm as any).scannerPlans.push({
      id: 'plan-2',
      name: '第二个方案',
      universe_pool_id: 'hs300',
      indicator_rules: [],
      condition: 'price > 0',
      lookback_days: 20,
      timeframe: '1d',
      schedule_enabled: false,
      schedule_frequency: 'daily',
      status: 'active',
    })
    ;(wrapper.vm as any).applySelectedPlan()
    await flushPromises()

    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    wrapper.unmount()
  })

  it('does not auto-load historical matches even if a legacy response claims verified', async () => {
    apiMocks.listScannerPlanRuns.mockResolvedValueOnce({
      items: [
        {
          id: 'old-claimed-verified-run',
          plan_id: 'plan-1',
          run_date: '2026-06-19',
          status: 'completed',
          data_status: 'verified',
          matches: [{ symbol: '000001.SZ', indicator: 0.91 }],
          match_count: 1,
        },
      ],
      total: 1,
    })

    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    expect((wrapper.vm as any).latestPlanRunLabel).toContain('暂不可用')
    expect(wrapper.get('.scanner-match-board .scanner-row-count').text()).toContain('0 项结果')
    wrapper.unmount()
  })

  it('accepts plan matches only from a completed verified run', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()
    ;(wrapper.vm as any).scannerExecutionUnavailable = false

    ;(wrapper.vm as any).loadRunResult({
      id: 'running-verified-run',
      plan_id: 'plan-1',
      run_date: '2026-06-19',
      status: 'running',
      data_status: 'verified',
      match_count: 1,
      matches: [{ symbol: '000001.SZ', indicator: 0.91 }],
    })
    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')

    ;(wrapper.vm as any).loadRunResult({
      id: 'completed-verified-run',
      plan_id: 'plan-1',
      run_date: '2026-06-19',
      status: 'completed',
      data_status: 'verified',
      match_count: 1,
      matches: [{ symbol: '000001.SZ', indicator: 0.91 }],
    })
    expect((wrapper.vm as any).matches).toHaveLength(1)
    expect((wrapper.vm as any).taskStatus).toBe('completed')
    wrapper.unmount()
  })

  it('rejects immediate scan results without an explicit verified data status', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()
    ;(wrapper.vm as any).scannerExecutionUnavailable = false
    apiMocks.runScanner.mockResolvedValueOnce({
      task_id: 'task-unverified',
      status: 'completed',
      matches: [{ symbol: '000001.SZ', indicator: 0.91 }],
    })

    await (wrapper.vm as any).run()
    await flushPromises()

    expect(apiMocks.getScannerTask).not.toHaveBeenCalled()
    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    wrapper.unmount()
  })

  it('rejects task matches when the polled task lacks a verified data status', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()
    ;(wrapper.vm as any).scannerExecutionUnavailable = false
    apiMocks.runScanner.mockResolvedValueOnce({
      task_id: 'task-with-unverified-poll',
      status: 'submitted',
      data_status: 'verified',
    })
    apiMocks.getScannerTask.mockResolvedValueOnce({
      task_id: 'task-with-unverified-poll',
      status: 'completed',
      matches: [{ symbol: '000001.SZ', indicator: 0.91 }],
    })

    await (wrapper.vm as any).run()
    await flushPromises()

    expect(apiMocks.getScannerTask).toHaveBeenCalledWith('task-with-unverified-poll')
    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    wrapper.unmount()
  })

  it('does not use batch responses to populate current results while execution is unavailable', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    apiMocks.runScannerPlan.mockResolvedValueOnce({
      id: 'run-returned',
      plan_id: 'plan-2',
      run_date: '2026-06-19',
      status: 'completed',
      match_count: 1,
      matches: [{ symbol: '000001.SZ', name: '平安银行', indicator: 0.77 }],
      metrics: { factor_cache_status: 'hit' },
    })

    await (wrapper.vm as any).runSelectedPlan()
    await flushPromises()

    expect(apiMocks.runScannerPlan).not.toHaveBeenCalled()
    expect((wrapper.vm as any).selectedPlanId).toBe('plan-1')
    expect((wrapper.vm as any).matches).toEqual([])
  })

  it('creates and edits scanner plans from the plan editor dialog', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    expect((wrapper.vm as any).planDialogVisible).toBe(false)
    expect(wrapper.find('.scanner-plan-editor-panel').exists()).toBe(false)

    ;(wrapper.vm as any).openNewPlanDialog()
    await flushPromises()

    expect(wrapper.find('.scanner-plan-editor-dialog').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-dialog-shell').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-dialog-shell.is-create').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-dialog-aside').exists()).toBe(false)
    expect(wrapper.find('.scanner-plan-primary-section').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-universe-section').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-indicator-section').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-result-section').exists()).toBe(false)
    expect(wrapper.find('.scanner-plan-primary-section .scanner-plan-pool-field').exists()).toBe(false)
    expect(wrapper.find('.scanner-pool-manager-panel').exists()).toBe(true)
    expect(wrapper.find('.scanner-manager-toolbar').exists()).toBe(true)
    expect(wrapper.find('.scanner-manager-layout').exists()).toBe(true)
    expect(wrapper.find('.scanner-manager-overview').exists()).toBe(true)
    expect(wrapper.find('.scanner-manager-pool-list').exists()).toBe(false)
    expect(wrapper.find('.scanner-plan-editor-parameters').exists()).toBe(true)
    expect(wrapper.find('.scanner-indicator-manager-panel').exists()).toBe(true)

    ;(wrapper.vm as any).planName = '沪深300精选方案'
    await (wrapper.vm as any).savePlanFromDialog()
    await flushPromises()

    expect(apiMocks.createScannerPlan).toHaveBeenCalledWith({
      name: '沪深300精选方案',
      universe_pool_id: 'hs300',
      indicator_rules: [],
      condition: 'price > 0',
      lookback_days: 20,
      timeframe: '1d',
      schedule_enabled: false,
      schedule_frequency: 'daily',
    })

    ;(wrapper.vm as any).openEditPlanDialog('plan-1')
    await flushPromises()
    expect(wrapper.find('.scanner-plan-dialog-shell.is-edit').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-dialog-aside').exists()).toBe(true)
    expect(wrapper.find('.scanner-plan-result-section').exists()).toBe(true)

    ;(wrapper.vm as any).planName = '沪深300质量动量'
    ;(wrapper.vm as any).lookbackDays = 60
    ;(wrapper.vm as any).timeframe = '4h'
    ;(wrapper.vm as any).indicatorRules = [
      { id: 'rule-1', metric: 'factor', operator: '>=', value: 0.65, enabled: true },
      { id: 'rule-2', metric: 'portfolio_exposure', operator: '<=', value: 0.2, enabled: true },
    ]
    await (wrapper.vm as any).savePlanFromDialog()
    await flushPromises()

    expect(apiMocks.updateScannerPlan).toHaveBeenCalledWith('plan-1', {
      name: '沪深300质量动量',
      universe_pool_id: 'hs300',
      indicator_rules: [
        { id: 'rule-1', metric: 'factor', operator: '>=', value: 0.65, enabled: true },
        { id: 'rule-2', metric: 'portfolio_exposure', operator: '<=', value: 0.2, enabled: true },
      ],
      condition: 'factor >= 0.65 and portfolio_exposure <= 0.2',
      lookback_days: 60,
      timeframe: '4h',
      schedule_enabled: true,
      schedule_frequency: 'daily',
      status: 'active',
    })

    await (wrapper.vm as any).createSelectedPlanResultTable()
    await flushPromises()
    expect(apiMocks.createScannerPlanResultTable).toHaveBeenCalledWith('plan-1')

    await (wrapper.vm as any).deleteSelectedPlanResultTable()
    await flushPromises()
    expect(apiMocks.deleteScannerPlanResultTable).toHaveBeenCalledWith('plan-1')

    await (wrapper.vm as any).deleteSelectedPlan()
    await flushPromises()
    expect(apiMocks.deleteScannerPlan).toHaveBeenCalledWith('plan-1')
  })

  it.each([
    ['missing schedule_enabled', 'schedule_enabled', undefined],
    ['invalid schedule_enabled', 'schedule_enabled', 'true'],
    ['missing schedule_frequency', 'schedule_frequency', undefined],
    ['invalid schedule_frequency', 'schedule_frequency', 'weekly'],
    ['missing status', 'status', undefined],
    ['invalid status', 'status', 'unknown'],
  ] as const)('blocks plan edits with %s', async (_label, field, value) => {
    apiMocks.listScannerPlans.mockResolvedValueOnce({
      items: [
        {
          id: 'plan-1',
          name: '沪深300动量日报',
          universe_pool_id: 'hs300',
          indicator_rules: [],
          condition: 'price > 0',
          lookback_days: 20,
          timeframe: '1d',
          schedule_enabled: true,
          schedule_frequency: 'daily',
          status: 'active',
          [field]: value,
        },
      ],
      total: 1,
    })
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    ;(wrapper.vm as any).openEditPlanDialog('plan-1')
    await flushPromises()

    const saveButton = wrapper.findAll('.scanner-plan-editor-toolbar button')
      .find((button) => button.text().includes('保存方案'))
    expect(saveButton).toBeDefined()
    expect((saveButton!.element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.text()).toContain('方案调度字段缺失或不受支持')

    await (wrapper.vm as any).savePlanFromDialog()
    expect(apiMocks.updateScannerPlan).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('builds a live condition from enabled rules and displays an empty scan result', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    expect(wrapper.get('.scanner-active-condition strong').text())
      .toBe('indicator >= 0.5 and news_sentiment >= 0.4')

    const editPlanButton = wrapper.findAll('.scanner-plan-actions button')
      .find((button) => button.text().includes('编辑方案'))
    expect(editPlanButton).toBeDefined()
    await editPlanButton!.trigger('click')
    await flushPromises()

    await wrapper.get('.scanner-indicator-footer button').trigger('click')
    expect(wrapper.findAll('.scanner-indicator-rule')).toHaveLength(3)
    await wrapper.get('.scanner-indicator-rule:last-child button').trigger('click')
    expect(wrapper.findAll('.scanner-indicator-rule')).toHaveLength(2)

    const enabledRuleInputs = wrapper.findAll('.scanner-indicator-rule input[type="checkbox"]')
    expect(enabledRuleInputs).toHaveLength(2)
    await enabledRuleInputs[0].setValue(false)
    await enabledRuleInputs[1].setValue(false)
    await wrapper.vm.$nextTick()
    expect(wrapper.get('.scanner-active-condition strong').text()).toBe('price > 0')

    const emptyResult: Record<string, unknown> = {
      status: 'unavailable',
      data_status: 'unavailable',
      matches: [],
    }
    apiMocks.runScanner.mockResolvedValueOnce(emptyResult)
    await (wrapper.vm as any).run()
    await flushPromises()

    expect(apiMocks.runScanner).not.toHaveBeenCalled()
    expect(apiMocks.getScannerTask).not.toHaveBeenCalled()
    expect(wrapper.get('.scanner-status-tag').text()).toBe('暂不可用')
    expect(wrapper.get('.scanner-empty-state').text()).toContain('扫描执行恢复')
    wrapper.unmount()
  })

  it('clears legacy matches when a scan is requested while unavailable', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()
    ;(wrapper.vm as any).matches = [{ symbol: '000001.SZ' }]
    ;(wrapper.vm as any).taskStatus = 'completed'

    await (wrapper.vm as any).run()
    await flushPromises()

    expect(apiMocks.runScanner).not.toHaveBeenCalled()
    expect((wrapper.vm as any).loading).toBe(false)
    expect((wrapper.vm as any).matches).toEqual([])
    expect((wrapper.vm as any).taskStatus).toBe('unavailable')
    expect(wrapper.get('.scanner-match-board .scanner-row-count').text()).toContain('0 项结果')
    expect(wrapper.find('.scanner-empty-state').exists()).toBe(true)
    wrapper.unmount()
  })

  it('saves a custom universe through its visible form and deduplicates symbols', async () => {
    const wrapper = mountWithPlugins(ScannerPage)
    await flushPromises()

    const newPlanButton = wrapper.findAll('.scanner-plan-actions button')
      .find((button) => button.text().includes('新建方案'))
    expect(newPlanButton).toBeDefined()
    await newPlanButton!.trigger('click')
    await flushPromises()

    await wrapper.get('.scanner-custom-grid input').setValue('我的观察池')
    await wrapper.get('.scanner-custom-grid textarea').setValue('300750.SZ, 110000.SH\n300750.SZ')
    await wrapper.get('.scanner-custom-actions button').trigger('click')
    await flushPromises()

    expect(apiMocks.saveCustomScannerUniversePool).toHaveBeenCalledWith({
      name: '我的观察池',
      description: '',
      instruments: [
        { symbol: '300750.SZ', name: '300750.SZ', asset_type: 'custom' },
        { symbol: '110000.SH', name: '110000.SH', asset_type: 'custom' },
      ],
    })
    expect((wrapper.vm as any).selectedPoolId).toBe('custom-watch')
    expect((wrapper.vm as any).customPoolName).toBe('')
    wrapper.unmount()
  })
})
