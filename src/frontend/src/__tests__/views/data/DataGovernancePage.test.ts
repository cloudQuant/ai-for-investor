import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type {
  DataGovernanceEndpoint,
  DataGovernanceProvider,
  DataPreviewResponse,
} from '@/api/dataGovernance'
import { elStubs } from '@/test/stubs'

const fixtures = vi.hoisted(() => {
  const providers: DataGovernanceProvider[] = [
    {
      id: 'provider-1',
      provider_id: 'akshare',
      name: 'AkShare',
      category: 'market_data',
      auth_type: 'none',
      api_key_env: null,
      rate_limit: 120,
      is_active: true,
    },
    {
      id: 'provider-2',
      provider_id: 'eastmoney',
      name: 'EastMoney',
      category: 'market_data',
      auth_type: 'api_key',
      api_key_env: 'EASTMONEY_KEY',
      rate_limit: 60,
      is_active: false,
    },
  ]

  const endpoints: DataGovernanceEndpoint[] = [
    {
      id: 'endpoint-1',
      provider_id: 'akshare',
      endpoint_name: 'stock_zh_a_hist',
      display_name: 'A 股历史行情',
      category: 'stock',
      function_path: 'akshare.stock_zh_a_hist',
      params_schema: { symbol: { type: 'string', required: true } },
      auth_type: 'none',
      api_key_env: null,
      rate_limit: 100,
      cache_ttl_sec: 300,
      target_database: 'akshare_data',
      target_table: 'stock_zh_a_hist',
      normalization_profile: { mode: 'table' },
      quality_profile: { required_columns: ['date', 'close'] },
      incremental_sync_key: 'date',
      is_active: true,
    },
    {
      id: 'endpoint-2',
      provider_id: 'eastmoney',
      endpoint_name: 'fund_flow',
      display_name: '资金流向',
      category: 'capital_flow',
      function_path: 'eastmoney.fund_flow',
      params_schema: {},
      auth_type: 'api_key',
      api_key_env: 'EASTMONEY_KEY',
      rate_limit: 50,
      cache_ttl_sec: 0,
      target_database: 'market_data',
      target_table: null,
      normalization_profile: {},
      quality_profile: {},
      incremental_sync_key: '',
      is_active: false,
    },
  ]

  const preview: DataPreviewResponse = {
    columns: ['date', 'close'],
    rows: [{ date: '2026-07-01', close: 12.3 }],
    metadata: { source: 'mock' },
    source_timestamp: '2026-07-01T09:00:00Z',
    provider_latency_ms: 42,
    quality_warnings: [],
    provider_id: 'akshare',
    endpoint_name: 'stock_zh_a_hist',
  }

  return { providers, endpoints, preview }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (params?.count !== undefined) return `${key}:${params.count}`
      if (params?.id !== undefined) return `${key}:${params.id}`
      return key
    },
  }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/api/dataGovernance', () => ({
  dataGovernanceApi: {
    bootstrap: vi.fn(),
    listProviders: vi.fn(),
    listEndpoints: vi.fn(),
    previewEndpoint: vi.fn(),
    createJob: vi.fn(),
  },
}))

vi.mock('@/api/index', () => ({
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

import { ElMessage } from 'element-plus'
import DataGovernancePage from '@/views/data/DataGovernancePage.vue'
import { dataGovernanceApi } from '@/api/dataGovernance'

const api = dataGovernanceApi as unknown as Record<string, ReturnType<typeof vi.fn>>

function doMount() {
  return mount(DataGovernancePage, { global: { stubs: elStubs } })
}

describe('DataGovernancePage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.bootstrap.mockResolvedValue({
      providers: 2,
      seed_endpoints: 1,
      akshare_migrated_endpoints: 1,
    })
    api.listProviders.mockResolvedValue({ items: fixtures.providers, total: fixtures.providers.length })
    api.listEndpoints.mockResolvedValue({ items: fixtures.endpoints, total: fixtures.endpoints.length })
    api.previewEndpoint.mockResolvedValue(fixtures.preview)
    api.createJob.mockResolvedValue({
      id: 'job-1',
      endpoint_id: 'endpoint-1',
      status: 'queued',
      row_count: 0,
      created_at: '2026-07-01T09:00:00Z',
    })
  })

  it('bootstraps and loads providers and endpoints on mount', async () => {
    doMount()
    await flushPromises()

    expect(api.bootstrap).toHaveBeenCalled()
    expect(api.listProviders).toHaveBeenCalled()
    expect(api.listEndpoints).toHaveBeenCalledWith(undefined)
  })

  it('renders the redesigned governance workbench', async () => {
    const wrapper = doMount()
    await flushPromises()

    expect(wrapper.find('[data-test="governance-hero"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="governance-metrics"]').findAll('.governance-metric')).toHaveLength(4)
    expect(wrapper.find('[data-test="governance-providers-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="governance-endpoints-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="governance-endpoints-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="governance-mobile-list"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('A 股历史行情')
    expect(wrapper.text()).toContain('AkShare')
    expect(wrapper.text()).toContain('governanceEndpointKicker')
  })

  it('loads endpoints for the selected provider', async () => {
    const vm = doMount().vm as unknown as {
      selectedProviderId: string | undefined
      handleProviderChange: () => Promise<void>
    }
    await flushPromises()

    vm.selectedProviderId = 'akshare'
    await vm.handleProviderChange()

    expect(api.listEndpoints).toHaveBeenLastCalledWith('akshare')
  })

  it('opens endpoint details and runs preview and job actions', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as unknown as {
      openEndpoint: (endpoint: DataGovernanceEndpoint) => void
      previewParamsText: string
      previewEndpoint: () => Promise<void>
      createIngestionJob: () => Promise<void>
      previewResult: DataPreviewResponse | null
    }
    await flushPromises()

    vm.openEndpoint(fixtures.endpoints[0])
    vm.previewParamsText = '{"symbol":"000001"}'
    await vm.previewEndpoint()
    await vm.createIngestionJob()

    expect(api.previewEndpoint).toHaveBeenCalledWith('endpoint-1', { symbol: '000001' })
    expect(api.createJob).toHaveBeenCalledWith('endpoint-1', { symbol: '000001' })
    expect(vm.previewResult?.rows).toHaveLength(1)
    expect(ElMessage.success).toHaveBeenCalledWith('dataPages.governancePreviewLoaded')
    expect(ElMessage.success).toHaveBeenCalledWith('dataPages.governanceJobCreated:job-1')
    expect(wrapper.find('[data-test="governance-preview-result"]').exists()).toBe(true)
  })

  it('filters endpoints case-insensitively across available metadata', async () => {
    const vm = doMount().vm as any
    await flushPromises()

    vm.endpointSearch = '  CAPITAL_FLOW '

    expect(vm.filteredEndpoints.map((item: DataGovernanceEndpoint) => item.id)).toEqual(['endpoint-2'])
    vm.endpointSearch = 'missing'
    expect(vm.filteredEndpoints).toEqual([])
  })

  it('clears loading and reports errors while loading a provider or bootstrapping', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.selectedProviderId = 'akshare'
    api.listEndpoints.mockRejectedValueOnce(new Error('provider endpoint unavailable'))

    await vm.handleProviderChange()

    expect(vm.loading).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.governanceLoadEndpointsFailed')

    api.bootstrap.mockRejectedValueOnce(new Error('bootstrap unavailable'))
    await vm.bootstrapAndLoad()
    expect(vm.loading).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.governanceLoadFailed')
  })

  it('returns without calling preview or job APIs until an endpoint is selected', async () => {
    const vm = doMount().vm as any
    await flushPromises()

    await vm.previewEndpoint()
    await vm.createIngestionJob()

    expect(api.previewEndpoint).not.toHaveBeenCalled()
    expect(api.createJob).not.toHaveBeenCalled()
    expect(vm.previewLoading).toBe(false)
    expect(vm.jobLoading).toBe(false)
  })

  it('reports preview and job failures and resets both action states', async () => {
    const vm = doMount().vm as any
    await flushPromises()
    vm.openEndpoint(fixtures.endpoints[0])
    vm.previewParamsText = '{"symbol":"000001"}'
    api.previewEndpoint.mockRejectedValueOnce(new Error('preview unavailable'))
    api.createJob.mockRejectedValueOnce(new Error('queue unavailable'))

    await vm.previewEndpoint()
    await vm.createIngestionJob()

    expect(api.previewEndpoint).toHaveBeenCalledWith('endpoint-1', { symbol: '000001' })
    expect(api.createJob).toHaveBeenCalledWith('endpoint-1', { symbol: '000001' })
    expect(vm.previewLoading).toBe(false)
    expect(vm.jobLoading).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.governancePreviewFailed')
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.governanceJobFailed')
  })

  it('shows quality warnings returned with a partial preview response', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    await flushPromises()
    vm.openEndpoint(fixtures.endpoints[0])
    api.previewEndpoint.mockResolvedValueOnce({
      ...fixtures.preview,
      quality_warnings: ['missing close value'],
    })

    await vm.previewEndpoint()

    expect(wrapper.find('[data-test="governance-preview-result"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('missing close value')
    expect(vm.previewLoading).toBe(false)
  })

  it('formats missing metadata and toggles a selected provider back to all providers', async () => {
    const vm = doMount().vm as any
    await flushPromises()

    expect(vm.providerLabel('akshare')).toBe('AkShare')
    expect(vm.providerLabel('unknown-provider')).toBe('unknown-provider')
    expect(vm.formatCacheTtl(0)).toBe('dataPages.governanceNoCache')
    expect(vm.formatCacheTtl(30)).toBe('30s')
    expect(vm.formatCacheTtl(300)).toBe('5m')
    expect(vm.formatCacheTtl(3600)).toBe('1h')
    expect(vm.formatDateTime(null)).toBe('-')

    vm.selectProvider('akshare')
    await flushPromises()
    expect(vm.selectedProviderId).toBe('akshare')
    expect(api.listEndpoints).toHaveBeenLastCalledWith('akshare')
    vm.selectProvider('akshare')
    await flushPromises()
    expect(vm.selectedProviderId).toBeUndefined()
    expect(api.listEndpoints).toHaveBeenLastCalledWith(undefined)

    vm.previewResult = fixtures.preview
    vm.openEndpoint(fixtures.endpoints[1])
    expect(vm.currentEndpoint.id).toBe('endpoint-2')
    expect(vm.previewResult).toBeNull()
    expect(vm.previewParamsText).toBe('{}')
  })
})
