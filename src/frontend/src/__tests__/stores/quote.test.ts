import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { quoteApi } from '@/api/quote'
import type {
  DataSourceInfo,
  DefaultSymbolsResponse,
  QuoteListResponse,
  QuoteTick,
} from '@/api/quote'
import { useQuoteStore } from '@/stores/quote'

vi.mock('@/api/quote', () => ({
  quoteApi: {
    listSources: vi.fn(),
    getSymbols: vi.fn(),
    addSymbols: vi.fn(),
    removeSymbols: vi.fn(),
    removeSubscriptions: vi.fn(),
    searchSymbols: vi.fn(),
    getQuotes: vi.fn(),
    getChartData: vi.fn(),
  },
}))

function makeSource(source: string, status: DataSourceInfo['status'] = 'available'): DataSourceInfo {
  return {
    source,
    source_label: `${source} market data`,
    status,
    status_message: null,
    capabilities: [],
    gateway_count: 0,
    workspace_count: 0,
    running_symbol_count: 0,
    workspaces: [],
  }
}

function makeTick(symbol: string, overrides: Partial<QuoteTick> = {}): QuoteTick {
  return {
    source: 'alpha',
    source_label: 'Alpha',
    symbol,
    name: symbol,
    exchange: 'XSHG',
    category: 'stock',
    last_price: 10,
    change: 1,
    change_pct: 1,
    bid_price: 9.9,
    ask_price: 10.1,
    high_price: 11,
    low_price: 9,
    open_price: 9.5,
    prev_close: 9,
    volume: 100,
    turnover: 1000,
    open_interest: 1,
    update_time: '2026-10-01T00:00:00.000Z',
    status: 'ok',
    error_message: null,
    quote_key: `alpha:gateway:${symbol}`,
    gateway_key: 'gateway',
    origins: ['workspace'],
    workspace_ids: ['workspace-1'],
    workspace_names: ['Workspace 1'],
    ...overrides,
  }
}

function makeSymbolsResponse(overrides: Partial<DefaultSymbolsResponse> = {}): DefaultSymbolsResponse {
  return {
    source: 'alpha',
    default_symbols: [],
    custom_symbols: [],
    running_symbols: [],
    categories: [],
    ...overrides,
  }
}

function makeQuoteResponse(ticks: QuoteTick[] = [], overrides: Partial<QuoteListResponse> = {}): QuoteListResponse {
  return {
    source: 'alpha',
    source_label: 'Alpha',
    total: ticks.length,
    ticks,
    update_time: null,
    refresh_mode: 'polling',
    ...overrides,
  }
}

function createStore(source = 'alpha') {
  localStorage.setItem('btweb_quote_activeSource', JSON.stringify(source))
  return useQuoteStore()
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('useQuoteStore', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    vi.clearAllMocks()
    Object.values(quoteApi).forEach(fn => (fn as ReturnType<typeof vi.fn>).mockReset())
    vi.mocked(quoteApi.listSources).mockResolvedValue({ sources: [] })
    vi.mocked(quoteApi.getSymbols).mockResolvedValue(makeSymbolsResponse())
    vi.mocked(quoteApi.getQuotes).mockResolvedValue(makeQuoteResponse())
    vi.mocked(quoteApi.addSymbols).mockResolvedValue({ source: 'alpha', symbols: [] })
    vi.mocked(quoteApi.removeSymbols).mockResolvedValue({ source: 'alpha', symbols: [] })
    vi.mocked(quoteApi.removeSubscriptions).mockResolvedValue({ source: 'alpha', symbols: [] })
    vi.mocked(quoteApi.searchSymbols).mockResolvedValue({ source: 'alpha', keyword: '', results: [] })
    vi.mocked(quoteApi.getChartData).mockResolvedValue({
      source: 'alpha', symbol: '600000', timeframe: 'M1', bars: [], total: 0,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.useRealTimers()
  })

  it('starts empty and selects the first available source after loading sources', async () => {
    vi.mocked(quoteApi.listSources).mockResolvedValue({
      sources: [makeSource('offline', 'not_connected'), makeSource('alpha'), makeSource('beta')],
    })
    const store = useQuoteStore()

    expect(store.activeSource).toBe('')
    expect(store.ticks).toEqual([])
    await store.fetchSources()

    expect(store.sources.map(source => source.source)).toEqual(['offline', 'alpha', 'beta'])
    expect(store.activeSource).toBe('alpha')
    expect(store.activeSourceInfo?.source_label).toBe('alpha market data')
    expect(localStorage.getItem('btweb_quote_activeSource')).toBe(JSON.stringify('alpha'))
    expect(store.sourcesLoading).toBe(false)
  })

  it('retains a configured source when none is available and falls back to the first source without one', async () => {
    localStorage.setItem('btweb_quote_activeSource', JSON.stringify('offline'))
    const retained = useQuoteStore()
    vi.mocked(quoteApi.listSources).mockResolvedValueOnce({ sources: [makeSource('offline', 'unavailable')] })
    await retained.fetchSources()
    expect(retained.activeSource).toBe('offline')
    expect(localStorage.getItem('btweb_quote_activeSource')).toBe(JSON.stringify('offline'))

    localStorage.removeItem('btweb_quote_activeSource')
    const firstSource = useQuoteStore()
    vi.mocked(quoteApi.listSources).mockResolvedValueOnce({
      sources: [makeSource('first', 'not_configured'), makeSource('second', 'unavailable')],
    })
    await firstSource.fetchSources()
    expect(firstSource.activeSource).toBe('first')
  })

  it('keeps source state when the source request fails and always clears loading', async () => {
    vi.mocked(quoteApi.listSources).mockRejectedValueOnce(new Error('source endpoint unavailable'))
    const store = createStore()
    store.sources = [makeSource('cached')]

    await store.fetchSources()

    expect(store.sources).toEqual([makeSource('cached')])
    expect(store.activeSource).toBe('alpha')
    expect(store.sourcesLoading).toBe(false)
  })

  it('loads placeholders from subscription and running workspace metadata, normalizing categories', async () => {
    const source = makeSource('alpha')
    source.workspaces = [{
      workspace_id: 'ws-1', workspace_name: 'Portfolio', gateway_key: 'ctp-main',
      symbol_count: 2, symbols: ['600000', 'IF2612'],
    }]
    const store = createStore()
    store.sources = [source]
    store.customSymbols = ['600000']
    const gatewayQuotes = deferred<QuoteListResponse>()
    vi.mocked(quoteApi.getQuotes).mockReturnValueOnce(gatewayQuotes.promise)
    vi.mocked(quoteApi.getSymbols).mockResolvedValueOnce(makeSymbolsResponse({
      default_symbols: [
        { symbol: '600000', name: 'Pudong Bank', exchange: 'XSHG', category: 'equity' },
        { symbol: '', name: 'ignored', exchange: '', category: '' },
        { symbol: '000001', name: '', exchange: '', category: '' },
      ],
      custom_symbols: ['600000', '300001'],
      running_symbols: [
        { symbol: 'IF2612', name: 'Index Future', exchange: 'CCFX', category: 'futures' },
        { symbol: '300001', name: 'Duplicate subscription row', exchange: '', category: '' },
      ],
      categories: [' futures ', '', 'equity', 'equity'],
    }))

    const refresh = store.fetchQuotes()
    await vi.waitFor(() => expect(store.customSymbols).toEqual(['600000', '300001']))

    expect(store.categories).toEqual(['equity', 'futures'])
    expect(store.ticks.map(tick => tick.symbol).sort()).toEqual(['000001', '300001', '600000', 'IF2612'])
    expect(store.ticks.find(tick => tick.symbol === '000001')).toMatchObject({
      name: '000001', category: '', last_price: null, status: 'loading',
      quote_key: 'alpha:subscription:000001', origins: ['subscription'],
    })
    expect(store.ticks.find(tick => tick.symbol === '600000')).toMatchObject({
      name: '600000', category: '', quote_key: 'alpha:ctp-main:600000',
      origins: ['subscription', 'workspace'], workspace_ids: ['ws-1'],
      workspace_names: ['Portfolio'],
    })
    expect(store.ticks.find(tick => tick.symbol === 'IF2612')).toMatchObject({
      quote_key: 'alpha:ctp-main:IF2612', origins: ['workspace'],
    })
    gatewayQuotes.resolve(makeQuoteResponse([]))
    await refresh
  })

  it('retries a quote response whose rows do not have prices and timestamps successful rows locally', async () => {
    vi.useFakeTimers()
    const store = createStore()
    vi.mocked(quoteApi.getQuotes)
      .mockResolvedValueOnce(makeQuoteResponse([makeTick('600000', {
        last_price: null, bid_price: null, ask_price: null,
      })]))
      .mockResolvedValueOnce(makeQuoteResponse([makeTick('600000', {
        last_price: 10.5, update_time: 'source-clock',
      })], { refresh_mode: 'stream' }))

    const refresh = store.fetchQuotes()
    await vi.advanceTimersByTimeAsync(1200)
    await refresh

    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(2)
    expect(quoteApi.getQuotes).toHaveBeenNthCalledWith(1, 'alpha')
    expect(quoteApi.getQuotes).toHaveBeenNthCalledWith(2, 'alpha')
    expect(store.ticks[0].last_price).toBe(10.5)
    expect(store.ticks[0].update_time).not.toBe('source-clock')
    expect(store.updateTime).toBe(store.ticks[0].update_time)
    expect(store.refreshMode).toBe('stream')
    expect(store.quotesError).toBeNull()
    expect(store.quotesLoading).toBe(false)
  })

  it('deduplicates an in-flight refresh and ignores the late response from a previously selected source', async () => {
    const pendingAlpha = deferred<QuoteListResponse>()
    const store = createStore()
    vi.mocked(quoteApi.getQuotes).mockImplementation((source: string) => (
      source === 'alpha' ? pendingAlpha.promise : Promise.resolve(makeQuoteResponse([
        makeTick('000001', { source: 'beta', source_label: 'Beta', quote_key: 'beta:gw:000001' }),
      ], { source: 'beta', source_label: 'Beta' }))
    ))

    const oldRefresh = store.fetchQuotes()
    await store.fetchQuotes()
    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(1)
    await store.switchSource('beta')
    expect(store.activeSource).toBe('beta')
    expect(store.ticks.map(tick => tick.symbol)).toEqual(['000001'])
    expect(store.quotesLoading).toBe(false)

    pendingAlpha.resolve(makeQuoteResponse([makeTick('600000')]))
    await oldRefresh
    expect(store.activeSource).toBe('beta')
    expect(store.ticks.map(tick => tick.symbol)).toEqual(['000001'])
    expect(store.ticks[0].source).toBe('beta')
    expect(store.quotesLoading).toBe(false)
  })

  it('reports Error messages and uses the translated fallback for non-Error quote failures', async () => {
    const store = createStore()
    vi.mocked(quoteApi.getQuotes).mockRejectedValueOnce(new Error('gateway disconnected'))
    await store.fetchQuotes()
    expect(store.quotesError).toBe('gateway disconnected')
    expect(store.quotesLoading).toBe(false)

    vi.mocked(quoteApi.getQuotes).mockRejectedValueOnce({ status: 503 })
    await store.fetchQuotes()
    expect(store.quotesError).toBe('行情加载失败')
    expect(store.quotesLoading).toBe(false)
  })

  it('does not call quote endpoints without a selected source and ignores empty dismiss keys', async () => {
    const store = createStore('')
    await store.fetchQuotes()
    await store.addSymbol('600000')
    await store.removeSymbol('600000')
    await store.removeSubscription('600000')
    store.dismissWorkspaceQuote('')

    expect(quoteApi.getQuotes).not.toHaveBeenCalled()
    expect(quoteApi.getSymbols).not.toHaveBeenCalled()
    expect(quoteApi.addSymbols).not.toHaveBeenCalled()
    expect(quoteApi.removeSymbols).not.toHaveBeenCalled()
    expect(quoteApi.removeSubscriptions).not.toHaveBeenCalled()
    expect(store.dismissedWorkspaceQuoteKeys.size).toBe(0)
    expect(store.quotesLoading).toBe(false)
  })

  it('updates subscriptions through their distinct API actions and refreshes the selected source', async () => {
    const store = createStore()
    vi.mocked(quoteApi.addSymbols).mockResolvedValueOnce({ source: 'alpha', symbols: ['600000'] })
    vi.mocked(quoteApi.removeSymbols).mockResolvedValueOnce({ source: 'alpha', symbols: [] })
    vi.mocked(quoteApi.removeSubscriptions).mockResolvedValueOnce({ source: 'alpha', symbols: ['IF2612'] })
    vi.mocked(quoteApi.getSymbols)
      .mockResolvedValueOnce(makeSymbolsResponse({ custom_symbols: ['600000'] }))
      .mockResolvedValueOnce(makeSymbolsResponse())
      .mockResolvedValueOnce(makeSymbolsResponse({ custom_symbols: ['IF2612'] }))

    await store.addSymbol('600000')
    expect(quoteApi.addSymbols).toHaveBeenCalledWith('alpha', ['600000'])
    expect(store.customSymbols).toEqual(['600000'])
    await store.removeSymbol('600000')
    expect(quoteApi.removeSymbols).toHaveBeenCalledWith('alpha', ['600000'])
    expect(store.customSymbols).toEqual([])
    await store.removeSubscription('IF2612')
    expect(quoteApi.removeSubscriptions).toHaveBeenCalledWith('alpha', ['IF2612'])
    expect(store.customSymbols).toEqual(['IF2612'])
    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(3)
  })

  it('filters by text, category, trend, custom membership, numeric bounds, and open interest', () => {
    const store = createStore()
    store.ticks = [
      makeTick('A', { name: 'Alpha Bank', category: 'equity', change_pct: 4, volume: 500, open_interest: 2 }),
      makeTick('B', { name: 'Beta Future', category: 'future', change_pct: -2, volume: 200, open_interest: 8 }),
      makeTick('C', { name: 'Gamma Fund', category: 'fund', change_pct: 0, volume: 100, open_interest: null }),
      makeTick('D', { name: 'Delta Bond', category: 'equity', change_pct: null, volume: null, open_interest: 0 }),
    ]

    store.searchKeyword = 'beta'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B'])
    store.searchKeyword = 'Delta'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['D'])
    store.searchKeyword = ''
    store.filterCategory = 'equity'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['A', 'D'])
    store.filterCategory = ''
    store.filterTrend = 'up'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['A'])
    store.filterTrend = 'down'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B'])
    store.filterTrend = 'flat'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['C', 'D'])
    store.filterTrend = ''
    store.customSymbols = ['B', 'D']
    store.filterCustomOnly = true
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B', 'D'])
    store.filterChangePctMin = -3
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B'])
    store.filterChangePctMax = -3
    expect(store.filteredTicks).toEqual([])
    store.filterChangePctMin = null
    store.filterChangePctMax = null
    store.filterVolumeMin = 150
    store.filterVolumeMax = 250
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B'])
    store.filterHasOpenInterest = true
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B'])
    store.dismissWorkspaceQuote('alpha:gateway:B')
    expect(store.filteredTicks).toEqual([])
    expect(store.ticks).toHaveLength(4)
  })

  it('sorts nulls last in both directions and compares numeric and textual fields', () => {
    const store = createStore()
    store.ticks = [
      makeTick('C', { last_price: null, name: 'Gamma' }),
      makeTick('A', { last_price: 2, name: 'Alpha' }),
      makeTick('B', { last_price: 10, name: 'Beta' }),
    ]
    store.sortField = 'last_price'
    store.sortOrder = 'asc'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['A', 'B', 'C'])
    store.sortOrder = 'desc'
    expect(store.filteredTicks.map(tick => tick.symbol)).toEqual(['B', 'A', 'C'])
    store.sortField = 'name'
    store.sortOrder = 'asc'
    expect(store.filteredTicks.map(tick => tick.name)).toEqual(['Alpha', 'Beta', 'Gamma'])
    store.availableCategories = ['zeta', 'alpha']
    expect(store.categories).toEqual(['alpha', 'stock', 'zeta'])
  })

  it('persists and restores per-source sort state while clearing source-specific filters', async () => {
    const store = createStore()
    store.setSort('last_price')
    expect(store.sortField).toBe('last_price')
    expect(store.sortOrder).toBe('desc')
    expect(localStorage.getItem('btweb_quote_sort_field_alpha')).toBe(JSON.stringify('last_price'))
    store.searchKeyword = 'query'
    store.filterCategory = 'equity'
    store.filterTrend = 'up'
    store.filterCustomOnly = true
    store.filterChangePctMin = 3
    store.filterChangePctMax = 5
    store.filterVolumeMin = 100
    store.filterVolumeMax = 500
    store.filterHasOpenInterest = true
    await store.switchSource('beta')

    expect(localStorage.getItem('btweb_quote_activeSource')).toBe(JSON.stringify('beta'))
    expect(store.searchKeyword).toBe('')
    expect(store.filterCategory).toBe('')
    expect(store.filterTrend).toBe('')
    expect(store.filterCustomOnly).toBe(false)
    expect(store.hasAdvancedFilters).toBe(false)
    expect(store.ticks).toEqual([])
    expect(store.updateTime).toEqual(expect.any(String))

    store.setSort('symbol')
    expect(store.sortOrder).toBe('desc')
    await store.switchSource('alpha')
    expect(store.sortField).toBe('last_price')
    expect(store.sortOrder).toBe('desc')
  })

  it('searches symbols, clears empty searches, and clears results on disconnection', async () => {
    const store = createStore()
    store.symbolSearchResults = [{ symbol: 'old', name: 'Old', exchange: '', category: '' }]
    await store.searchSymbols('')
    expect(store.symbolSearchResults).toEqual([])
    expect(quoteApi.searchSymbols).not.toHaveBeenCalled()

    vi.mocked(quoteApi.searchSymbols).mockResolvedValueOnce({
      source: 'alpha', keyword: '600', results: [
        { symbol: '600000', name: 'Pudong Bank', exchange: 'XSHG', category: 'equity' },
      ],
    })
    await store.searchSymbols('600')
    expect(quoteApi.searchSymbols).toHaveBeenCalledWith('alpha', '600')
    expect(store.symbolSearchResults.map(item => item.symbol)).toEqual(['600000'])
    expect(store.symbolSearchLoading).toBe(false)

    vi.mocked(quoteApi.searchSymbols).mockRejectedValueOnce(new Error('gateway disconnected'))
    await store.searchSymbols('missing')
    expect(store.symbolSearchResults).toEqual([])
    expect(store.symbolSearchLoading).toBe(false)
  })

  it('persists custom column choices, ignores unknown columns, and restores defaults', async () => {
    const saved = [
      { prop: 'last_price', label: 'stale label', visible: false },
      { prop: 'unknown', label: 'Unknown', visible: true },
    ]
    localStorage.setItem('btweb_quote_columnConfig_alpha', JSON.stringify(saved))
    const store = createStore()
    await store.fetchQuotes()

    expect(store.columnConfig.find(column => column.prop === 'last_price')).toMatchObject({
      label: '最新价', visible: false,
    })
    expect(store.columnConfig.map(column => column.prop)).not.toContain('unknown')
    expect(store.columnConfig.map(column => column.prop)).toContain('symbol')

    store.setColumnConfig([
      { prop: 'symbol', label: 'changed', visible: false },
      { prop: 'not-a-real-field', label: 'Unknown', visible: true },
    ])
    expect(store.columnConfig[0]).toMatchObject({ prop: 'symbol', visible: false, always_show: true })
    expect(store.columnConfig.map(column => column.prop)).not.toContain('not-a-real-field')
    expect(JSON.parse(localStorage.getItem('btweb_quote_columnConfig_alpha') ?? '[]')).toEqual(store.columnConfig)

    store.resetColumnConfig()
    expect(store.columnConfig.every(column => column.visible)).toBe(true)
    expect(JSON.parse(localStorage.getItem('btweb_quote_columnConfig_alpha') ?? '[]')).toEqual(store.columnConfig)
  })

  it('updates and stops the polling refresh timer as settings change', async () => {
    vi.useFakeTimers()
    const store = createStore()
    store.setRefreshInterval(5)
    expect(localStorage.getItem('btweb_quote_refreshInterval')).toBe(JSON.stringify(5))
    store.setAutoRefresh(true)
    expect(localStorage.getItem('btweb_quote_autoRefresh')).toBe(JSON.stringify(true))

    await vi.advanceTimersByTimeAsync(5000)
    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(1)
    store.setRefreshInterval(10)
    await vi.advanceTimersByTimeAsync(9999)
    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(2)
    store.setAutoRefresh(false)
    await vi.advanceTimersByTimeAsync(20000)
    expect(quoteApi.getQuotes).toHaveBeenCalledTimes(2)
    expect(localStorage.getItem('btweb_quote_autoRefresh')).toBe(JSON.stringify(false))
    store.cleanup()
  })

  it('loads charts for the selected symbol and timeframe, and clears stale data on close or failure', async () => {
    const store = createStore()
    const bars = [{ date: '2026-10-01', open: 1, high: 3, low: 1, close: 2, volume: 10 }]
    vi.mocked(quoteApi.getChartData).mockResolvedValueOnce({
      source: 'alpha', symbol: '600000', timeframe: 'M5', bars, total: 1,
    })
    await store.openChart('600000')
    expect(store.chartDrawerVisible).toBe(true)
    expect(store.chartSymbol).toBe('600000')
    expect(store.chartBars).toEqual(bars)
    expect(quoteApi.getChartData).toHaveBeenCalledWith('alpha', '600000', 'M5')
    expect(store.chartLoading).toBe(false)

    await store.setChartTimeframe('D1')
    expect(localStorage.getItem('btweb_quote_chartTimeframe')).toBe(JSON.stringify('D1'))
    expect(quoteApi.getChartData).toHaveBeenLastCalledWith('alpha', '600000', 'D1')

    vi.mocked(quoteApi.getChartData).mockResolvedValueOnce({
      source: 'alpha', symbol: '600000', timeframe: 'D1', bars: [], total: 0,
      complete: false, error_code: 'SERVICE_MARKET_PROFILE_REQUIRED',
    })
    await store.fetchChartData()
    expect(store.chartBars).toEqual([])
    expect(store.chartError).toBe('SERVICE_MARKET_PROFILE_REQUIRED')

    vi.mocked(quoteApi.getChartData).mockRejectedValueOnce({ status: 502 })
    await store.fetchChartData()
    expect(store.chartBars).toEqual([])
    expect(store.chartError).toBe('图表数据加载失败')
    expect(store.chartLoading).toBe(false)
    store.closeChart()
    expect(store.chartDrawerVisible).toBe(false)
    expect(store.chartError).toBeNull()
    expect(store.chartBars).toEqual([])
  })

  it('skips chart requests for missing source or symbol and reports Error messages', async () => {
    const store = createStore('')
    await store.openChart('600000')
    expect(store.chartSymbol).toBe('600000')
    expect(store.chartDrawerVisible).toBe(true)
    expect(quoteApi.getChartData).not.toHaveBeenCalled()

    store.activeSource = 'alpha'
    store.chartSymbol = ''
    await store.fetchChartData()
    expect(quoteApi.getChartData).not.toHaveBeenCalled()

    store.chartSymbol = '600000'
    vi.mocked(quoteApi.getChartData).mockRejectedValueOnce(new Error('chart endpoint failed'))
    await store.fetchChartData()
    expect(store.chartError).toBe('chart endpoint failed')
    expect(store.chartBars).toEqual([])
  })

  it('contains malformed and unavailable local-storage operations', async () => {
    localStorage.setItem('btweb_quote_sort_field_alpha', '{broken')
    const store = createStore()
    expect(store.sortField).toBe('')

    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage quota exceeded')
    })
    expect(() => store.setSort('last_price')).not.toThrow()
    expect(store.sortField).toBe('last_price')
    setItem.mockRestore()

    const getItem = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })
    await store.switchSource('beta')
    expect(store.activeSource).toBe('beta')
    expect(store.sortField).toBe('')
    getItem.mockRestore()
  })
})
