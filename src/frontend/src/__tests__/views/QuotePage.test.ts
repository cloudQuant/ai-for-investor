import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { useQuoteStore } from '@/stores/quote'
import QuotePage from '@/views/QuotePage.vue'
import { mountWithPlugins } from '@/test/mountWithPlugins'

const storageState = new Map<string, string>()

const quoteApiMocks = vi.hoisted(() => ({
  listSources: vi.fn(),
  getSymbols: vi.fn(),
  addSymbols: vi.fn(),
  removeSymbols: vi.fn(),
  removeSubscriptions: vi.fn(),
  searchSymbols: vi.fn(),
  getQuotes: vi.fn(),
  getChartData: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  warning: vi.fn(),
  error: vi.fn(),
}))

const chartMocks = vi.hoisted(() => ({
  setOption: vi.fn(),
  resize: vi.fn(),
  dispose: vi.fn(),
}))

const echartsInitMock = vi.hoisted(() => vi.fn(() => chartMocks))

vi.mock('element-plus', () => ({
  ElMessage: messageMocks,
}))

vi.mock('@element-plus/icons-vue', () => {
  const icon = { template: '<span class="icon-stub" />' }

  return {
    Search: icon,
    Refresh: icon,
    Plus: icon,
    Loading: icon,
    Delete: icon,
    Setting: icon,
    Filter: icon,
    Rank: icon,
    DataLine: icon,
    Connection: icon,
    WarningFilled: icon,
  }
})

vi.mock('@/api/quote', () => ({
  quoteApi: quoteApiMocks,
}))

vi.mock('echarts', () => ({
  init: echartsInitMock,
}))

const PopconfirmStub = defineComponent({
  name: 'QuotePopconfirmStub',
  props: ['title'],
  emits: ['confirm'],
  setup(props, { slots, emit }) {
    return () => h('div', { class: 'quote-popconfirm', 'data-title': props.title }, [
      slots.reference?.(),
      h('button', {
        type: 'button',
        'data-test': 'confirm-popconfirm',
        onClick: () => emit('confirm'),
      }, 'confirm'),
    ])
  },
})

const EmptyStateStub = defineComponent({
  name: 'QuoteEmptyStateStub',
  props: ['description'],
  setup(props, { slots }) {
    return () => h('div', { class: 'el-empty' }, [
      slots.description?.() ?? String(props.description ?? ''),
      slots.default?.(),
    ])
  },
})

const quotePageStubs = {
  Search: true,
  Refresh: true,
  Plus: true,
  Loading: true,
  Delete: true,
  Setting: true,
  Filter: true,
  Rank: true,
  DataLine: true,
  Connection: true,
  WarningFilled: true,
  'el-popover': { template: '<div class="el-popover"><slot name="reference" /><slot /></div>' },
  'el-drawer': { template: '<div class="el-drawer"><slot /></div>' },
  'el-popconfirm': PopconfirmStub,
  'el-empty': EmptyStateStub,
}

function mountQuotePage(globalMocks: Record<string, unknown> = {}) {
  return mountWithPlugins(QuotePage, {
    customStubs: quotePageStubs,
    global: { mocks: globalMocks },
  })
}

describe('QuotePage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
    storageState.clear()
    vi.stubGlobal('localStorage', {
      getItem: vi.fn((key: string) => storageState.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => {
        storageState.set(key, value)
      }),
      removeItem: vi.fn((key: string) => {
        storageState.delete(key)
      }),
      clear: vi.fn(() => {
        storageState.clear()
      }),
    })

    quoteApiMocks.listSources.mockResolvedValue({
      sources: [
        {
          source: 'eastmoney',
          source_label: '东方财富',
          status: 'available',
          status_message: null,
          capabilities: ['quotes'],
        },
      ],
    })
    quoteApiMocks.getSymbols.mockResolvedValue({
      source: 'eastmoney',
      default_symbols: [],
      custom_symbols: ['AG2406'],
      categories: ['贵金属', '能源'],
    })
    quoteApiMocks.addSymbols.mockResolvedValue({
      source: 'eastmoney',
      symbols: ['AG2406'],
    })
    quoteApiMocks.removeSymbols.mockResolvedValue({
      source: 'eastmoney',
      symbols: [],
    })
    quoteApiMocks.removeSubscriptions.mockResolvedValue({
      source: 'eastmoney',
      symbols: [],
    })
    quoteApiMocks.searchSymbols.mockResolvedValue({
      source: 'eastmoney',
      keyword: 'rb',
      results: [
        {
          symbol: 'RB2405',
          name: '螺纹钢主力',
          exchange: 'SHFE',
          category: 'futures',
        },
      ],
    })
    quoteApiMocks.getQuotes.mockResolvedValue({
      source: 'eastmoney',
      source_label: '东方财富',
      total: 1,
      ticks: [
        {
          source: 'eastmoney',
          source_label: '东方财富',
          symbol: 'RB2405',
          name: '螺纹钢主力',
          exchange: 'SHFE',
          category: 'futures',
          last_price: 3500,
          change: 10,
          change_pct: 1.2,
          bid_price: 3499,
          ask_price: 3501,
          high_price: 3510,
          low_price: 3480,
          open_price: 3490,
          prev_close: 3490,
          volume: 125000,
          turnover: 1000000,
          open_interest: 80000,
          update_time: '2026-01-01T09:30:00Z',
          status: 'trading',
          error_message: null,
        },
      ],
      fields: [
        { prop: 'symbol', label: '代码', visible: true, always_show: true },
        { prop: 'last_price', label: '最新价', visible: true },
        { prop: 'change_pct', label: '涨跌幅', visible: true },
      ],
      update_time: '2026-01-01T09:30:00Z',
      refresh_mode: 'polling',
    })
    quoteApiMocks.getChartData.mockResolvedValue({
      source: 'eastmoney',
      symbol: 'RB2405',
      timeframe: 'M5',
      total: 2,
      bars: [
        { date: '2026-01-01 09:30', open: 3490, high: 3510, low: 3488, close: 3500, volume: 1000 },
        { date: '2026-01-01 09:35', open: 3500, high: 3512, low: 3498, close: 3508, volume: 1200 },
      ],
    })
  })

  it('loads quotes and covers symbol, sort, column, format, and chart helpers', async () => {
    vi.setSystemTime(new Date('2026-07-24T06:30:45.000Z'))
    const wrapper = mountWithPlugins(QuotePage, {
      customStubs: {
        Search: true,
        Refresh: true,
        Plus: true,
        Loading: true,
        Delete: true,
        Setting: true,
        Filter: true,
        Rank: true,
        DataLine: true,
        Connection: true,
        WarningFilled: true,
        'el-popover': { template: '<div class="el-popover"><slot name="reference" /><slot /></div>' },
        'el-drawer': { template: '<div class="el-drawer"><slot /></div>' },
      },
    })

    await flushPromises()

    const store = useQuoteStore()
    expect(quoteApiMocks.listSources).toHaveBeenCalledTimes(1)
    expect(quoteApiMocks.getQuotes).toHaveBeenCalledWith('eastmoney')
    expect(quoteApiMocks.getSymbols).toHaveBeenCalledWith('eastmoney')
    expect(store.filteredTicks).toHaveLength(1)
    expect(store.updateTime).toBe('2026-07-24T06:30:45.000Z')
    expect(store.ticks[0].update_time).toBe('2026-07-24T06:30:45.000Z')
    expect(store.categories).toEqual(expect.arrayContaining(['能源', '贵金属', 'futures']))
    expect(store.columnConfig.map((column) => column.prop)).toEqual([
      'symbol',
      'name',
      'category',
      'last_price',
      'bid_price',
      'ask_price',
      'update_time',
    ])
    expect(wrapper.findAll('.quote-mobile-card')).toHaveLength(1)
    expect(wrapper.find('.quote-mobile-card').text()).toContain('RB2405')

    const vm = wrapper.vm as any
    vm.addKeyword = 'rb'
    vm.handleAddSearch()
    vi.advanceTimersByTime(300)
    await flushPromises()
    expect(quoteApiMocks.searchSymbols).toHaveBeenCalledWith('eastmoney', 'rb')

    vm.addSymbolDirect = 'ag2406'
    await vm.handleDirectAdd()
    await flushPromises()
    expect(quoteApiMocks.addSymbols).toHaveBeenCalledWith('eastmoney', ['AG2406'])
    expect(messageMocks.success).toHaveBeenCalledWith('已添加 AG2406')

    await vm.removeQuoteSubscription(store.ticks[0])
    expect(quoteApiMocks.removeSubscriptions).toHaveBeenCalledWith('eastmoney', ['RB2405'])

    const workspaceTick = {
      ...store.ticks[0],
      quote_key: 'workspace-gateway:RB2405',
      origins: ['workspace'],
    }
    store.ticks.push(workspaceTick)
    await vm.removeQuoteSubscription(workspaceTick)
    expect(store.dismissedWorkspaceQuoteKeys.has('workspace-gateway:RB2405')).toBe(true)

    vm.handleSourceClick({
      source: 'sim',
      source_label: '模拟源',
      status: 'not_configured',
      status_message: '未配置',
      capabilities: [],
    })
    expect(messageMocks.warning).toHaveBeenCalledWith('未配置')

    vm.handleSortChange({ prop: 'last_price', order: 'ascending' })
    expect(store.sortField).toBe('last_price')
    expect(store.sortOrder).toBe('asc')

    expect(vm.fmtPct(1.23)).toBe('+1.23%')
    expect(vm.fmtVol(120000)).toContain('万')
    expect(vm.formatTime('2026-01-01T09:30:00Z')).toBeTruthy()
    expect(vm.priceClass({ change_pct: 1.2 })).toContain('text-red-600')
    expect(vm.changeClass(-1)).toBe('text-green-600')
    expect(vm.isWorkspaceQuote({ origins: ['workspace'] })).toBe(true)
    expect(vm.isWorkspaceQuote({ origins: ['subscription'] })).toBe(false)

    vm.showColumnDialog = true
    await wrapper.vm.$nextTick()
    vm.onColDragStart(0)
    vm.onColDrop(1)
    vm.handleSaveColumns()
    expect(store.columnConfig[0].prop).toBe('name')
    vm.handleResetColumns()
    expect(store.columnConfig[0].prop).toBe('symbol')

    await vm.handleRowClick(store.filteredTicks[0])
    await flushPromises()
    expect(quoteApiMocks.getChartData).toHaveBeenCalledWith('eastmoney', 'RB2405', 'M5')

    echartsInitMock.mockClear()
    chartMocks.setOption.mockClear()
    vm.chartContainerRef = document.createElement('div')
    vm.renderChart()
    expect(echartsInitMock).toHaveBeenCalledTimes(1)
    expect(chartMocks.setOption).toHaveBeenCalledTimes(1)

    vm.flashSymbols = new Set(['RB2405'])
    expect(vm.rowClassName({ row: { symbol: 'RB2405' } })).toBe('tick-flash')
  })

  it('shows a querying status before the initial quote content is available', async () => {
    let resolveSources: ((value: unknown) => void) | undefined
    quoteApiMocks.listSources.mockReturnValueOnce(new Promise((resolve) => {
      resolveSources = resolve
    }))

    const wrapper = mountWithPlugins(QuotePage, {
      customStubs: {
        Search: true,
        Refresh: true,
        Plus: true,
        Loading: true,
        Delete: true,
        Setting: true,
        Filter: true,
        Rank: true,
        DataLine: true,
        Connection: true,
        WarningFilled: true,
        'el-popover': { template: '<div class="el-popover"><slot name="reference" /><slot /></div>' },
      },
    })
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.quote-loading-state [data-test="quote-initial-querying"]').text()).toContain('查询中')

    resolveSources?.({
      sources: [
        {
          source: 'eastmoney',
          source_label: '东方财富',
          status: 'available',
          status_message: null,
          capabilities: ['quotes'],
        },
      ],
    })
    await flushPromises()
    wrapper.unmount()
  })

  it.each([
    ['not_connected', '网关尚未连接'],
    ['not_configured', '数据源尚未配置'],
    ['unavailable', '上游暂不可用'],
  ] as const)('shows the %s source state and avoids quote requests', async (status, statusMessage) => {
    quoteApiMocks.listSources.mockResolvedValueOnce({
      sources: [
        {
          source: `source-${status}`,
          source_label: '测试数据源',
          status,
          status_message: statusMessage,
          capabilities: [],
        },
      ],
    })
    const router = { push: vi.fn() }
    const wrapper = mountQuotePage({ $router: router })

    await flushPromises()

    const stateCard = wrapper.get('.quote-state-card')
    if (status === 'not_configured') {
      expect(stateCard.text()).toContain('数据源未配置，请先完成相关配置')
    } else {
      expect(stateCard.text()).toContain(statusMessage)
    }
    expect(quoteApiMocks.getQuotes).not.toHaveBeenCalled()

    if (status === 'not_connected') {
      await stateCard.get('button').trigger('click')
      expect(router.push).toHaveBeenCalledWith('/gateways')
    } else {
      await wrapper.get('.source-tab').trigger('click')
      expect(messageMocks.warning).toHaveBeenCalledWith(statusMessage)
      expect(quoteApiMocks.getQuotes).not.toHaveBeenCalled()
    }

    wrapper.unmount()
  })

  it('shows a quote fetch error and retries against the active source', async () => {
    quoteApiMocks.getQuotes.mockRejectedValue(new Error('quote feed offline'))
    const wrapper = mountQuotePage()

    await flushPromises()
    expect(wrapper.get('.quote-error-text').text()).toBe('quote feed offline')
    expect(quoteApiMocks.getQuotes).toHaveBeenCalledWith('eastmoney')
    const callsBeforeRetry = quoteApiMocks.getQuotes.mock.calls.length

    quoteApiMocks.getQuotes.mockResolvedValue({
      source: 'eastmoney',
      source_label: '东方财富',
      total: 0,
      ticks: [],
      fields: [],
      update_time: null,
      refresh_mode: 'polling',
    })
    const retry = wrapper.findAll('button').find((button) => button.text().includes('重试'))
    expect(retry).toBeDefined()
    await retry!.trigger('click')
    await flushPromises()

    expect(quoteApiMocks.getQuotes).toHaveBeenCalledTimes(callsBeforeRetry + 1)
    expect(quoteApiMocks.getQuotes).toHaveBeenLastCalledWith('eastmoney')
    expect(wrapper.find('.quote-error-text').exists()).toBe(false)
    expect(wrapper.find('.quote-state-card').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows no search results after a symbol search request fails', async () => {
    quoteApiMocks.searchSymbols.mockRejectedValueOnce(new Error('symbol search failed'))
    const wrapper = mountQuotePage()
    await flushPromises()

    const vm = wrapper.vm as any
    vm.showAddDialog = true
    vm.addKeyword = 'unknown-symbol'
    vm.handleAddSearch()
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(quoteApiMocks.searchSymbols).toHaveBeenCalledWith('eastmoney', 'unknown-symbol')
    expect(wrapper.text()).toContain('未找到匹配品种')
    wrapper.unmount()
  })

  it('removes a subscription through the visible confirmation action', async () => {
    const wrapper = mountQuotePage()
    await flushPromises()

    const confirmActions = wrapper.findAll('[data-test="confirm-popconfirm"]')
    expect(confirmActions).toHaveLength(1)
    expect(confirmActions[0].element.parentElement?.getAttribute('data-title')).toBe('确定删除此订阅？')
    await confirmActions[0].trigger('click')
    await flushPromises()

    expect(quoteApiMocks.removeSubscriptions).toHaveBeenCalledWith('eastmoney', ['RB2405'])
    wrapper.unmount()
  })
})
