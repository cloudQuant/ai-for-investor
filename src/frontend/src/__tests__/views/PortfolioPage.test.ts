import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { ElMessage } from 'element-plus'
import PortfolioPage from '@/views/PortfolioPage.vue'
import { portfolioApi, type PortfolioProviderAccountObservation } from '@/api/portfolio'
import { portfolioLedgerApi } from '@/api/portfolioLedger'
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
    createCompositionVersion: vi.fn().mockResolvedValue({
      portfolio_ref: 'imported-display', membership_version: 1,
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

vi.mock('@/api/portfolioLedger', () => ({
  portfolioLedgerApi: {
    listImportSources: vi.fn().mockResolvedValue({
      items: [], total: 0, page: 1, page_size: 100, has_more: false,
    }),
    create: vi.fn().mockResolvedValue({ id: 'ledger-import-1' }),
    importTransactions: vi.fn().mockResolvedValue({
      duplicate: false,
      imported_count: 2,
      import_version_id: 'import-version-1',
      source_sha256: 'a'.repeat(64),
      source_material_status: 'verified',
    }),
    getImportSource: vi.fn().mockResolvedValue({
      import_version_id: 'import-version-1',
      portfolio_id: 'ledger-import-1',
      portfolio_name: 'Imported transactions',
      base_currency: 'USD',
      import_format: 'json',
      imported_count: 2,
      source_material_status: 'verified',
      source_schema_version: 1,
      source_as_of: '2026-10-13',
      source_currency: 'USD',
      source_sha256: 'a'.repeat(64),
      source_document: {
        schema_version: 1,
        format: 'json',
        source_as_of: '2026-10-13',
        source_currency: 'USD',
        transactions: [{ symbol: 'SYNTH-A' }, { symbol: 'SYNTH-B', trade_date: '2026-10-12' }],
      },
      created_at: '2026-10-15T00:00:00Z',
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
      source_status: 'research_reports_projected',
      source_facts: {
        kind: 'asset_research_reports' as const,
        research_facts_available: true,
        freshness_status: 'not_defined',
        currency_status: 'not_declared',
        artifacts: [{
          status: 'available',
          report_integrity_status: 'verified',
          task_status: 'SUCCEEDED',
          asset_type: 'stock',
          canonical_id: 'SYNTH:AAA',
          report_version: 'v1',
          report_content_hash: 'a'.repeat(64),
          report_created_at: '2026-10-14T12:00:00+00:00',
          decision_status: 'available',
          published_decision: {
            asset_type: 'stock',
            market_view: 'BULLISH',
            normalized_direction: 'LONG',
            recommendation: 'BUY',
            actionability: 'RESEARCH_ONLY',
            quality_status: 'ELIGIBLE',
            horizon_code: '1d',
            execution_disabled: true as const,
          },
          freshness_status: 'not_defined',
          currency: null,
          currency_status: 'not_declared',
          account_value_status: 'not_applicable_research',
        }],
      },
      account_total: { status: 'not_applicable_research', currency: null, value: null },
      strategies: [],
      strategy_attribution: {
        ...liveProjection.strategy_attribution,
        status: 'not_applicable_research',
        strategy_count: 0,
        unattributed_account_value: null,
        residual_basis: 'research reports do not establish account or strategy holdings',
      },
      coverage: {
        complete: false,
        research_facts_available: true,
        account_facts_complete: false,
        strategy_attribution_complete: false,
        code: 'RESEARCH_REPORTS_NOT_FINANCIAL_ACCOUNTS',
      },
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
    expect(wrapper.get('[data-test="portfolio-composition-source-status"]').text())
      .toContain('已读取公开研究报告')
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('不可用')
    expect(wrapper.get('[data-test="portfolio-research-disclaimer"]')
      .text()).toContain('不代表持仓、账户余额或执行归属')
    expect(wrapper.get('[data-test="portfolio-research-artifact"]').text()).toContain('SYNTH:AAA')
    expect(wrapper.get('[data-test="portfolio-research-artifact"]').text()).toContain('BUY')
    expect(wrapper.get('[data-test="portfolio-research-artifact"]').text()).toContain('未声明')
    expect(wrapper.get('[data-test="portfolio-composition-attribution-status"]')
      .text()).toContain('不适用持仓归属')
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

  it('shows live unallocated books separately from provider changes and incremental residuals', async () => {
    const makeCoverage = (complete: boolean, reasons: string[] = []) => ({
      scope_directory_revision: 'directory-r1',
      journal_generation: complete ? 'a'.repeat(32) : 'b'.repeat(32),
      baseline_execution_cursor: 10,
      current_execution_cursor: 12,
      complete,
      reasons,
      scanned_outbox_events: 2,
      outbox_history_contiguous: complete,
      outbox_scan_complete: true,
      continuations: [],
      input_continuations: [],
      quarantined_intents: [],
    })
    const liveProjection = {
      portfolio_ref: 'dual-live',
      membership_version: 4,
      source_type: 'live' as const,
      source_status: 'projected',
      base_currency: 'USDT',
      projection_kind: 'display_only' as const,
      creditable: false as const,
      overlap_policy: 'non_additive_display_only' as const,
      account_total: { status: 'current', currency: 'USDT', value: '950' },
      accounts: [
        {
          member_ref: 'account-a', currency: 'USDT', quality: 'fresh', cash: null, value: '160',
          included_in_total: true, duplicate_of_ref: null, detail_code: null,
        },
        {
          member_ref: 'account-b', currency: 'USDT', quality: 'fresh', cash: null, value: '790',
          included_in_total: true, duplicate_of_ref: null, detail_code: null,
        },
      ],
      account_book_sources: [
        {
          account_ref: 'account-a',
          state: 'RESIDUAL',
          coverage: makeCoverage(true),
          provider_position_change: [{ instrument: 'SYNTH-A', net_quantity: '1' }],
          unallocated_book: {
            owner_kind: 'UNALLOCATED' as const,
            owner_ref: 'UNALLOCATED',
            current_positions: [{ instrument: 'SYNTH-A', net_quantity: '3.5' }],
            fees_since_baseline: [{ currency: 'USDT', amount: '0.04' }],
          },
          position_residual: [{ instrument: 'SYNTH-A', net_quantity: '0.5' }],
          fee_residual: [{ currency: 'USDT', amount: '0.04' }],
          financial: {
            status: 'available' as const,
            source: 'PERSISTED_EXECUTION_FINANCIAL_PROJECTION' as const,
            freshness: 'PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED' as const,
            cut_relationship: 'INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT' as const,
            complete: true,
            state: 'RESIDUAL' as const,
            ledger_cut: {
              owner_directory_revision: 'financial-directory-a-r1',
              captured_at_ns: '1797000000123456789',
              watermarks: [
                {
                  source_kind: 'execution_outbox' as const,
                  source_ref: 'synthetic-outbox-a',
                  generation: 'synthetic-generation-a',
                  cursor: 0,
                  as_of_ns: '1797000000123456789',
                },
                {
                  source_kind: 'account_facts' as const,
                  source_ref: 'synthetic-facts-a',
                  generation: 'synthetic-facts-generation-a',
                  cursor: 3,
                  as_of_ns: '1797000000123456788',
                },
                {
                  source_kind: 'account_activity' as const,
                  source_ref: 'synthetic-activity-a',
                  generation: 'synthetic-activity-generation-a',
                  cursor: 4,
                  as_of_ns: '1797000000123456787',
                },
              ],
            },
            books: [
              {
                owner: { kind: 'STRATEGY' as const, owner_ref: 'strategy-a' },
                cash: [{ currency: 'USDT', amount: '123.45' }],
                positions: [{
                  instrument: 'SYNTH-A',
                  quantity: '2.5',
                  cost_basis: null,
                  cost_currency: null,
                  cost_method: 'AVERAGE_COST' as const,
                  product_model: 'SPOT' as const,
                  metadata_version: 'synthetic-spot-v1',
                }],
                cumulative_fees: [{ currency: 'USDT', amount: '0' }],
                realized_pnl: [],
                cost_basis_complete: false,
              },
            ],
            unallocated: {
              cash: [],
              positions: [{ instrument: 'SYNTH-A', quantity: '0.5' }],
              fees: [],
            },
          },
        },
        {
          account_ref: 'account-b',
          state: 'PARTIAL',
          coverage: makeCoverage(false, ['OUTBOX_HISTORY_GAP']),
          provider_position_change: [{ instrument: 'SYNTH-B', net_quantity: '2' }],
          unallocated_book: {
            owner_kind: 'UNALLOCATED' as const,
            owner_ref: 'UNALLOCATED',
            current_positions: [{ instrument: 'SYNTH-B', net_quantity: '5' }],
            fees_since_baseline: [{ currency: 'USDT', amount: '0.07' }],
          },
          position_residual: [{ instrument: 'SYNTH-B', net_quantity: '1' }],
          fee_residual: [{ currency: 'USDT', amount: '0.07' }],
          financial: {
            status: 'unavailable' as const,
            code: 'PERSISTED_PROJECTION_UNAVAILABLE' as const,
            freshness: 'NOT_ESTABLISHED' as const,
            cut_relationship: 'INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT' as const,
          },
        },
      ],
      strategies: [
        { strategy_ref: 'strategy-a', attribution_status: 'available', attributed_value: null },
        { strategy_ref: 'strategy-b', attribution_status: 'available', attributed_value: null },
      ],
      strategy_attribution: {
        status: 'execution_attribution_incomplete',
        strategy_count: 2,
        attributed_value: null,
        unattributed_account_value: null,
        residual_basis: 'account total only; no strategy shares inferred',
      },
      coverage: {
        complete: false,
        account_facts_complete: true,
        strategy_attribution_complete: false,
        code: 'EXECUTION_ATTRIBUTION_INCOMPLETE',
      },
    }
    vi.mocked(portfolioApi.listCompositionVersions).mockResolvedValueOnce({
      items: [{
        portfolio_ref: 'dual-live', membership_version: 4, source_type: 'live',
        base_currency: 'USDT', created_at: '2026-10-16T00:00:00Z',
      }],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    })
    vi.mocked(portfolioApi.getCompositionProjection).mockResolvedValueOnce(liveProjection)

    const wrapper = doMount()
    await flushPromises()
    await wrapper.get('[data-test="portfolio-mode-composition"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('950 USDT')
    expect(wrapper.get('[data-test="portfolio-composition-coverage"]').text()).toContain('不完整')
    expect(wrapper.get('[data-test="portfolio-composition-creditability"]').text()).toContain('仅供展示，不可计入')
    expect(wrapper.get('[data-test="portfolio-composition-overlap"]').text()).toContain('不可相加')
    expect(wrapper.get('[data-test="portfolio-composition-attributed-value"]').text()).toBe('不可用')

    const accountSources = wrapper.findAll('[data-test="portfolio-account-book-source"]')
    expect(accountSources).toHaveLength(2)
    expect(accountSources[0].get('[data-test="portfolio-account-book-coverage"]').text()).toContain('完整')
    expect(accountSources[1].get('[data-test="portfolio-account-book-coverage"]').text()).toContain('不完整')
    expect(accountSources[1].text()).toContain('OUTBOX_HISTORY_GAP')

    expect(accountSources[0].get('[data-test="portfolio-account-book-unallocated"]')
      .get('[data-test="portfolio-account-book-unallocated-position"]').text()).toBe('SYNTH-A · 3.5')
    expect(accountSources[0].get('[data-test="portfolio-account-book-provider-change"]')
      .text()).toContain('SYNTH-A · 1')
    expect(accountSources[0].get('[data-test="portfolio-account-book-position-residual"]')
      .text()).toContain('SYNTH-A · 0.5')
    expect(accountSources[0].get('[data-test="portfolio-account-book-fee-residual"]')
      .text()).toContain('0.04 USDT')
    expect(accountSources[1].get('[data-test="portfolio-account-book-unallocated"]')
      .get('[data-test="portfolio-account-book-unallocated-position"]').text()).toBe('SYNTH-B · 5')
    expect(accountSources[1].get('[data-test="portfolio-account-book-provider-change"]')
      .text()).toContain('SYNTH-B · 2')
    expect(accountSources[1].get('[data-test="portfolio-account-book-position-residual"]')
      .text()).toContain('SYNTH-B · 1')
    const availableFinancial = accountSources[0].get('[data-test="portfolio-account-book-financial"]')
    expect(availableFinancial.get('[data-test="portfolio-account-book-financial-cut"]')
      .text()).toContain('1797000000123456789')
    expect(availableFinancial.get('[data-test="portfolio-account-book-financial-cut"]')
      .text()).toContain('PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED')
    expect(availableFinancial.get('[data-test="portfolio-account-book-financial-watermarks"]')
      .text()).toContain('cursor 3')
    const availableOwner = availableFinancial.get('[data-test="portfolio-account-book-financial-owner"]')
    expect(availableOwner.get('[data-test="portfolio-account-book-financial-cash"]').text())
      .toBe('123.45 USDT')
    expect(availableOwner.get('[data-test="portfolio-account-book-financial-fees"]').text())
      .toBe('0 USDT')
    expect(availableOwner
      .get('[data-test="portfolio-account-book-financial-position"]').text())
      .toContain('cost basis 缺失 / Missing')
    expect(availableFinancial.text()).toContain('不会加入账户总额')
    expect(accountSources[1].get('[data-test="portfolio-account-book-financial-unavailable"]')
      .text()).toContain('PERSISTED_PROJECTION_UNAVAILABLE')

    // These execution quantities remain separate source facts; none are folded into account equity.
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('950 USDT')
    expect(wrapper.text()).toContain('不会加到账户总额')
    expect(wrapper.text()).not.toContain('strategy-a · 3.5')
    expect(wrapper.text()).not.toContain('strategy-b · 5')
  })

  it('shows provider observations, missing inputs, stale cuts, and currencies without revaluing totals', async () => {
    const availableObservation: Extract<
      PortfolioProviderAccountObservation,
      { status: 'available' }
    > = {
      status: 'available',
      quality: 'fresh',
      source: 'AUTHORIZED_PROVIDER_ACCOUNT_OBSERVATION',
      observation_id: 'observation-ui-a',
      session_generation: 'session-ui-a',
      cursor: 9,
      consistency: 'multi_query',
      cut: {
        started_at_utc: '2026-10-15T00:00:00Z',
        completed_at_utc: '2026-10-15T00:00:01Z',
        earliest_row_observed_at_utc: '2026-10-15T00:00:00Z',
        latest_row_observed_at_utc: '2026-10-15T00:00:00.5Z',
        row_skew_ns: '1000000000',
        row_observed_at_count: 5,
        row_count: 5,
      },
      coverage: {
        resources: [
          { product_type: 'SPOT', margin_pool: 'cash' },
          { product_type: 'SPOT', margin_pool: 'funding' },
        ],
        balances_complete: false,
        positions_complete: true,
        state: 'incomplete',
      },
      valuation: null,
      balances: [
        {
          resource: { product_type: 'SPOT', margin_pool: 'cash' },
          currency: 'USD',
          total: '100',
          available: '20',
          locked: '80',
          observed_at_utc: '2026-10-15T00:00:00Z',
        },
        {
          resource: { product_type: 'SPOT', margin_pool: 'cash' },
          currency: 'EUR',
          total: '12.5',
          available: null,
          locked: '0',
          observed_at_utc: '2026-10-15T00:00:00.5Z',
        },
        {
          resource: { product_type: 'SPOT', margin_pool: 'funding' },
          currency: 'USDT',
          total: '0',
          available: '0',
          locked: '0',
          observed_at_utc: '2026-10-15T00:00:00Z',
        },
      ],
      positions: [
        {
          resource: { product_type: 'SPOT', margin_pool: 'cash' },
          instrument: {
            provider: 'synthetic-provider',
            venue: 'synthetic-venue',
            environment: 'live',
            product_type: 'SPOT',
            instrument_id: 'instrument-zero',
            native_symbol: 'ZERO/EUR',
          },
          side: 'net',
          quantity: '0',
          qty_unit: 'base_asset',
          average_price: '0',
          price_currency: 'EUR',
          observed_at_utc: '2026-10-15T00:00:01Z',
          valuation_inputs: {
            mark_price: { status: 'missing', value: null },
            contract_multiplier: { status: 'unsupported', value: null },
            fx_rate: { status: 'unsupported', value: null },
            market_value: { status: 'not_calculated', value: null },
          },
        },
        {
          resource: { product_type: 'SPOT', margin_pool: 'cash' },
          instrument: {
            provider: 'synthetic-provider',
            venue: 'synthetic-venue',
            environment: 'live',
            product_type: 'SPOT',
            instrument_id: 'instrument-missing-price',
            native_symbol: 'NO-MARK/EUR',
          },
          side: 'long',
          quantity: '2',
          qty_unit: 'contracts',
          average_price: null,
          price_currency: null,
          observed_at_utc: '2026-10-15T00:00:01Z',
          valuation_inputs: {
            mark_price: { status: 'missing', value: null },
            contract_multiplier: { status: 'unsupported', value: null },
            fx_rate: { status: 'unsupported', value: null },
            market_value: { status: 'not_calculated', value: null },
          },
        },
      ],
    }
    const staleObservation: Extract<
      PortfolioProviderAccountObservation,
      { status: 'stale' }
    > = {
      ...availableObservation,
      status: 'stale',
      quality: 'stale',
      observation_id: 'observation-ui-stale',
      cut: {
        ...availableObservation.cut,
        completed_at_utc: '2026-10-15T00:00:03Z',
      },
    }
    const liveProjection = {
      portfolio_ref: 'provider-facts-ui',
      membership_version: 1,
      source_type: 'live' as const,
      source_status: 'projected',
      base_currency: 'USD',
      projection_kind: 'display_only' as const,
      creditable: false as const,
      overlap_policy: 'non_additive_display_only' as const,
      account_total: { status: 'current', currency: 'USD', value: '100' },
      accounts: [
        {
          member_ref: 'account-a', currency: 'USD', quality: 'fresh', cash: '0', value: '100',
          included_in_total: true, duplicate_of_ref: null, detail_code: null,
          provider_observation: availableObservation,
        },
        {
          member_ref: 'account-stale', currency: 'USD', quality: 'stale', cash: null, value: null,
          included_in_total: false, duplicate_of_ref: null, detail_code: 'ACCOUNT_FACTS_STALE',
          provider_observation: staleObservation,
        },
        {
          member_ref: 'account-error', currency: 'USD', quality: 'unavailable', cash: null, value: null,
          included_in_total: false, duplicate_of_ref: null, detail_code: 'SYNTHETIC_READ_FAILED',
          provider_observation: { status: 'unavailable' as const, code: 'SYNTHETIC_READ_FAILED' },
        },
        {
          member_ref: 'account-legacy', currency: 'USD', quality: 'fresh', cash: null, value: null,
          included_in_total: false, duplicate_of_ref: null, detail_code: null,
          provider_observation: {
            status: 'absent' as const,
            code: 'PROVIDER_OBSERVATION_NOT_PROJECTED',
          },
        },
      ],
      provider_snapshot_consistency: {
        cut_model: 'independent_provider_observation_per_account' as const,
        atomic: false as const,
        member_read_count: 4,
        observation_count: 2,
        consistency_modes: ['multi_query'],
        coverage_status: 'not_established',
        coverage_complete: null,
        earliest_completed_at_utc: '2026-10-15T00:00:01Z',
        latest_completed_at_utc: '2026-10-15T00:00:03Z',
        skew_ns: null,
        skew_policy: 'reported_without_threshold' as const,
        status: 'observation_absent_or_unavailable',
      },
      strategies: [],
      strategy_attribution: {
        status: 'execution_attribution_not_collected',
        strategy_count: 0,
        attributed_value: null,
        unattributed_account_value: null,
        residual_basis: 'account total only; no strategy shares inferred',
      },
      coverage: { complete: false, account_facts_complete: true, code: null },
    }
    vi.mocked(portfolioApi.listCompositionVersions).mockResolvedValueOnce({
      items: [{
        portfolio_ref: 'provider-facts-ui', membership_version: 1, source_type: 'live',
        base_currency: 'USD', created_at: '2026-10-16T00:00:00Z',
      }],
      total: 1,
      page: 1,
      page_size: 50,
      has_more: false,
    })
    vi.mocked(portfolioApi.getCompositionProjection).mockResolvedValueOnce(liveProjection)

    const wrapper = doMount()
    await flushPromises()
    await wrapper.get('[data-test="portfolio-mode-composition"]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text())
      .toBe('100 USD')
    expect(wrapper.get('[data-test="portfolio-provider-snapshot-consistency"]')
      .text()).toContain('observation_absent_or_unavailable')
    const observations = wrapper.findAll('[data-test="portfolio-provider-account-observation"]')
    expect(observations).toHaveLength(4)
    const available = observations[0].text()
    expect(available).toContain('100 USD')
    expect(available).toContain('12.5 EUR')
    expect(available).toContain('0 USDT')
    expect(available).toContain('不可用')
    expect(available).toContain('ZERO/EUR')
    expect(available).toContain('NO-MARK/EUR')
    expect(available).toContain('2 contracts')
    expect(available).toContain('average 0 EUR')
    expect(available).toContain('atomicity not established')
    expect(available).toContain('reconciliation is not established')
    expect(available).toContain('mark missing')
    expect(available).toContain('multiplier unsupported')
    expect(available).toContain('FX unsupported')
    expect(available).toContain('覆盖完整性 / Coverage')
    expect(available).toContain('balances 不完整 / incomplete')
    expect(available).toContain('不计算市值')
    expect(observations[1].text()).toContain('observation-ui-stale')
    expect(observations[1].text()).toContain('stale')
    expect(observations[2].text()).toContain('SYNTHETIC_READ_FAILED')
    expect(observations[3].text()).toContain('PROVIDER_OBSERVATION_NOT_PROJECTED')
    const accountQualities = wrapper.findAll('[data-test="portfolio-composition-account-quality"]')
    expect(accountQualities.map(node => node.text())).toEqual([
      '(fresh)',
      '(stale)',
      '(unavailable)',
      '(fresh)',
    ])
    expect(wrapper.text()).not.toContain('private-synthetic-account')
  })

  it('keeps older live projections usable when the unallocated-book field is absent', async () => {
    const legacyProjection = {
      portfolio_ref: 'legacy-live',
      membership_version: 1,
      source_type: 'live' as const,
      source_status: 'projected',
      base_currency: 'USD',
      projection_kind: 'display_only' as const,
      creditable: false as const,
      overlap_policy: 'non_additive_display_only' as const,
      account_total: { status: 'current', currency: 'USD', value: '42' },
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
    }
    const partialProjection = {
      ...legacyProjection,
      portfolio_ref: 'partial-live',
      account_book_sources: [{
        account_ref: 'account-old',
        state: 'PARTIAL',
        coverage: {
          scope_directory_revision: 'directory-r0',
          journal_generation: 'c'.repeat(32),
          baseline_execution_cursor: 0,
          current_execution_cursor: 0,
          complete: false,
          reasons: ['ACCOUNT_BOOK_NOT_CONFIGURED'],
          scanned_outbox_events: 0,
          outbox_history_contiguous: false,
          outbox_scan_complete: false,
          continuations: [],
          input_continuations: [],
          quarantined_intents: [],
        },
        provider_position_change: [],
        position_residual: [],
        fee_residual: [],
        // Older backend response has no unallocated_book field.
      }],
    }
    vi.mocked(portfolioApi.listCompositionVersions).mockResolvedValueOnce({
      items: [
        {
          portfolio_ref: 'legacy-live', membership_version: 1, source_type: 'live',
          base_currency: 'USD', created_at: '2026-10-16T00:00:00Z',
        },
        {
          portfolio_ref: 'partial-live', membership_version: 1, source_type: 'live',
          base_currency: 'USD', created_at: '2026-10-15T00:00:00Z',
        },
      ],
      total: 2,
      page: 1,
      page_size: 50,
      has_more: false,
    })
    vi.mocked(portfolioApi.getCompositionProjection)
      .mockResolvedValueOnce(legacyProjection)
      .mockResolvedValueOnce(partialProjection)

    const wrapper = doMount()
    await flushPromises()
    await wrapper.get('[data-test="portfolio-mode-composition"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('42 USD')
    expect(wrapper.find('[data-test="portfolio-account-book-sources"]').exists()).toBe(false)

    await wrapper.get('[data-test="portfolio-composition-version-select"]')
      .setValue(JSON.stringify(['partial-live', 1]))
    await flushPromises()
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('42 USD')
    expect(wrapper.get('[data-test="portfolio-account-book-unallocated-unavailable"]')
      .text()).toContain('未提供未分配账簿详情')
    expect(wrapper.get('[data-test="portfolio-account-book-financial-absent"]')
      .text()).toContain('Financial projection not provided')
    expect(wrapper.findAll('[data-test="portfolio-account-book-unallocated-position"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-test="portfolio-account-book-position-residual"] li')).toHaveLength(0)
  })

  it('imports versioned raw transactions and selects the imported display projection', async () => {
    const importedProjection = {
      portfolio_ref: 'imported-portfolio',
      membership_version: 1,
      source_type: 'imported' as const,
      source_status: 'imported_materials_projected',
      base_currency: 'USD',
      projection_kind: 'display_only' as const,
      creditable: false as const,
      overlap_policy: 'non_additive_display_only' as const,
      source_facts: {
        kind: 'portfolio_ledger_import_versions' as const,
        source_materials_verified: true,
        freshness_status: 'not_defined',
        account_value_status: 'not_applicable_imported',
        artifacts: [{
          status: 'available',
          import_version_id: 'import-version-1',
          portfolio_name: 'Imported transactions',
          import_format: 'json',
          source_integrity_status: 'verified',
          source_schema_version: 1,
          source_sha256: 'a'.repeat(64),
          source_as_of: '2026-10-13',
          source_as_of_status: 'declared',
          source_currency: 'USD',
          currency_status: 'declared',
          freshness_status: 'not_defined',
          source_row_count: 2,
          trade_date_rows_present: 1,
          trade_date_coverage: 'partial',
          source_metadata_status: 'complete',
          source_rows_available: true,
        }],
      },
      account_total: { status: 'not_applicable_imported', currency: null, value: null },
      accounts: [],
      strategies: [],
      strategy_attribution: {
        status: 'not_applicable_imported',
        strategy_count: 0,
        attributed_value: null,
        unattributed_account_value: null,
        residual_basis: 'imported transaction materials do not establish account holdings',
      },
      coverage: {
        complete: false,
        account_facts_complete: false,
        source_materials_verified: true,
        code: 'IMPORTED_SOURCE_TRADE_DATES_INCOMPLETE',
      },
    }
    vi.mocked(portfolioApi.listCompositionVersions)
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, page_size: 50, has_more: false })
      .mockResolvedValueOnce({
        items: [{
          portfolio_ref: 'imported-portfolio',
          membership_version: 1,
          source_type: 'imported',
          base_currency: 'USD',
          created_at: '2026-10-15T00:00:00Z',
        }],
        total: 1,
        page: 1,
        page_size: 50,
        has_more: false,
      })
    vi.mocked(portfolioApi.getCompositionProjection).mockResolvedValueOnce(importedProjection)
    vi.mocked(portfolioApi.createCompositionVersion).mockResolvedValueOnce({
      portfolio_ref: 'imported-portfolio',
      membership_version: 1,
      source_type: 'imported',
      base_currency: 'USD',
      created_at: '2026-10-15T00:00:00Z',
      membership_sha256: 'b'.repeat(64),
      members: [{ kind: 'imported_ledger', ref: 'import-version-1' }],
      creditable: false,
    })

    const wrapper = doMount()
    await flushPromises()
    await wrapper.get('[data-test="portfolio-mode-composition"]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-test="portfolio-import-source-open"]').trigger('click')
    await flushPromises()

    await wrapper.get('[data-test="portfolio-import-source-name"]').setValue('Imported transactions')
    await wrapper.get('[data-test="portfolio-import-source-ref"]').setValue('imported-portfolio')
    await wrapper.get('[data-test="portfolio-import-source-base-currency"]').setValue('USD')
    await wrapper.get('[data-test="portfolio-import-source-as-of"]').setValue('2026-10-13')
    await wrapper.get('[data-test="portfolio-import-source-currency"]').setValue('USD')
    const rawRows = [
      { symbol: 'SYNTH-A', trade_type: 'buy', quantity: 2, price: 10 },
      { symbol: 'SYNTH-B', trade_type: 'sell', quantity: 1, price: 12, trade_date: '2026-10-12' },
    ]
    await wrapper.get('[data-test="portfolio-import-source-rows"]').setValue(JSON.stringify(rawRows))
    await wrapper.get('[data-test="portfolio-import-source-form"]').trigger('submit')
    await flushPromises()

    expect(portfolioLedgerApi.create).toHaveBeenCalledWith({
      name: 'Imported transactions',
      base_currency: 'USD',
      source_type: 'imported',
    })
    expect(portfolioLedgerApi.importTransactions).toHaveBeenCalledWith(
      'ledger-import-1',
      expect.objectContaining({
        format: 'json',
        transactions: rawRows,
        source_as_of: '2026-10-13',
        source_currency: 'USD',
      }),
    )
    expect(portfolioApi.createCompositionVersion).toHaveBeenCalledWith({
      portfolio_ref: 'imported-portfolio',
      source_type: 'imported',
      base_currency: 'USD',
      members: [{ kind: 'imported_ledger', ref: 'import-version-1' }],
    })
    expect(portfolioApi.getCompositionProjection).toHaveBeenCalledWith('imported-portfolio', 1)
    expect(wrapper.find('[data-test="portfolio-import-source-dialog"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="portfolio-composition-source-status"]').text())
      .toContain('导入来源材料已验证')
    expect(wrapper.get('[data-test="portfolio-composition-account-total"]').text()).toBe('不可用')
    expect(wrapper.get('[data-test="portfolio-import-source-disclaimer"]').text())
      .toContain('不证明当前持仓或账户价值')
    expect(wrapper.get('[data-test="portfolio-import-source-artifact"]').text())
      .toContain('2026-10-13')
    expect(wrapper.get('[data-test="portfolio-import-source-artifact"]').text())
      .toContain('部分缺失')
    expect(wrapper.find('[data-test="portfolio-overview"]').exists()).toBe(false)
    expect(portfolioApi.getOverview).toHaveBeenCalledTimes(1)

    await wrapper.get('[data-test="portfolio-import-source-detail-import-version-1"]').trigger('click')
    await flushPromises()
    expect(portfolioLedgerApi.getImportSource).toHaveBeenCalledWith('import-version-1')
    expect(wrapper.get('[data-test="portfolio-import-source-raw-import-version-1"]').text())
      .toContain('SYNTH-A')
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
