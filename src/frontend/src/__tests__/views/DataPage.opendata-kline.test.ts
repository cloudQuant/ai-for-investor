import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import DataPage from '@/views/DataPage.vue'
import { elStubs } from '@/test/stubs'
import type {
  MarketInstrumentLookupResponse,
  MarketInstrumentOptionsResponse,
  OpenDataDirectKlineRequest,
  OpenDataDirectKlineResponse,
} from '@/api/marketData'
import instrumentReferenceFixture from '../fixtures/instrument_reference_v1.json'

const apiMocks = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  getOpenDataDirectKline: vi.fn(),
  lookupInstrument: vi.fn(),
  getQueryBundle: vi.fn(),
  getQueryContract: vi.fn(),
  queryLocalFirst: vi.fn(),
  listInstrumentOptions: vi.fn(),
  listCoverage: vi.fn(),
  refreshLocalCoverage: vi.fn(),
  refreshWarehouseCoverage: vi.fn(),
  listTables: vi.fn(),
}))

vi.mock('@/api/marketData', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/marketData')>()
  return {
    ...actual,
    marketDataApi: {
      ...actual.marketDataApi,
      getCapabilities: apiMocks.getCapabilities,
      getOpenDataDirectKline: apiMocks.getOpenDataDirectKline,
      lookupInstrument: apiMocks.lookupInstrument,
      getQueryBundle: apiMocks.getQueryBundle,
      getQueryContract: apiMocks.getQueryContract,
      queryLocalFirst: apiMocks.queryLocalFirst,
      listInstrumentOptions: apiMocks.listInstrumentOptions,
      listCoverage: apiMocks.listCoverage,
      refreshLocalCoverage: apiMocks.refreshLocalCoverage,
      refreshWarehouseCoverage: apiMocks.refreshWarehouseCoverage,
    },
  }
})

vi.mock('@/api/akshare', () => ({
  akshareTablesApi: { list: apiMocks.listTables },
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
}))

const ROUTE_IDS = [
  'market-data.query-v2',
  'market-data.online-fetch',
  'market-data.research-cache-fill',
  'market-data.research-backtest-bridge',
]

const ASSET_SELECTIONS_STORAGE_KEY = 'ai_for_investor:market:asset_selections'
const LEGACY_SELECTION_STORAGE_KEY = 'ai_for_investor:market:last_query'
const START_DATE = '2026-10-01'
const END_DATE = '2026-10-02'

const frozenOptionsResponse = (
  instrumentReferenceFixture.options_response as MarketInstrumentOptionsResponse
)

const instrumentSelectStub = defineComponent({
  inheritAttrs: false,
  props: { allowCreate: { type: Boolean, default: true } },
  setup(props, { attrs, slots }) {
    return () => h('div', {
      ...attrs,
      'data-allow-create': String(props.allowCreate),
    }, slots.default?.())
  },
})

const instrumentDatePickerStub = defineComponent({
  inheritAttrs: false,
  props: [
    'modelValue',
    'type',
    'valueFormat',
    'clearable',
    'placeholder',
    'startPlaceholder',
    'endPlaceholder',
  ],
  emits: ['update:modelValue', 'change'],
  setup(props, { attrs, emit }) {
    return () => h('input', {
      ...attrs,
      value: typeof props.modelValue === 'string' ? props.modelValue : '',
      onInput: (event: Event) => emit(
        'update:modelValue',
        (event.target as HTMLInputElement).value,
      ),
      onChange: (event: Event) => emit('change', (event.target as HTMLInputElement).value),
    })
  },
})

const instrumentQueryButtonStub = defineComponent({
  inheritAttrs: false,
  props: {
    loading: { type: Boolean, default: false },
    nativeType: { type: String, default: 'button' },
  },
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', {
      ...attrs,
      type: props.nativeType,
      disabled: props.loading,
      onClick: () => emit('click'),
    }, slots.default?.())
  },
})

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function openDataOptions(): MarketInstrumentOptionsResponse {
  return {
    ...frozenOptionsResponse,
    items: frozenOptionsResponse.items.map((item) => ({ ...item })),
  }
}

function lifecycleState(
  capabilityId: string,
  scope: 'rollout' | 'route',
  routeId: string | null,
  effective: boolean,
) {
  return {
    capability_id: capabilityId,
    scope,
    route_id: routeId,
    declared: effective,
    installed: effective,
    verified: effective,
    authorized: effective,
    effective,
    reason_code: effective ? null : 'CAPABILITY_LEDGER_MISSING',
  }
}

function capabilityDocument(
  mode: 'opendata' | 'opendata_ineffective' | 'legacy' = 'opendata',
) {
  const gates = mode === 'opendata'
    ? [true, true, false, false]
    : mode === 'opendata_ineffective'
      ? [true, true, false, false]
      : [false, false, false, false]
  const states = ROUTE_IDS.map((capabilityId, index) => (
    lifecycleState(capabilityId, 'rollout', null, gates[index] as boolean)
  ))
  const routeId = mode === 'legacy'
    ? 'akshare-stock-kline-legacy-v1'
    : 'opendata-stock-daily-v1'
  states.push(lifecycleState(
    `market-data.route:${routeId}`,
    'route',
    routeId,
    mode === 'opendata',
  ))
  return {
    version: 'market-data-capabilities-v1',
    query_v2_enabled: gates[0],
    online_fetch_enabled: gates[1],
    research_cache_fill_enabled: gates[2],
    research_backtest_bridge_enabled: gates[3],
    capability_states: states,
  }
}

function legacyLookup(): MarketInstrumentLookupResponse {
  return {
    asset_type: 'stock',
    symbol: '000001',
    name: 'LOCAL_LOOKUP_NAME_SENTINEL',
    market: 'CN',
    provider: 'LOCAL_PROVIDER_SENTINEL',
    snapshot: {
      price: 98765.43,
      turnover: 54321,
      update_time: 'LOCAL_SNAPSHOT_TIME_SENTINEL',
      data_source_table: 'LOCAL_SNAPSHOT_TABLE_SENTINEL',
    },
    history: {
      period: 'daily',
      rows: [{
        date: '2026-09-29',
        open: 98760,
        high: 98770,
        low: 98750,
        close: 98765.43,
        volume: 43210,
        turnover: 54321,
      }],
      total: 1,
    },
    indicators: {
      latest_close: 98765.43,
      return_pct: 3.21,
      observation_count: 1,
    },
    warnings: [],
  }
}

function directResponse(request: OpenDataDirectKlineRequest): OpenDataDirectKlineResponse {
  const dates = request.start_date === request.end_date
    ? [request.start_date]
    : [request.start_date, request.end_date]
  const records = dates.map((date, index) => ({
    date,
    open: 10 + index,
    high: 12 + index,
    low: 9 + index,
    close: 11 + index,
    volume: 1200 + index * 300,
    change: index ? 9.09 : 1.25,
  }))
  return {
    symbol: request.symbol,
    count: records.length,
    kline: {
      dates: [...dates],
      ohlc: records.map((record) => [
        record.open,
        record.close,
        record.low,
        record.high,
      ] as const),
      volumes: records.map((record) => record.volume),
    },
    records,
    provenance: {
      provider_id: 'opendata',
      provider_adapter_revision: 'fixture-adapter-v1',
      source_revision: null,
      request_id: 'fixture-direct-request-1',
      retrieved_at: '2026-10-02T16:00:00+08:00',
      raw_payload_sha256: 'b'.repeat(64),
      source_registry_id: 'fixture-direct-registry',
      coverage_status: 'unknown',
      source_available_at: 'unknown',
      source_snapshot_id: null,
      observation_revision_ids: null,
      committed_at: null,
      durable_receipt: 'not_created',
    },
  }
}

function coverageFixture() {
  return {
    total: 1,
    refreshed: false,
    items: [{
      id: 'LOCAL_COVERAGE_SENTINEL',
      asset_type: 'stock',
      symbol: '000001',
      timeframe: '1d',
      provider: 'LOCAL_COVERAGE_PROVIDER_SENTINEL',
      start_date: '2026-09-01',
      end_date: '2026-09-29',
      row_count: 20,
      missing_count: 2,
      missing_ratio: 0.1,
      latest_bar_time: '2026-09-29',
      quality_status: 'warning',
      source_path: 'LOCAL_COVERAGE_PATH_SENTINEL',
      updated_at: '2026-10-01T00:00:00Z',
    }],
  }
}

function relatedTableFixture() {
  return {
    items: [{
      id: 208,
      table_name: 'LOCAL_RELATED_TABLE_SENTINEL',
      table_comment: 'synthetic local table',
      category: 'stocks',
      script_id: 'fixture',
      row_count: 12,
      last_update_time: '2026-10-01T00:00:00Z',
      last_update_status: 'success',
      data_start_date: '2026-09-01',
      data_end_date: '2026-09-29',
      symbol_raw: '000001',
      symbol_normalized: '000001',
      market: 'CN',
      asset_type: 'stock',
      metadata: {},
      created_at: '2026-10-01T00:00:00Z',
      updated_at: '2026-10-01T00:00:00Z',
    }],
    total: 1,
    page: 1,
    page_size: 8,
  }
}

function createDeferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (error: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('DataPage OpenData direct daily chart', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('VITE_MARKET_DATA_QUERY_V2_ENABLED', 'false')
    vi.stubEnv('VITE_MARKET_DATA_QUERY_BUNDLE_ENABLED', 'false')
    window.localStorage.removeItem(ASSET_SELECTIONS_STORAGE_KEY)
    window.localStorage.removeItem(LEGACY_SELECTION_STORAGE_KEY)

    apiMocks.getCapabilities.mockResolvedValue(capabilityDocument())
    apiMocks.getOpenDataDirectKline.mockImplementation((request: OpenDataDirectKlineRequest) => (
      Promise.resolve(directResponse(request))
    ))
    apiMocks.lookupInstrument.mockResolvedValue(legacyLookup())
    apiMocks.getQueryBundle.mockRejectedValue({ response: { status: 404 } })
    apiMocks.getQueryContract.mockRejectedValue({ response: { status: 404 } })
    apiMocks.queryLocalFirst.mockRejectedValue(new Error('local v2 fixture unavailable'))
    apiMocks.listInstrumentOptions.mockResolvedValue(openDataOptions())
    apiMocks.listCoverage.mockResolvedValue(coverageFixture())
    apiMocks.refreshLocalCoverage.mockResolvedValue({ total: 0, refreshed: true, items: [] })
    apiMocks.refreshWarehouseCoverage.mockResolvedValue({ total: 0, refreshed: true, items: [] })
    apiMocks.listTables.mockResolvedValue(relatedTableFixture())
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    window.localStorage.removeItem(ASSET_SELECTIONS_STORAGE_KEY)
    window.localStorage.removeItem(LEGACY_SELECTION_STORAGE_KEY)
    vi.unstubAllEnvs()
    vi.clearAllMocks()
  })

  async function mountPage() {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/data/market', component: DataPage }],
    })
    await router.push('/data/market')
    await router.isReady()
    wrapper = mount(DataPage, {
      global: {
        plugins: [router],
        stubs: {
          ...elStubs,
          'el-select': instrumentSelectStub,
          'el-date-picker': instrumentDatePickerStub,
          'el-button': instrumentQueryButtonStub,
        },
      },
    })
    await flushPromises()
    await flushPromises()
    return wrapper
  }

  async function clickQuery(page: VueWrapper) {
    await page.get('[data-test="market-instrument-query"]').trigger('click')
    await flushPromises()
  }

  function freezeLegacyState(vm: Record<string, unknown>) {
    return clone({
      result: vm.result,
      snapshot: vm.snapshot,
      historyRows: vm.historyRows,
      displayHistoryRows: vm.displayHistoryRows,
      ohlcHistoryRows: vm.ohlcHistoryRows,
      heroStats: vm.heroStats,
      rangeStats: vm.rangeStats,
      assetKpiCards: vm.assetKpiCards,
      coverageRows: vm.coverageRows,
      dataCoverageRows: vm.dataCoverageRows,
      coverageSummaryCards: vm.coverageSummaryCards,
      coverageScore: vm.coverageScore,
      assetDetailRows: vm.assetDetailRows,
      snapshotMetrics: vm.snapshotMetrics,
      relatedTables: vm.relatedTables,
      marketDataPlatformStatus: vm.marketDataPlatformStatus,
      chartModeOptions: vm.chartModeOptions,
    })
  }

  it('keeps mount local-only and leaves the existing complete legacy view intact', async () => {
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>

    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).toHaveBeenCalledWith(expect.objectContaining({
      asset_type: 'stock',
      symbol: '000001',
      refresh_online: false,
    }))
    expect(vm.dataPageDisplayMode).toBe('legacy')
    expect((vm.openDataDirectKlineDisplay as { status: string }).status).toBe('idle')
    expect(page.find('.asset-overview').exists()).toBe(true)
    expect(page.find('.snapshot-card').exists()).toBe(true)
    expect(page.find('.history-table-card').exists()).toBe(true)
    expect(page.text()).toContain('LOCAL_LOOKUP_NAME_SENTINEL')
    expect(page.text()).toContain('LOCAL_SNAPSHOT_TIME_SENTINEL')
    expect(page.text()).toContain('LOCAL_RELATED_TABLE_SENTINEL')
  })

  it('routes verified stock daily to the direct endpoint and isolates its display', async () => {
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    const form = vm.form as { asset_type: string; symbol: string; period: string }
    const legacyBefore = freezeLegacyState(vm)
    vm.dateRange = [START_DATE, END_DATE]
    form.symbol = '000001'
    form.period = 'daily'
    apiMocks.lookupInstrument.mockClear()
    apiMocks.getQueryBundle.mockClear()
    apiMocks.getQueryContract.mockClear()
    apiMocks.queryLocalFirst.mockClear()

    await clickQuery(page)

    expect(apiMocks.getOpenDataDirectKline).toHaveBeenCalledTimes(1)
    expect(apiMocks.getOpenDataDirectKline).toHaveBeenCalledWith({
      symbol: '000001',
      start_date: START_DATE,
      end_date: END_DATE,
      period: 'daily',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()

    const display = vm.openDataDirectKlineDisplay as Record<string, unknown>
    expect(vm.dataPageDisplayMode).toBe('opendata_direct')
    expect(display.status).toBe('ready')
    expect(display.request).toEqual({
      symbol: '000001',
      start_date: START_DATE,
      end_date: END_DATE,
      period: 'daily',
    })
    expect(display.symbolLabel).toBe('000001')
    expect(display.rangeLabel).toContain(START_DATE)
    expect(display.rangeLabel).toContain(END_DATE)
    expect(display.returnedBarCount).toBe(2)
    expect(display.retrievedAt).toBe('2026-10-02T16:00:00+08:00')
    expect(display.coverageStatus).toBe('unknown')
    expect(display.sourceAvailableAt).toBe('unknown')
    expect(display.durableReceipt).toBe('not_created')
    expect(display.rows).toHaveLength(2)
    expect(display).not.toHaveProperty('rawPayloadSha256')
    expect(display).not.toHaveProperty('sourceRegistryId')

    const directChart = page.get('[data-test="market-opendata-direct-chart"]')
    expect(directChart.text()).toContain(display.symbolLabel as string)
    expect(directChart.text()).toContain(display.rangeLabel as string)
    expect(directChart.text()).toContain(String(display.returnedBarCount))
    expect(directChart.text()).toContain(display.retrievedAt as string)
    expect(directChart.text()).toMatch(/unknown|未知/i)
    expect(page.find('.asset-overview').exists()).toBe(false)
    expect(page.find('.history-metrics-grid').exists()).toBe(false)
    expect(page.find('.market-data-platform-status').exists()).toBe(false)
    expect(page.find('.market-side-panels').exists()).toBe(false)
    expect(page.find('.snapshot-card').exists()).toBe(false)
    expect(page.find('.asset-detail-card').exists()).toBe(false)
    expect(page.find('.history-table-card').exists()).toBe(false)
    expect(page.find('.market-data-details').exists()).toBe(false)
    expect(page.find('[data-test="market-main-chart"]').exists()).toBe(false)
    expect(page.text()).toContain('OpenData')
    expect(page.text()).not.toContain('LOCAL_LOOKUP_NAME_SENTINEL')
    expect(page.text()).not.toContain('LOCAL_PROVIDER_SENTINEL')
    expect(page.text()).not.toContain('LOCAL_SNAPSHOT_TIME_SENTINEL')
    expect(page.text()).not.toContain('LOCAL_RELATED_TABLE_SENTINEL')
    expect(page.text()).not.toContain('98765.43')

    expect(freezeLegacyState(vm)).toEqual(legacyBefore)

    await (vm.lookupInstrument as (intent: string) => Promise<void>)('local_only')
    await flushPromises()
    expect(vm.dataPageDisplayMode).toBe('legacy')
    expect(freezeLegacyState(vm)).toEqual(legacyBefore)
    expect(page.find('.asset-overview').exists()).toBe(true)
    expect(page.find('.snapshot-card').exists()).toBe(true)
    expect(apiMocks.getOpenDataDirectKline).toHaveBeenCalledTimes(1)
  })

  it('clears prior direct bars after failure without fallback or error leakage', async () => {
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    const legacyBefore = freezeLegacyState(vm)
    vm.dateRange = [START_DATE, END_DATE]
    apiMocks.lookupInstrument.mockClear()
    apiMocks.getOpenDataDirectKline.mockResolvedValueOnce(directResponse({
      symbol: '000001',
      start_date: START_DATE,
      end_date: END_DATE,
      period: 'daily',
    }))

    await clickQuery(page)
    expect((vm.openDataDirectKlineDisplay as { rows: unknown[] }).rows).toHaveLength(2)

    apiMocks.getOpenDataDirectKline.mockRejectedValueOnce({
      response: {
        status: 503,
        data: { detail: 'RAW_UPSTREAM_SECRET_SENTINEL' },
      },
    })
    await clickQuery(page)

    const display = vm.openDataDirectKlineDisplay as Record<string, unknown>
    expect(display.status).toBe('unavailable')
    expect(display.reason).toBe('DIRECT_REQUEST_FAILED')
    expect(display.rows).toEqual([])
    expect(page.text()).not.toContain('RAW_UPSTREAM_SECRET_SENTINEL')
    expect(page.text()).not.toContain('LOCAL_SNAPSHOT_TIME_SENTINEL')
    expect(page.find('[data-test="market-opendata-direct-chart"]').exists()).toBe(true)
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()
    expect(freezeLegacyState(vm)).toEqual(legacyBefore)
  })

  it('clears prior direct bars when the API rejects a malformed DTO', async () => {
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    apiMocks.lookupInstrument.mockClear()
    vm.dateRange = [START_DATE, END_DATE]
    const legacyBefore = freezeLegacyState(vm)

    await clickQuery(page)
    expect((vm.openDataDirectKlineDisplay as { rows: unknown[] }).rows).toHaveLength(2)

    apiMocks.getOpenDataDirectKline.mockRejectedValueOnce(
      new Error('OPENDATA_DIRECT_RESPONSE_INVALID'),
    )
    await clickQuery(page)

    const display = vm.openDataDirectKlineDisplay as Record<string, unknown>
    expect(display.status).toBe('unavailable')
    expect(display.reason).toBe('DIRECT_RESPONSE_INVALID')
    expect(display.rows).toEqual([])
    expect(page.text()).not.toContain('OPENDATA_DIRECT_RESPONSE_INVALID')
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()
    expect(freezeLegacyState(vm)).toEqual(legacyBefore)
  })

  it('blocks an unknown capability census without making the old lookup the fallback', async () => {
    apiMocks.getCapabilities.mockResolvedValue({
      ...capabilityDocument(),
      capability_states: [],
    })
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    const legacyBefore = freezeLegacyState(vm)
    apiMocks.lookupInstrument.mockClear()

    await clickQuery(page)

    const display = vm.openDataDirectKlineDisplay as Record<string, unknown>
    expect(vm.dataPageDisplayMode).toBe('opendata_direct')
    expect(display.status).toBe('unavailable')
    expect(display.reason).toBe('CAPABILITY_CENSUS_INVALID')
    expect(display.rows).toEqual([])
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()
    expect(page.find('.asset-overview').exists()).toBe(false)
    expect(page.find('.snapshot-card').exists()).toBe(false)
    expect(page.text()).not.toContain('LOCAL_SNAPSHOT_TIME_SENTINEL')
    expect(freezeLegacyState(vm)).toEqual(legacyBefore)
  })

  it('blocks direct and compatibility queries when capability lookup rejects', async () => {
    apiMocks.getCapabilities.mockRejectedValue(new Error('CAPABILITIES_DOWN_SENTINEL'))
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    const legacyBefore = freezeLegacyState(vm)
    apiMocks.getOpenDataDirectKline.mockClear()
    apiMocks.lookupInstrument.mockClear()
    apiMocks.getQueryBundle.mockClear()
    apiMocks.getQueryContract.mockClear()
    apiMocks.queryLocalFirst.mockClear()

    await clickQuery(page)

    const display = vm.openDataDirectKlineDisplay as Record<string, unknown>
    expect(vm.dataPageDisplayMode).toBe('opendata_direct')
    expect(display.status).toBe('unavailable')
    expect(display.reason).toBe('CAPABILITIES_UNAVAILABLE')
    expect(display.rows).toEqual([])
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()
    expect(page.text()).not.toContain('CAPABILITIES_DOWN_SENTINEL')
    expect(freezeLegacyState(vm)).toEqual(legacyBefore)
  })

  it('blocks a disabled OpenData route instead of treating it as legacy', async () => {
    apiMocks.getCapabilities.mockResolvedValue(capabilityDocument('opendata_ineffective'))
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    apiMocks.lookupInstrument.mockClear()

    await clickQuery(page)

    const display = vm.openDataDirectKlineDisplay as Record<string, unknown>
    expect(vm.dataPageDisplayMode).toBe('opendata_direct')
    expect(display.status).toBe('unavailable')
    expect(display.reason).toBe('OPENDATA_ROUTE_INEFFECTIVE')
    expect(display.rows).toEqual([])
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()
  })

  it('keeps a legacy census with closed gates on the existing lookup path', async () => {
    apiMocks.getCapabilities.mockResolvedValue(capabilityDocument('legacy'))
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    apiMocks.lookupInstrument.mockClear()

    await clickQuery(page)

    expect(vm.dataPageDisplayMode).toBe('legacy')
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).toHaveBeenCalledWith(expect.objectContaining({
      asset_type: 'stock',
      symbol: '000001',
      period: 'daily',
      refresh_online: false,
    }))
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()
    expect(page.find('.asset-overview').exists()).toBe(true)
    expect(page.find('.snapshot-card').exists()).toBe(true)
    expect(page.text()).toContain('LOCAL_LOOKUP_NAME_SENTINEL')
  })

  it('blocks unsupported selections and admits the inclusive 366-day maximum', async () => {
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    const form = vm.form as { asset_type: string; symbol: string; period: string }

    form.asset_type = 'fund'
    apiMocks.lookupInstrument.mockClear()
    await clickQuery(page)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).reason)
      .toBe('UNSUPPORTED_ASSET')
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()

    form.asset_type = 'stock'
    form.period = 'weekly'
    apiMocks.lookupInstrument.mockClear()
    await clickQuery(page)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).reason)
      .toBe('UNSUPPORTED_PERIOD')
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()

    form.period = 'daily'
    vm.dateRange = ['2025-10-26', '2026-10-27']
    apiMocks.lookupInstrument.mockClear()
    await clickQuery(page)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).reason)
      .toBe('INVALID_DATE_RANGE')
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()

    form.symbol = 'UNVERIFIED_TYPED_SYMBOL'
    vm.dateRange = [START_DATE, END_DATE]
    apiMocks.lookupInstrument.mockClear()
    await clickQuery(page)
    expect(apiMocks.getOpenDataDirectKline).not.toHaveBeenCalled()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(apiMocks.getQueryBundle).not.toHaveBeenCalled()
    expect(apiMocks.getQueryContract).not.toHaveBeenCalled()
    expect(apiMocks.queryLocalFirst).not.toHaveBeenCalled()

    form.symbol = '000001'
    vm.dateRange = ['2025-10-27', '2026-10-27']
    await clickQuery(page)
    expect(apiMocks.getOpenDataDirectKline).toHaveBeenCalledWith({
      symbol: '000001',
      start_date: '2025-10-27',
      end_date: '2026-10-27',
      period: 'daily',
    }, expect.objectContaining({ signal: expect.any(AbortSignal) }))
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).status).toBe('ready')
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
  })

  it('aborts synchronously on selector edits and ignores the late response', async () => {
    const deferred = createDeferred<OpenDataDirectKlineResponse>()
    apiMocks.getOpenDataDirectKline.mockReturnValueOnce(deferred.promise)
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    const form = vm.form as { symbol: string; period: string }
    vm.dateRange = [START_DATE, END_DATE]
    form.symbol = '000001'
    form.period = 'daily'

    await clickQuery(page)
    const [request, options] = apiMocks.getOpenDataDirectKline.mock.calls[0] as [
      OpenDataDirectKlineRequest,
      { signal?: AbortSignal },
    ]
    expect(options.signal).toBeInstanceOf(AbortSignal)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).status).toBe('loading')
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).request).toEqual(request)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).symbolLabel)
      .toBe(request.symbol)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).rangeLabel)
      .toContain(request.start_date)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).rangeLabel)
      .toContain(request.end_date)

    form.symbol = '600001'
    vm.dateRange = ['2026-10-05', END_DATE]
    expect(options.signal?.aborted).toBe(true)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).status).toBe('idle')
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).rows).toEqual([])

    deferred.resolve(directResponse(request))
    await flushPromises()
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).status).not.toBe('ready')
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).rows).toEqual([])
    expect(page.text()).not.toContain('2026-10-01')
    expect(page.text()).not.toContain('2026-10-02')
  })

  it('aborts on unmount and prevents a late response from becoming ready', async () => {
    const deferred = createDeferred<OpenDataDirectKlineResponse>()
    apiMocks.getOpenDataDirectKline.mockReturnValueOnce(deferred.promise)
    const page = await mountPage()
    const vm = page.vm as unknown as Record<string, unknown>
    vm.dateRange = [START_DATE, END_DATE]

    await clickQuery(page)
    const options = apiMocks.getOpenDataDirectKline.mock.calls[0]?.[1] as {
      signal?: AbortSignal
    } | undefined
    expect(options?.signal).toBeInstanceOf(AbortSignal)
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).status).toBe('loading')

    page.unmount()
    wrapper = undefined
    expect(options?.signal?.aborted).toBe(true)
    deferred.resolve(directResponse({
      symbol: '000001',
      start_date: START_DATE,
      end_date: END_DATE,
      period: 'daily',
    }))
    await flushPromises()

    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).status).not.toBe('ready')
    expect((vm.openDataDirectKlineDisplay as Record<string, unknown>).rows).toEqual([])
    expect(apiMocks.getOpenDataDirectKline).toHaveBeenCalledTimes(1)
  })
})
