import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { ElMessage } from 'element-plus'
import PortfolioPage from '@/views/PortfolioPage.vue'
import { portfolioApi } from '@/api/portfolio'
import { workspaceApi } from '@/api/workspace'
import { elStubs } from '@/test/stubs'

const chartMock = vi.hoisted(() => {
  const charts: Array<any> = []
  const init = vi.fn((dom: HTMLElement) => {
    const chart = {
      getDom: () => dom,
      setOption: vi.fn(),
      resize: vi.fn(),
      dispose: vi.fn(),
    }
    charts.push(chart)
    return chart
  })
  return { charts, init }
})

vi.mock('echarts', () => ({ init: chartMock.init }))

const rowAwareElTable = defineComponent({
  inheritAttrs: false,
  props: ['data'],
  setup(props, { attrs, slots }) {
    return () => h('div', { ...attrs, class: ['el-table', attrs.class] },
      ((props.data || []) as unknown[]).map((row, rowIndex) => h(
        'div',
        { class: 'el-table-row', 'data-row-index': rowIndex },
        (slots.default?.() || []).map((column: any) => {
          const columnProps = column.props || {}
          const renderCell = column.children?.default
          const value = typeof renderCell === 'function'
            ? renderCell({ row, $index: rowIndex })
            : columnProps.prop
              ? (row as Record<string, unknown>)[columnProps.prop]
              : ''
          return h('div', {
            class: 'el-table-cell',
            'data-column': columnProps.label || columnProps.prop || '',
          }, [
            h('span', { class: 'el-table-cell__label' }, String(columnProps.label || '')),
            h('span', { class: 'el-table-cell__value' }, Array.isArray(value) ? value : [value]),
          ])
        }),
      )),
    )
  },
})

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
}))

// Use the actual zh-CN locale so `t('portfolio.unitYi')` -> '亿' for assertions
// like formatMoney(-2e8) -> '-2.00亿'. Aligns with the global setup.ts mock.
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

vi.mock('@/api/strategy', () => ({
  strategyApi: {
    getTemplates: vi.fn().mockResolvedValue({ templates: [], total: 0 }),
  },
}))

vi.mock('@/api/portfolio', () => ({
  portfolioApi: {
    getOverview: vi.fn().mockResolvedValue({
      total_assets: 100000, total_cash: 50000, total_position_value: 50000, net_position_value: 50000,
      total_initial_capital: 80000, total_pnl: 20000, total_pnl_pct: 25,
      strategy_count: 2, running_count: 1, strategies: [
        { strategy_id: 's1', strategy_name: 'SMA', status: 'running', assets: 60000, pnl: 10000, pnl_pct: 20 },
      ],
    }),
    listCompositionVersions: vi.fn().mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 50, has_more: false,
    }),
    getCompositionProjection: vi.fn().mockResolvedValue({
      portfolio_ref: 'empty',
      membership_version: 1,
      source_type: 'live',
      source_status: 'no_account_members',
      base_currency: 'USD',
      projection_kind: 'display_only',
      creditable: false,
      overlap_policy: 'non_additive_display_only',
      account_total: { status: 'not_collected', currency: 'USD', value: null },
      accounts: [],
      strategies: [],
      strategy_attribution: {
        status: 'execution_attribution_not_collected',
        strategy_count: 0,
        attributed_value: null,
        unattributed_account_value: null,
        residual_basis: 'account total only; no strategy shares inferred',
      },
      coverage: { complete: false, code: 'EXECUTION_ATTRIBUTION_NOT_COLLECTED' },
    }),
    getPositions: vi.fn().mockResolvedValue({
      total: 0,
      positions: [],
      summary: {
        total_long_value: 0,
        total_short_value: 0,
        gross_market_value: 0,
        net_market_value: 0,
        total_pnl: 0,
        long_count: 0,
        short_count: 0,
        flat_count: 0,
      },
    }),
    getTrades: vi.fn().mockResolvedValue({
      total: 2,
      trades: [
        {
          strategy_id: 'unit-1',
          strategy_name: 'CTA 交易工作区 / RB 趋势',
          instance_id: 'unit-1',
          ref: 1,
          datetime: '2026-06-19 10:00:00',
          dtopen: '2026-06-19 09:30:00',
          dtclose: '2026-06-19 10:00:00',
          data_name: 'RB2510',
          direction: 'long',
          size: 2,
          price: 3600,
          value: 7200,
          commission: 3,
          pnl: 200,
          pnlcomm: 197,
          barlen: 12,
        },
        {
          strategy_id: 'idle-unit',
          strategy_name: '暂停工作区 / AG 趋势',
          instance_id: 'idle-unit',
          ref: 2,
          datetime: '2026-06-19 10:00:00',
          dtopen: '2026-06-19 09:30:00',
          dtclose: '2026-06-19 10:00:00',
          data_name: 'AG2512',
          direction: 'short',
          size: 1,
          price: 8000,
          value: 8000,
          commission: 3,
          pnl: -50,
          pnlcomm: -53,
          barlen: 8,
        },
      ],
    }),
    getEquity: vi.fn().mockResolvedValue({ dates: ['2024-01-01'], total_equity: [100000], total_drawdown: [0], strategies: [] }),
    getAllocation: vi.fn().mockResolvedValue({
      total: 7200,
      items: [{
        asset: 'RB2510',
        value: 7200,
        weight: 100,
        long_value: 7200,
        short_value: 0,
        net_value: 7200,
        position_count: 1,
      }],
    }),
  },
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    list: vi.fn().mockResolvedValue({
      total: 2,
      items: [
        {
          id: 'ws-running',
          user_id: 'u1',
          name: 'CTA 交易工作区',
          description: null,
          workspace_type: 'trading',
          settings: {},
          trading_config: {},
          unit_count: 2,
          completed_count: 0,
          status: 'running',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-02T00:00:00Z',
        },
        {
          id: 'ws-idle',
          user_id: 'u1',
          name: '暂停工作区',
          description: null,
          workspace_type: 'trading',
          settings: {},
          trading_config: {},
          unit_count: 1,
          completed_count: 0,
          status: 'idle',
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-02T00:00:00Z',
        },
      ],
    }),
    getTradingPositions: vi.fn().mockResolvedValue({
      positions: [
        {
          unit_id: 'unit-1',
          unit_name: 'RB 趋势',
          symbol: 'RB2510',
          symbol_name: '螺纹钢',
          trading_mode: 'live',
          long_position: 2,
          short_position: 0,
          avg_price: 3500,
          latest_price: 3600,
          position_pnl: 200,
          market_value: 7200,
          margin_value: 720,
          multiplier: 10,
          margin_rate: 0.1,
          leverage: 10,
          commission: 3.5,
          gross_pnl: 203.5,
          position_source: 'gateway',
          asset_spec_source: 'ctp_gateway',
          valuation_status: 'confirmed',
          valuation_warnings: [],
        },
        {
          unit_id: 'unit-flat',
          unit_name: '空仓单元',
          symbol: 'AG2512',
          symbol_name: '白银',
          trading_mode: 'live',
          long_position: 0,
          short_position: 0,
          avg_price: 0,
          latest_price: 0,
          position_pnl: 0,
          market_value: 0,
        },
      ],
      total_long_value: 999999,
      total_short_value: 888888,
      total_pnl: 777,
    }),
    getTradingDailySummary: vi.fn().mockResolvedValue({
      summaries: [
        {
          trading_date: '2026-06-19',
          daily_pnl: 200,
          trade_count: 3,
          cumulative_pnl: 1200,
          max_drawdown: 0.02,
        },
      ],
    }),
  },
}))

describe('PortfolioPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    chartMock.charts.splice(0)
  })

  const doMount = (renderTableRows = false) => mount(PortfolioPage, {
    global: {
      stubs: {
        ...elStubs,
        EquityCurve: true,
        ...(renderTableRows ? { 'el-table': rowAwareElTable } : {}),
      },
    },
  })

  it('selects owner-listed membership versions and renders source-aware values without legacy fallback', async () => {
    const liveProjection = {
      portfolio_ref: 'primary',
      membership_version: 2,
      source_type: 'live' as const,
      source_status: 'projected',
      base_currency: 'USD',
      projection_kind: 'display_only' as const,
      creditable: false as const,
      overlap_policy: 'non_additive_display_only' as const,
      account_total: { status: 'current', currency: 'USD', value: '1500' },
      accounts: [
        {
          member_ref: 'account-a', currency: 'USD', quality: 'fresh', cash: '200', value: '1000',
          included_in_total: true, duplicate_of_ref: null, detail_code: null,
        },
        {
          member_ref: 'account-a-alias', currency: 'USD', quality: 'fresh', cash: '200',
          value: '1000', included_in_total: false, duplicate_of_ref: 'account-a', detail_code: null,
        },
        {
          member_ref: 'account-b', currency: 'USD', quality: 'fresh', cash: '250', value: '500',
          included_in_total: true, duplicate_of_ref: null, detail_code: null,
        },
      ],
      strategies: [{
        strategy_ref: 'strategy-x',
        attribution_status: 'execution_attribution_not_collected',
        attributed_value: null,
      }],
      strategy_attribution: {
        status: 'execution_attribution_not_collected',
        strategy_count: 1,
        attributed_value: null,
        unattributed_account_value: '1500',
        residual_basis: 'account total only; no strategy shares inferred',
      },
      coverage: {
        complete: false,
        account_facts_complete: true,
        strategy_attribution_complete: false,
        code: 'EXECUTION_ATTRIBUTION_NOT_COLLECTED',
      },
    }
    const researchProjection = {
      ...liveProjection,
      portfolio_ref: 'research-set',
      membership_version: 1,
      source_type: 'research' as const,
      source_status: 'adapter_not_integrated',
      account_total: { status: 'not_collected', currency: 'USD', value: null },
      strategies: [],
      strategy_attribution: {
        ...liveProjection.strategy_attribution,
        strategy_count: 0,
        unattributed_account_value: null,
      },
      coverage: { complete: false, code: 'RESEARCH_FACT_ADAPTER_NOT_INTEGRATED' },
    }
    const conflictingProjection = {
      ...liveProjection,
      portfolio_ref: 'conflict-live',
      source_status: 'projected',
      account_total: { status: 'incomplete', currency: 'USD', value: null },
      accounts: [
        {
          member_ref: 'account-a', currency: 'USD', quality: 'fresh', cash: '200', value: '1000',
          included_in_total: false, duplicate_of_ref: null,
          detail_code: 'DUPLICATE_ACCOUNT_FACT_CONFLICT',
        },
        {
          member_ref: 'account-a-alias', currency: 'USD', quality: 'fresh', cash: '300',
          value: '1100', included_in_total: false, duplicate_of_ref: 'account-a',
          detail_code: 'DUPLICATE_ACCOUNT_FACT_CONFLICT',
        },
      ],
      strategies: [],
      strategy_attribution: {
        ...liveProjection.strategy_attribution,
        strategy_count: 0,
        unattributed_account_value: null,
      },
      coverage: {
        complete: false,
        account_facts_complete: false,
        strategy_attribution_complete: true,
        code: 'ACCOUNT_FACT_COVERAGE_INCOMPLETE',
      },
    }
    const firstPageItems = [
      {
        portfolio_ref: 'primary', membership_version: 2, source_type: 'live' as const,
        base_currency: 'USD', created_at: '2026-10-15T00:00:00Z',
      },
      {
        portfolio_ref: 'research-set', membership_version: 1, source_type: 'research' as const,
        base_currency: 'USD', created_at: '2026-10-14T00:00:00Z',
      },
      ...Array.from({ length: 48 }, (_, index) => ({
        portfolio_ref: `paper-set-${index + 1}`,
        membership_version: 1,
        source_type: 'paper' as const,
        base_currency: 'USD',
        created_at: '2026-10-13T00:00:00Z',
      })),
    ]
    vi.mocked(portfolioApi.listCompositionVersions)
      .mockResolvedValueOnce({
        items: firstPageItems,
        total: 52,
        page: 1,
        page_size: 50,
        has_more: true,
      })
      .mockResolvedValueOnce({
        items: [
          {
            portfolio_ref: 'primary', membership_version: 2, source_type: 'live',
            base_currency: 'USD', created_at: '2026-10-15T00:00:00Z',
          },
          {
            portfolio_ref: 'conflict-live', membership_version: 1, source_type: 'live',
            base_currency: 'USD', created_at: '2026-10-13T00:00:00Z',
          },
          {
            portfolio_ref: 'error-live', membership_version: 1, source_type: 'live',
            base_currency: 'USD', created_at: '2026-10-12T00:00:00Z',
          },
        ],
        total: 53,
        page: 2,
        page_size: 50,
        has_more: false,
      })
      .mockResolvedValueOnce({
        items: firstPageItems,
        total: 53,
        page: 1,
        page_size: 50,
        has_more: true,
      })
      .mockResolvedValueOnce({
        items: [
          {
            portfolio_ref: 'conflict-live', membership_version: 1, source_type: 'live',
            base_currency: 'USD', created_at: '2026-10-13T00:00:00Z',
          },
          {
            portfolio_ref: 'error-live', membership_version: 1, source_type: 'live',
            base_currency: 'USD', created_at: '2026-10-12T00:00:00Z',
          },
          {
            portfolio_ref: 'final-live', membership_version: 1, source_type: 'live',
            base_currency: 'USD', created_at: '2026-10-11T00:00:00Z',
          },
        ],
        total: 53,
        page: 2,
        page_size: 50,
        has_more: false,
      })
    vi.mocked(portfolioApi.getCompositionProjection)
      .mockResolvedValueOnce(liveProjection)
      .mockResolvedValueOnce(liveProjection)
      .mockResolvedValueOnce(researchProjection)
      .mockResolvedValueOnce(conflictingProjection)

    const wrapper = doMount()
    await flushPromises()
    expect(wrapper.find('[data-test="portfolio-hero"]').exists()).toBe(true)
    const legacyOverviewCalls = vi.mocked(portfolioApi.getOverview).mock.calls.length

    await wrapper.get('[data-test="portfolio-mode-composition"]').trigger('click')
    await flushPromises()
    expect(portfolioApi.listCompositionVersions).toHaveBeenCalledWith(1, 50)
    expect(portfolioApi.getCompositionProjection).toHaveBeenNthCalledWith(1, 'primary', 2)
    expect(wrapper.find('[data-test="portfolio-composition-view"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="portfolio-hero"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('1500 USD')
    expect(wrapper.get('[data-test="portfolio-composition-attributed-value"]').text()).toBe('不可用')
    expect(wrapper.get('[data-test="portfolio-composition-residual"]').text()).toBe('1500 USD')
    expect(wrapper.get('[data-test="portfolio-composition-attribution-status"]').text())
      .toContain('尚未采集执行归属')
    expect(wrapper.text()).toContain('未计入账户总额')
    expect(wrapper.text()).toContain('不会推算策略份额')
    expect(wrapper.text()).toContain('不能重复授信')

    await wrapper.get('[data-test="portfolio-composition-load-more"]').trigger('click')
    await flushPromises()
    expect(portfolioApi.listCompositionVersions).toHaveBeenNthCalledWith(2, 2, 50)
    expect(portfolioApi.listCompositionVersions).toHaveBeenNthCalledWith(3, 1, 50)
    expect(wrapper.get('[data-test="portfolio-composition-list-changed"]')
      .text()).toContain('列表发生变化')
    const selector = wrapper.get<HTMLSelectElement>(
      '[data-test="portfolio-composition-version-select"]',
    )
    await wrapper.get('[data-test="portfolio-composition-load-more"]').trigger('click')
    await flushPromises()
    expect(portfolioApi.listCompositionVersions).toHaveBeenNthCalledWith(4, 2, 50)
    expect(selector.findAll('option').filter(option => (
      option.attributes('value')?.startsWith('[')
    ))).toHaveLength(53)
    expect(selector.findAll('option').filter(option => (
      option.attributes('value') === JSON.stringify(['primary', 2])
    ))).toHaveLength(1)
    await selector.setValue(JSON.stringify(['research-set', 1]))
    await flushPromises()
    expect(portfolioApi.getCompositionProjection).toHaveBeenNthCalledWith(
      3,
      'research-set',
      1,
    )
    expect(wrapper.get('[data-test="portfolio-composition-adapter-unavailable"]').text())
      .toContain('尚未接入事实适配器')
    expect(wrapper.get('[data-test="portfolio-composition-source-status"]').text())
      .toContain('尚未接入事实适配器')
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('不可用')
    expect(wrapper.find('[data-test="portfolio-overview"]').exists()).toBe(false)
    expect(vi.mocked(portfolioApi.getOverview).mock.calls).toHaveLength(legacyOverviewCalls)

    await selector.setValue(JSON.stringify(['conflict-live', 1]))
    await flushPromises()
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('不可用')
    expect(wrapper.text()).toContain('DUPLICATE_ACCOUNT_FACT_CONFLICT')
    expect(wrapper.text()).toContain('与 account-a 是同一账户')
    expect(wrapper.findAll('[data-test="portfolio-composition-account-detail-code"]')).toHaveLength(2)
    expect(wrapper.findAll('[data-test="portfolio-composition-account-detail-code"]')
      .every(node => node.text().includes('DUPLICATE_ACCOUNT_FACT_CONFLICT'))).toBe(true)

    vi.mocked(portfolioApi.getCompositionProjection)
      .mockRejectedValueOnce(new Error('selected projection unavailable'))
    await selector.setValue(JSON.stringify(['error-live', 1]))
    await flushPromises()
    expect(wrapper.get('[data-test="portfolio-composition-error"]').text())
      .toContain('selected projection unavailable')
    expect(wrapper.find('[data-test="portfolio-hero"]').exists()).toBe(false)
    expect(vi.mocked(portfolioApi.getOverview).mock.calls).toHaveLength(legacyOverviewCalls)
  })

  it('mounts without error', () => {
    expect(doMount().exists()).toBe(true)
  })

  it('formatMoney formats billions', () => {
    const vm = doMount().vm as any
    expect(vm.formatMoney(1.5e8)).toBe('1.50亿')
  })

  it('formatMoney formats ten-thousands', () => {
    const vm = doMount().vm as any
    expect(vm.formatMoney(15000)).toBe('1.50万')
  })

  it('formatMoney formats small values', () => {
    const vm = doMount().vm as any
    expect(vm.formatMoney(99.5)).toBe('99.50')
  })

  it('formatPositionSize preserves micro nonzero positions', () => {
    const vm = doMount().vm as any
    expect(vm.formatPositionSize(0.00004)).toBe('0.00004')
    expect(vm.formatPositionSize(-0.00004)).toBe('-0.00004')
    expect(vm.formatPositionSize(1.23456)).toBe('1.2346')
    expect(vm.formatPositionSize(0)).toBe('--')
  })

  it('hasOpenPosition ignores zero residuals but keeps hedged positions', () => {
    const vm = doMount().vm as any
    expect(vm.hasOpenPosition({ size: 1e-13, long_position: 0, short_position: 0 })).toBe(false)
    expect(vm.hasOpenPosition({ size: 0, long_position: 1, short_position: 1 })).toBe(true)
  })

  it('keeps stopped workspaces out of the live portfolio aggregation', async () => {
    const vm = doMount().vm as any
    await vm.loadData()
    expect(vm.overview.total_assets).toBe(100000)
    expect(vm.tradingWorkspaces).toHaveLength(2)
    expect(vm.runningWorkspaces).toHaveLength(1)
    expect(vm.runningWorkspaces.map((workspace: { id: string }) => workspace.id)).toEqual(['ws-running'])
    expect(vm.portfolioWorkspaceIds).toEqual(['ws-running'])
    expect(vm.loading).toBe(false)
    expect(portfolioApi.getOverview).toHaveBeenCalledWith(true)
    expect(workspaceApi.getTradingPositions).not.toHaveBeenCalled()
    expect(portfolioApi.getTrades).not.toHaveBeenCalled()
  })

  it('loadTabData only includes positions from active workspaces', async () => {
    const vm = doMount().vm as any
    await vm.loadData()
    await vm.loadTabData('positions')
    expect(vm.positions.length).toBe(1)
    expect(vm.positions[0].strategy_name).toContain('CTA 交易工作区')
    expect(vm.positions[0].data_name).toBe('RB2510')
    expect(vm.positions[0].long_position).toBe(2)
    expect(vm.positions[0].latest_price).toBe(3600)
    expect(vm.positions[0].margin_value).toBe(720)
    expect(vm.positions[0].leverage).toBe(10)
    expect(vm.positions[0].commission).toBe(3.5)
    expect(vm.positions[0].position_source).toBe('gateway')
    expect(vm.positions[0].asset_spec_source).toBe('ctp_gateway')
    expect(vm.valuationStatusLabel(vm.positions[0])).toBe('交易所确认')
    expect(vm.positionSummary.total_long_value).toBe(7200)
    expect(vm.positionSummary.gross_market_value).toBe(7200)
    expect(vm.positionSummary.net_market_value).toBe(7200)
    expect(vm.positionSummary.total_pnl).toBe(200)
    expect(workspaceApi.getTradingPositions).toHaveBeenCalledWith('ws-running')
    expect(workspaceApi.getTradingPositions).not.toHaveBeenCalledWith('ws-idle')
  })

  it('loadWorkspacePositions keeps hedged positions with zero net size', async () => {
    const vm = doMount().vm as any
    vm.runningWorkspaces = [
      {
        id: 'ws-running',
        user_id: 'u1',
        name: 'CTA 交易工作区',
        description: null,
        workspace_type: 'trading',
        settings: {},
        trading_config: {},
        unit_count: 1,
        completed_count: 0,
        status: 'running',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      },
    ]
    vi.mocked(workspaceApi.getTradingPositions).mockResolvedValueOnce({
      positions: [
        {
          unit_id: 'unit-hedged',
          unit_name: 'IF 双向',
          symbol: 'IF2609',
          symbol_name: null,
          trading_mode: 'live',
          long_position: 1,
          short_position: 1,
          avg_price: 5000,
          latest_price: 5010,
          position_pnl: 120,
          market_value: 1_002_600,
          long_market_value: 501_000,
          short_market_value: 501_600,
          margin_value: 120_240,
          multiplier: 300,
          margin_rate: 0.12,
          leverage: 8.33333333,
          commission: 10,
          gross_pnl: 130,
          position_source: 'gateway',
          asset_spec_source: 'ctp_gateway',
          valuation_status: 'confirmed',
          valuation_warnings: [],
        },
      ],
      total_long_value: 501_000,
      total_short_value: 501_600,
      total_pnl: 120,
    })
    await vm.loadWorkspacePositions()

    expect(vm.positions).toHaveLength(1)
    expect(vm.positions[0].direction).toBe('hedged')
    expect(vm.positions[0].size).toBe(0)
    expect(vm.positions[0].long_position).toBe(1)
    expect(vm.positions[0].short_position).toBe(1)
    expect(vm.directionLabel('hedged')).toBe('双向')
    expect(vm.positionSummary.long_count).toBe(1)
    expect(vm.positionSummary.short_count).toBe(1)
    expect(vm.positionSummary.gross_market_value).toBe(1_002_600)
    expect(vm.positionSummary.net_market_value).toBe(-600)
  })

  it('loadTabData loads current workspace trade records only', async () => {
    const vm = doMount().vm as any
    await vm.loadData()
    await vm.loadTabData('trades')
    expect(vm.trades.length).toBe(1)
    expect(vm.trades[0].strategy_name).toBe('CTA 交易工作区 / RB 趋势')
    expect(vm.trades[0].data_name).toBe('RB2510')
    expect(vm.trades[0].pnlcomm).toBe(197)
    expect(portfolioApi.getTrades).toHaveBeenCalledWith(1000, ['ws-running'], false)
  })

  it('loadWorkspaceTrades requests all running workspaces in one aggregate call', async () => {
    const vm = doMount().vm as any
    vm.runningWorkspaces = [
      {
        id: 'ws-running',
        user_id: 'u1',
        name: 'CTA 交易工作区',
        description: null,
        workspace_type: 'trading',
        settings: {},
        trading_config: {},
        unit_count: 2,
        completed_count: 0,
        status: 'running',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      },
      {
        id: 'ws-mt5',
        user_id: 'u1',
        name: 'MT5模拟工作区',
        description: null,
        workspace_type: 'trading',
        settings: {},
        trading_config: {},
        unit_count: 2,
        completed_count: 0,
        status: 'running',
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-02T00:00:00Z',
      },
    ]
    vi.mocked(portfolioApi.getTrades).mockClear()
    await vm.loadWorkspaceTrades()

    expect(portfolioApi.getTrades).toHaveBeenCalledWith(1000, ['ws-running', 'ws-mt5'], false)
  })

  it('loadTabData loads equity', async () => {
    const vm = doMount().vm as any
    await vm.loadData()
    await vm.loadTabData('equity')
    expect(vm.equityData).toBeTruthy()
    expect(vm.selectedEquitySeries).toBe('portfolio')
    expect(portfolioApi.getEquity).toHaveBeenCalledWith(['ws-running'], false)
  })

  it('uses the portfolio curve by default and trims leading empty points', () => {
    const vm = doMount().vm as any
    vm.equityData = {
      dates: ['2026-06-20', '2026-06-21', '2026-06-22', '2026-06-23'],
      total_equity: [0, 0, 100000, 101500],
      total_drawdown: [0, 0, 0, -0.01],
      strategies: [{
        strategy_id: 'unit-1',
        strategy_name: 'IB 美股趋势',
        instance_id: 'unit-1',
        values: [0, 25000, 25200, 25100],
      }],
    }

    expect(vm.selectedEquityCurve.name).toBe('组合总资产')
    expect(vm.selectedEquityCurve.dates).toEqual(['2026-06-22', '2026-06-23'])
    expect(vm.selectedEquityCurve.values).toEqual([100000, 101500])
    expect(vm.selectedEquityCurve.drawdown).toEqual([0, -0.01])
  })

  it('uses the API portfolio drawdown instead of recalculating from mixed equity history', () => {
    const vm = doMount().vm as any
    vm.equityData = {
      dates: ['2026-06-20', '2026-06-21', '2026-06-22'],
      total_equity: [100000, 500000, 120000],
      cumulative_pnl: [0, 0, 0],
      total_drawdown: [0, 0, -0.02],
      strategies: [],
    }

    expect(vm.selectedEquityCurve.drawdown).toEqual([0, 0, -0.02])
  })

  it('switches to and trims an individual strategy equity curve', () => {
    const vm = doMount().vm as any
    vm.equityData = {
      dates: ['2026-06-20', '2026-06-21', '2026-06-22'],
      total_equity: [100000, 101000, 102000],
      total_drawdown: [0, 0, 0],
      strategies: [{
        strategy_id: 'unit-1',
        strategy_name: 'IB 美股趋势',
        instance_id: 'unit-1',
        values: [0, 25000, 24900],
      }],
    }
    vm.selectedEquitySeries = 'unit-1'

    expect(vm.selectedEquityCurve.name).toBe('IB 美股趋势')
    expect(vm.selectedEquityCurve.dates).toEqual(['2026-06-21', '2026-06-22'])
    expect(vm.selectedEquityCurve.values).toEqual([25000, 24900])
    expect(vm.selectedEquityCurve.drawdown[0]).toBe(0)
    expect(vm.selectedEquityCurve.drawdown[1]).toBeCloseTo(-0.004, 6)
  })

  it('loadTabData loads allocation', async () => {
    const vm = doMount().vm as any
    await vm.loadData()
    await vm.loadTabData('allocation')
    expect(vm.allocationItems.length).toBe(1)
    expect(vm.allocationItems[0].asset).toBe('RB2510')
    expect(portfolioApi.getAllocation).toHaveBeenCalledWith(['ws-running'])
  })

  it('loadTabData skips already loaded tabs', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    const callsBefore = vi.mocked(workspaceApi.getTradingPositions).mock.calls.length
    await vm.loadTabData('positions')
    await vm.loadTabData('positions')

    expect(workspaceApi.getTradingPositions).toHaveBeenCalledTimes(callsBefore + 1)
    expect(vm.positions).toHaveLength(1)
  })

  it('activeTab defaults to workspaces', () => {
    const vm = doMount().vm as any
    expect(vm.activeTab).toBe('workspaces')
  })

  it('exposes an empty selected curve without equity data', () => {
    const vm = doMount().vm as any
    vm.equityData = null
    expect(vm.selectedEquityCurve).toEqual({
      name: '',
      dates: [],
      values: [],
      cumulativePnl: [],
      drawdown: [],
    })
  })

  it('renderDrawdownChart does nothing without equityData', () => {
    const vm = doMount().vm as any
    vm.equityData = null
    vm.renderDrawdownChart() // should not throw
  })

  it('renderAllocationChart does nothing without data', () => {
    const vm = doMount().vm as any
    vm.allocationItems = []
    vm.renderAllocationChart() // should not throw
  })

  it('tradeDirectionLabel supports backend buy/sell directions', () => {
    const vm = doMount().vm as any
    expect(vm.tradeDirectionLabel('buy')).toBe('多')
    expect(vm.tradeDirectionLabel('sell')).toBe('空')
    expect(vm.tradeDirectionClass('buy')).toBe('text-red-600')
    expect(vm.tradeDirectionClass('sell')).toBe('text-green-600')
  })

  it('handleResize is callable', () => {
    const vm = doMount().vm as any
    vm.handleResize() // should not throw
  })

  it('formatMoney handles negative values', () => {
    const vm = doMount().vm as any
    expect(vm.formatMoney(-2e8)).toBe('-2.00亿')
    expect(vm.formatMoney(-50000)).toBe('-5.00万')
    expect(vm.formatMoney(-50)).toBe('-50.00')
  })

  it('reports overview failures and clears the loading state', async () => {
    vi.mocked(portfolioApi.getOverview).mockRejectedValueOnce(new Error('overview unavailable'))

    const wrapper = doMount()
    await flushPromises()

    expect(portfolioApi.getOverview).toHaveBeenCalledWith(true)
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('overview unavailable'))
    expect(wrapper.find('.portfolio-loading').exists()).toBe(false)
    expect(wrapper.find('[data-test="portfolio-hero"]').exists()).toBe(true)
  })

  it('refreshes the visible portfolio and reloads the selected tab', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.activeTab = 'positions'
    await flushPromises()
    const callsBefore = vi.mocked(workspaceApi.getTradingPositions).mock.calls.length

    vi.mocked(portfolioApi.getOverview).mockResolvedValueOnce({
      total_assets: 123456,
      total_cash: 100000,
      total_position_value: 23456,
      net_position_value: 23456,
      total_initial_capital: 100000,
      total_pnl: 23456,
      total_pnl_pct: 23.456,
      strategy_count: 1,
      running_count: 1,
      strategies: [],
    })
    const refreshButton = wrapper.get('.portfolio-hero__status .el-button')
    expect(refreshButton.text()).toBe('刷新')
    await refreshButton.trigger('click')
    await flushPromises()

    expect(portfolioApi.getOverview).toHaveBeenCalledTimes(2)
    expect(workspaceApi.getTradingPositions).toHaveBeenCalledTimes(callsBefore + 1)
    expect(wrapper.get('.portfolio-hero__asset').text()).toContain('12.35万')
  })

  it('shows empty position and trade states when there are no running workspaces', async () => {
    vi.mocked(workspaceApi.list).mockResolvedValueOnce({ total: 0, items: [] })
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any

    vm.activeTab = 'positions'
    await flushPromises()
    expect(vm.positions).toEqual([])
    expect(vm.positionSummary).toMatchObject({
      total_long_value: 0,
      total_short_value: 0,
      gross_market_value: 0,
      net_market_value: 0,
      total_pnl: 0,
    })
    expect(wrapper.find('.portfolio-empty').text()).toContain('暂无持仓数据')
    expect(workspaceApi.getTradingPositions).not.toHaveBeenCalled()

    vm.activeTab = 'trades'
    await flushPromises()
    expect(vm.trades).toEqual([])
    expect(wrapper.get('.el-tab-pane[name="trades"] .portfolio-empty').text()).toContain('暂无交易记录')
    expect(portfolioApi.getTrades).not.toHaveBeenCalled()
  })

  it('reports a positions request failure and retries the tab on the next request', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vi.mocked(workspaceApi.getTradingPositions).mockRejectedValueOnce(new Error('positions unavailable'))

    vm.activeTab = 'positions'
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('positions unavailable'))
    expect(vm.isTabLoading('positions')).toBe(false)
    expect(wrapper.find('.portfolio-empty').text()).toContain('暂无持仓数据')

    await vm.loadTabData('positions')

    expect(workspaceApi.getTradingPositions).toHaveBeenCalledTimes(2)
    expect(vm.positions).toHaveLength(1)
    expect(vm.positions[0].data_name).toBe('RB2510')
  })

  it('renders long and short position rows including zero and unavailable valuation fields', async () => {
    const wrapper = doMount(true)
    await flushPromises()
    const vm = wrapper.vm as any

    vi.mocked(workspaceApi.getTradingPositions).mockResolvedValueOnce({
      positions: [
        {
          unit_id: 'unit-long',
          unit_name: '多头趋势',
          symbol: 'LONG',
          symbol_name: '多头标的',
          trading_mode: 'live',
          long_position: 2,
          short_position: 0,
          avg_price: 10.5,
          latest_price: 12,
          position_pnl: 3,
          market_value: 24,
          margin_value: 2.4,
          leverage: 10,
          commission: 0.5,
          position_source: 'gateway',
          asset_spec_source: 'exchange',
          valuation_status: 'confirmed',
          valuation_warnings: [],
        },
        {
          unit_id: 'unit-short',
          unit_name: '空头对冲',
          symbol: 'SHORT',
          symbol_name: '空头标的',
          trading_mode: 'live',
          long_position: 0,
          short_position: 1,
          avg_price: null,
          latest_price: null,
          position_pnl: -2,
          market_value: 0,
          margin_value: null,
          leverage: null,
          commission: null,
          position_source: 'snapshot',
          asset_spec_source: null,
          valuation_status: 'estimated',
          valuation_warnings: ['价格为估算值'],
        },
      ],
    } as any)

    vm.activeTab = 'positions'
    await flushPromises()

    const rows = wrapper.findAll('.el-tab-pane[name="positions"] .el-table-row')
    expect(workspaceApi.getTradingPositions).toHaveBeenCalledWith('ws-running')
    expect(rows).toHaveLength(2)
    const cellText = (row: typeof rows[number], label: string) => (
      row.get(`[data-column="${label}"] .el-table-cell__value`).text()
    )

    const longRow = rows.find(row => cellText(row, '标的代码') === 'LONG')
    expect(longRow).toBeDefined()
    expect(cellText(longRow!, '方向')).toBe('多')
    expect(cellText(longRow!, '多头')).toBe('2.0000')
    expect(cellText(longRow!, '空头')).toBe('--')
    expect(cellText(longRow!, '成本价')).toBe('10.5000')
    expect(cellText(longRow!, '最新价')).toBe('12.0000')
    expect(cellText(longRow!, '市值')).toBe('24.00')
    expect(cellText(longRow!, '持仓盈亏')).toBe('+3.00')
    expect(cellText(longRow!, '保证金')).toBe('2.40')
    expect(cellText(longRow!, '手续费')).toBe('0.50')
    expect(cellText(longRow!, '估值状态')).toBe('交易所确认')

    const shortRow = rows.find(row => cellText(row, '标的代码') === 'SHORT')
    expect(shortRow).toBeDefined()
    expect(cellText(shortRow!, '方向')).toBe('空')
    expect(cellText(shortRow!, '持仓量')).toBe('-1.0000')
    expect(cellText(shortRow!, '成本价')).toBe('0.0000')
    expect(cellText(shortRow!, '最新价')).toBe('0.0000')
    expect(cellText(shortRow!, '市值')).toBe('0.00')
    expect(cellText(shortRow!, '持仓盈亏')).toBe('-2.00')
    expect(cellText(shortRow!, '保证金')).toBe('--')
    expect(cellText(shortRow!, '杠杆')).toBe('--')
    expect(cellText(shortRow!, '手续费')).toBe('--')
    expect(cellText(shortRow!, '估值状态')).toBe('估算')
  })

  it('renders buy and sell trade rows with signed net profit and loss', async () => {
    const wrapper = doMount(true)
    await flushPromises()
    const vm = wrapper.vm as any
    vi.mocked(portfolioApi.getTrades).mockResolvedValueOnce({
      total: 2,
      trades: [
        {
          workspace_id: 'ws-running',
          strategy_name: 'CTA 交易工作区 / 多头策略',
          data_name: 'LONG',
          direction: 'buy',
          dtopen: '2026-06-19 09:30:00',
          dtclose: '2026-06-19 10:00:00',
          price: 10.5,
          size: 2,
          commission: 1.25,
          pnlcomm: 20,
          barlen: 7,
        },
        {
          workspace_id: 'ws-running',
          strategy_name: 'CTA 交易工作区 / 空头策略',
          data_name: 'SHORT',
          direction: 'sell',
          dtopen: '2026-06-19 10:30:00',
          dtclose: '2026-06-19 11:00:00',
          price: 8,
          size: 1,
          commission: 0.75,
          pnlcomm: -5,
          barlen: 3,
        },
      ],
    } as any)

    vm.activeTab = 'trades'
    await flushPromises()

    const rows = wrapper.findAll('.el-tab-pane[name="trades"] .el-table-row')
    expect(portfolioApi.getTrades).toHaveBeenCalledWith(1000, ['ws-running'], false)
    expect(rows).toHaveLength(2)
    const cellText = (row: typeof rows[number], label: string) => (
      row.get(`[data-column="${label}"] .el-table-cell__value`).text()
    )
    const longRow = rows.find(row => cellText(row, '标的') === 'LONG')
    const shortRow = rows.find(row => cellText(row, '标的') === 'SHORT')

    expect(longRow).toBeDefined()
    expect(cellText(longRow!, '方向')).toBe('多')
    expect(cellText(longRow!, '价格')).toBe('10.50')
    expect(cellText(longRow!, '手续费')).toBe('1.25')
    expect(cellText(longRow!, '净盈亏')).toBe('+20.00')
    expect(shortRow).toBeDefined()
    expect(cellText(shortRow!, '方向')).toBe('空')
    expect(cellText(shortRow!, '价格')).toBe('8.00')
    expect(cellText(shortRow!, '净盈亏')).toBe('-5.00')
  })

  it('renders both equity charts and updates the selected strategy series', async () => {
    vi.mocked(portfolioApi.getEquity).mockResolvedValueOnce({
      dates: ['2026-06-20', '2026-06-21'],
      total_equity: [100000, 101000],
      cumulative_pnl: [0, 1000],
      total_drawdown: [0, -0.01],
      strategies: [{
        strategy_id: 's1',
        strategy_name: 'SMA 单元',
        instance_id: 'unit-1',
        values: [50000, 51000],
        pnl_values: [-100, 200],
      }],
    } as any)
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.activeTab = 'equity'
    await flushPromises()

    expect(portfolioApi.getEquity).toHaveBeenCalledWith(['ws-running'], false)
    expect(wrapper.find('.portfolio-chart--pnl').exists()).toBe(true)
    expect(wrapper.find('.portfolio-chart--drawdown').exists()).toBe(true)
    expect(chartMock.init).toHaveBeenCalledTimes(2)
    expect(chartMock.charts[0].setOption).toHaveBeenCalledWith(
      expect.objectContaining({ series: [expect.objectContaining({ data: [0, 1000] })] }),
      true,
    )

    vm.selectedEquitySeries = 'unit-1'
    await flushPromises()

    expect(vm.selectedEquityCurve.name).toBe('SMA 单元')
    expect(vm.selectedEquityCurve.values).toEqual([50000, 51000])
    expect(vm.selectedEquityCurve.cumulativePnl).toEqual([-100, 200])
    expect(chartMock.charts[0].setOption).toHaveBeenLastCalledWith(
      expect.objectContaining({ series: [expect.objectContaining({ data: [-100, 200] })] }),
      true,
    )
    expect(chartMock.charts[0].resize).toHaveBeenCalled()

    vm.activeTab = 'workspaces'
    await flushPromises()
    vm.activeTab = 'equity'
    await flushPromises()

    expect(chartMock.charts[0].dispose).toHaveBeenCalledOnce()
    expect(chartMock.charts[1].dispose).toHaveBeenCalledOnce()
    expect(chartMock.init).toHaveBeenCalledTimes(4)
  })

  it('renders the allocation chart from the selected workspace data', async () => {
    vi.mocked(portfolioApi.getAllocation).mockResolvedValueOnce({
      total: 100,
      items: [
        { asset: 'RB2510', value: 70, weight: 70, long_value: 70, short_value: 0, net_value: 70, position_count: 1 },
        { asset: 'AG2512', value: 30, weight: 30, long_value: 0, short_value: 30, net_value: -30, position_count: 1 },
      ],
    })
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.activeTab = 'allocation'
    await flushPromises()

    expect(portfolioApi.getAllocation).toHaveBeenCalledWith(['ws-running'])
    expect(wrapper.find('.portfolio-chart--allocation').exists()).toBe(true)
    expect(chartMock.init).toHaveBeenCalledTimes(1)
    expect(chartMock.charts[0].setOption).toHaveBeenCalledWith(
      expect.objectContaining({
        series: [expect.objectContaining({
          type: 'pie',
          data: [{ name: 'RB2510', value: 70 }, { name: 'AG2512', value: 30 }],
        })],
      }),
      true,
    )
  })

  it('reports allocation request errors and allows the tab to be retried', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vi.mocked(portfolioApi.getAllocation).mockRejectedValueOnce(new Error('allocation unavailable'))

    vm.activeTab = 'allocation'
    await flushPromises()

    expect(portfolioApi.getAllocation).toHaveBeenCalledWith(['ws-running'])
    expect(ElMessage.error).toHaveBeenCalledWith(expect.stringContaining('allocation unavailable'))
    expect(vm.isTabLoading('allocation')).toBe(false)
    expect(wrapper.get('.el-tab-pane[name="allocation"] .portfolio-empty').text()).toContain('暂无持仓资产')

    await vm.loadTabData('allocation')

    expect(portfolioApi.getAllocation).toHaveBeenCalledTimes(2)
    expect(vm.allocationItems).toHaveLength(1)
  })
})
