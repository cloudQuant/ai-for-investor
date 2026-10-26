import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h } from 'vue'

import DataPage from '@/views/DataPage.vue'
import { elStubs } from '@/test/stubs'
import type {
  MarketInstrumentLookupResponse,
  MarketInstrumentOptionsResponse,
} from '@/api/marketData'
import instrumentReferenceFixture from '../fixtures/instrument_reference_v1.json'

const apiMocks = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  lookupInstrument: vi.fn(),
  getQueryBundle: vi.fn(),
  getQueryContract: vi.fn(),
  queryLocalFirst: vi.fn(),
  listInstrumentOptions: vi.fn(),
  listCoverage: vi.fn(),
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
      lookupInstrument: apiMocks.lookupInstrument,
      getQueryBundle: apiMocks.getQueryBundle,
      getQueryContract: apiMocks.getQueryContract,
      queryLocalFirst: apiMocks.queryLocalFirst,
      listInstrumentOptions: apiMocks.listInstrumentOptions,
      listCoverage: apiMocks.listCoverage,
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

const frozenOptionsResponse = instrumentReferenceFixture.options_response as MarketInstrumentOptionsResponse
const ASSET_SELECTIONS_STORAGE_KEY = 'ai_for_investor:market:asset_selections'
const LEGACY_SELECTION_STORAGE_KEY = 'ai_for_investor:market:last_query'

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
      onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
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

function openDataOptions(): MarketInstrumentOptionsResponse {
  return {
    ...frozenOptionsResponse,
    items: frozenOptionsResponse.items.map((item) => ({ ...item })),
  }
}

function successfulStockLookup(): MarketInstrumentLookupResponse {
  return {
    asset_type: 'stock',
    symbol: '000001',
    name: 'Synthetic verified stock',
    market: 'CN',
    provider: 'fixture',
    snapshot: { price: 12.5, update_time: '2026-10-26T00:00:00Z' },
    history: {
      period: 'daily',
      rows: [{ date: '2026-10-26', open: 12, high: 13, low: 11, close: 12.5, volume: 100 }],
      total: 1,
    },
    indicators: { latest_close: 12.5, observation_count: 1 },
    warnings: [],
  }
}

describe('DataPage OpenData instrument selector', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    vi.clearAllMocks()
    window.localStorage.removeItem(ASSET_SELECTIONS_STORAGE_KEY)
    window.localStorage.removeItem(LEGACY_SELECTION_STORAGE_KEY)
    apiMocks.getCapabilities.mockResolvedValue({
      version: 'market-data-capabilities-v1',
      query_v2_enabled: false,
      online_fetch_enabled: false,
      research_cache_fill_enabled: false,
      research_backtest_bridge_enabled: false,
    })
    apiMocks.lookupInstrument.mockRejectedValue(new Error('lookup unavailable'))
    apiMocks.getQueryBundle.mockRejectedValue({ response: { status: 404 } })
    apiMocks.getQueryContract.mockRejectedValue({ response: { status: 404 } })
    apiMocks.queryLocalFirst.mockRejectedValue(new Error('query unavailable'))
    apiMocks.listInstrumentOptions.mockResolvedValue(openDataOptions())
    apiMocks.listCoverage.mockResolvedValue({ items: [], total: 0 })
    apiMocks.refreshWarehouseCoverage.mockResolvedValue({ items: [], total: 0 })
    apiMocks.listTables.mockResolvedValue({ items: [] })
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
    window.localStorage.removeItem(ASSET_SELECTIONS_STORAGE_KEY)
    window.localStorage.removeItem(LEGACY_SELECTION_STORAGE_KEY)
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

  it('shows only verified OpenData instruments, preserves unknown coverage, and disables free-form creation', async () => {
    const response = openDataOptions()
    response.items.push({
      ...response.items[0],
      symbol: '999999',
      instrument_id: 'UNVERIFIED_TEST_ROW',
      catalog_verified: false,
    })
    apiMocks.listInstrumentOptions.mockResolvedValueOnce(response)

    const page = await mountPage()
    const vm = page.vm as any
    vm.form.symbol = 'CUSTOM'
    await vm.loadInstrumentOptions('600')

    expect(vm.instrumentOptions.map((item: { symbol: string }) => item.symbol)).toEqual(
      frozenOptionsResponse.items.map((item) => item.symbol),
    )
    expect(vm.instrumentOptions.some((item: { symbol: string }) => item.symbol === 'CUSTOM')).toBe(false)
    expect(vm.instrumentOptions.some((item: { symbol: string }) => item.symbol === '999999')).toBe(false)
    expect(vm.instrumentOptionsCatalogMode).toBe('opendata')
    expect(page.get('[data-test="market-instrument-select"]').attributes('data-allow-create')).toBe('false')
    expect(vm.instrumentAliasEffectiveOn).toBeNull()
    // Unknown availability is not a reason to reject a verified identity.
    expect(apiMocks.lookupInstrument).toHaveBeenCalled()
    expect(apiMocks.listInstrumentOptions).toHaveBeenNthCalledWith(1, {
      asset_type: 'stock',
      search: '000001',
      limit: 80,
    })
    expect(vm.formatInstrumentHistoryStatus(frozenOptionsResponse.items[0])).toBe('未知')
    expect(vm.instrumentOptionStatusTagType(frozenOptionsResponse.items[0])).toBe('info')
    expect(page.find('[data-test="market-instrument-effective-on"]').exists()).toBe(true)
  })

  it('sends an alias effective date only after explicit selection and retries the current search', async () => {
    const page = await mountPage()
    const vm = page.vm as any
    vm.searchInstrumentOptions('HIST')
    await flushPromises()
    expect(apiMocks.listInstrumentOptions).toHaveBeenLastCalledWith({
      asset_type: 'stock',
      search: 'HIST',
      limit: 80,
    })

    const effectiveOnPicker = page.get<HTMLInputElement>('[data-test="market-instrument-effective-on"]')
    effectiveOnPicker.element.value = '2018-06-01'
    await effectiveOnPicker.trigger('input')
    await effectiveOnPicker.trigger('change')
    await flushPromises()

    expect(vm.instrumentAliasEffectiveOn).toBe('2018-06-01')
    expect(apiMocks.listInstrumentOptions).toHaveBeenLastCalledWith({
      asset_type: 'stock',
      search: 'HIST',
      limit: 80,
      effective_on: '2018-06-01',
    })
  })

  it('clears stale OpenData items and shows a fixed actionable alias-date message without echoing errors', async () => {
    const page = await mountPage()
    const vm = page.vm as any
    apiMocks.listInstrumentOptions.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          message: 'RAW_UPSTREAM_SECRET_SENTINEL',
          detail: {
            code: 'OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED',
            catalog_mode: 'opendata',
          },
        },
      },
    })

    await vm.loadInstrumentOptions('HIST')

    expect(vm.instrumentOptions).toEqual([])
    expect(vm.instrumentOptionsCatalogMode).toBe('opendata')
    expect(vm.instrumentOptionsError).toContain('生效日期')
    expect(vm.instrumentOptionsError).not.toContain('OPENDATA_REFERENCE_')
    expect(vm.instrumentOptionsError).not.toContain('RAW_UPSTREAM_SECRET_SENTINEL')
    expect(page.find('[data-test="market-instrument-options-error"]').text()).toBe(vm.instrumentOptionsError)
    expect(page.get('[data-test="market-instrument-select"]').attributes('data-allow-create')).toBe('false')
  })

  it('blocks a persisted unknown stock symbol after the OpenData catalog resolves', async () => {
    window.localStorage.setItem(
      ASSET_SELECTIONS_STORAGE_KEY,
      JSON.stringify({ stock: { symbol: 'PERSISTED_UNKNOWN', market: 'CN' } }),
    )

    const page = await mountPage()
    const vm = page.vm as any

    expect(vm.instrumentOptionsCatalogMode).toBe('opendata')
    expect(vm.instrumentOptionsError).toContain('已验证')
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
  })

  it('resolves catalog mode before honoring a query clicked while the directory is still pending', async () => {
    let resolveInitialCatalog: ((response: MarketInstrumentOptionsResponse) => void) | undefined
    apiMocks.listInstrumentOptions.mockImplementationOnce(
      () => new Promise((resolve) => { resolveInitialCatalog = resolve }),
    )
    const page = await mountPage()
    const vm = page.vm as any
    vm.form.symbol = 'UNVERIFIED_TYPED_SYMBOL'
    apiMocks.listInstrumentOptions.mockResolvedValueOnce(openDataOptions())

    await page.get('[data-test="market-instrument-query"]').trigger('click')
    await flushPromises()
    resolveInitialCatalog?.({
      asset_type: 'stock',
      total: 1,
      items: [{
        asset_type: 'stock',
        symbol: 'LEGACY_ONLY',
        name: 'Legacy response arriving late',
        has_snapshot: false,
        has_history: false,
        history_rows: 0,
      }],
    })
    await flushPromises()

    expect(vm.instrumentOptionsCatalogMode).toBe('opendata')
    expect(vm.instrumentOptionsError).toContain('已验证')
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(vm.instrumentOptions.map((item: { symbol: string }) => item.symbol)).toEqual(
      frozenOptionsResponse.items.map((item) => item.symbol),
    )
  })

  it('blocks a manually changed symbol after OpenData verified options are already loaded', async () => {
    const page = await mountPage()
    const vm = page.vm as any
    apiMocks.lookupInstrument.mockClear()
    vm.form.symbol = 'MANUALLY_CHANGED_UNKNOWN'

    await page.get('[data-test="market-instrument-query"]').trigger('click')
    await flushPromises()

    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(vm.instrumentOptionsError).toContain('已验证')
  })

  it('requires reselecting when a filtered OpenData response omits the current symbol', async () => {
    const page = await mountPage()
    const vm = page.vm as any
    apiMocks.lookupInstrument.mockClear()
    apiMocks.listInstrumentOptions.mockResolvedValueOnce({
      ...openDataOptions(),
      items: [openDataOptions().items[1]],
    })

    vm.searchInstrumentOptions('600001')
    await flushPromises()

    expect(vm.form.symbol).toBe('000001')
    expect(vm.instrumentOptions.map((item: { symbol: string }) => item.symbol)).toEqual(['600001'])
    expect(vm.instrumentOptionsError).toContain('重新选择')
    await page.get('[data-test="market-instrument-query"]').trigger('click')
    await flushPromises()
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
  })

  it('clears existing query results when an OpenData directory refresh fails', async () => {
    const page = await mountPage()
    const vm = page.vm as any
    apiMocks.lookupInstrument.mockClear()
    apiMocks.lookupInstrument.mockResolvedValueOnce(successfulStockLookup())
    apiMocks.listTables.mockResolvedValue({
      items: [{
        id: 204,
        table_name: 'fixture_stock_history',
        table_comment: null,
        category: null,
        script_id: null,
        row_count: 1,
        last_update_time: null,
        last_update_status: null,
        data_start_date: '2026-10-26',
        data_end_date: '2026-10-26',
        symbol_raw: '000001',
        symbol_normalized: '000001',
        market: 'CN',
        asset_type: 'stock',
        metadata: {},
        created_at: '2026-10-27T00:00:00Z',
        updated_at: '2026-10-27T00:00:00Z',
      }],
    })

    await page.get('[data-test="market-instrument-query"]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(vm.result?.symbol).toBe('000001')
    expect(vm.relatedTables).toHaveLength(1)

    apiMocks.listInstrumentOptions.mockRejectedValueOnce({
      response: {
        status: 503,
        data: {
          message: 'RAW_UPSTREAM_SECRET_SENTINEL',
          detail: { code: 'OPENDATA_REFERENCE_UNAVAILABLE', catalog_mode: 'opendata' },
        },
      },
    })
    await vm.loadInstrumentOptions('000001')

    expect(vm.instrumentOptions).toEqual([])
    expect(vm.result).toBeNull()
    expect(vm.referenceSeriesResult).toBeNull()
    expect(vm.genericObservationResult).toBeNull()
    expect(vm.relatedTables).toEqual([])
    expect(vm.instrumentOptionsError).not.toContain('RAW_UPSTREAM_SECRET_SENTINEL')
  })

  it('fails closed on an initial stock catalog timeout without inventing a legacy selector item', async () => {
    apiMocks.listInstrumentOptions.mockRejectedValueOnce(new Error('RAW_TIMEOUT_SENTINEL'))

    const page = await mountPage()
    const vm = page.vm as any

    expect(vm.instrumentOptionsCatalogMode).toBeNull()
    expect(vm.instrumentOptions).toEqual([])
    expect(vm.instrumentOptionsError).toBeTruthy()
    expect(vm.instrumentOptionsError).not.toContain('RAW_TIMEOUT_SENTINEL')
    expect(apiMocks.lookupInstrument).not.toHaveBeenCalled()
    expect(page.get('[data-test="market-instrument-select"]').attributes('data-allow-create')).toBe('false')
  })

  it.each([
    {
      name: 'permission denial',
      error: {
        response: {
          status: 403,
          data: { detail: { code: 'ACCESS_DENIED', catalog_mode: 'opendata' } },
        },
      },
    },
    {
      name: 'rate limit',
      error: {
        response: {
          status: 429,
          data: { detail: { code: 'RATE_LIMITED', catalog_mode: 'opendata' } },
        },
      },
    },
    {
      name: 'service outage',
      error: {
        response: {
          status: 503,
          data: { detail: { code: 'OPENDATA_REFERENCE_UNAVAILABLE', catalog_mode: 'opendata' } },
        },
      },
    },
    {
      name: 'invalid OpenData request',
      error: {
        response: {
          status: 422,
          data: { detail: { code: 'OPENDATA_REFERENCE_REQUEST_INVALID', catalog_mode: 'opendata' } },
        },
      },
    },
  ])('clears OpenData options after $name without echoing server codes', async ({ error }) => {
    const page = await mountPage()
    const vm = page.vm as any
    apiMocks.listInstrumentOptions.mockRejectedValueOnce(error)

    await vm.loadInstrumentOptions('600001')

    expect(vm.instrumentOptions).toEqual([])
    expect(vm.instrumentOptionsCatalogMode).toBe('opendata')
    expect(vm.instrumentOptionsError).toBeTruthy()
    expect(vm.instrumentOptionsError).not.toContain('ACCESS_DENIED')
    expect(vm.instrumentOptionsError).not.toContain('RATE_LIMITED')
    expect(vm.instrumentOptionsError).not.toContain('OPENDATA_REFERENCE_')
    expect(page.get('[data-test="market-instrument-select"]').attributes('data-allow-create')).toBe('false')
  })

  it('keeps legacy responses without catalog_mode compatible and ignores stale option responses', async () => {
    const page = await mountPage()
    const vm = page.vm as any
    apiMocks.listInstrumentOptions.mockResolvedValueOnce({
      asset_type: 'stock',
      total: 1,
      items: [{
        asset_type: 'stock',
        symbol: '000001',
        name: 'Legacy instrument',
        has_snapshot: true,
        has_history: false,
        history_rows: 0,
      }],
    })
    vm.form.symbol = 'CUSTOM'
    await vm.loadInstrumentOptions('CUSTOM')

    expect(vm.instrumentOptionsCatalogMode).toBe('legacy')
    expect(vm.instrumentOptions.map((item: { symbol: string }) => item.symbol)).toEqual(['CUSTOM', '000001'])
    expect(page.get('[data-test="market-instrument-select"]').attributes('data-allow-create')).toBe('true')
    expect(vm.formatInstrumentHistoryStatus(vm.instrumentOptions[0])).toBe('0')

    let resolveStale: ((response: MarketInstrumentOptionsResponse) => void) | undefined
    apiMocks.listInstrumentOptions
      .mockImplementationOnce(() => new Promise((resolve) => { resolveStale = resolve }))
      .mockResolvedValueOnce({
        ...openDataOptions(),
        items: [openDataOptions().items[1]],
      })
    const staleRequest = vm.loadInstrumentOptions('old')
    const currentRequest = vm.loadInstrumentOptions('new')
    await currentRequest
    resolveStale?.({
      asset_type: 'stock',
      total: 1,
      items: [{
        asset_type: 'stock',
        symbol: 'STALE',
        name: 'Stale legacy item',
        has_snapshot: false,
        has_history: false,
        history_rows: 0,
      }],
    })
    await staleRequest

    expect(vm.instrumentOptions.map((item: { symbol: string }) => item.symbol)).toEqual(['600001'])
    expect(vm.instrumentOptionsCatalogMode).toBe('opendata')
  })
})
