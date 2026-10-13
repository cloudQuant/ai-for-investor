import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { DataInterface } from '@/types'

const interfaceFixture = vi.hoisted((): DataInterface => ({
  id: 1,
  name: 'stock_zh_a_hist',
  display_name: 'A 股历史行情',
  description: '沪深京 A 股日频历史行情接口',
  category_id: 1,
  module_path: 'akshare',
  function_name: 'stock_zh_a_hist',
  parameters: {
    symbol: { type: 'string', required: true },
    period: { type: 'string', default: 'daily' },
  },
  extra_config: { throttle_ms: 500 },
  return_type: 'DataFrame',
  example: 'ak.stock_zh_a_hist(symbol="000001")',
  is_active: true,
  created_at: '2026-07-01T08:00:00Z',
  updated_at: '2026-07-01T09:00:00Z',
  params: [
    {
      id: 1,
      name: 'symbol',
      display_name: '股票代码',
      param_type: 'string',
      description: '证券代码',
      default_value: null,
      required: true,
      options: null,
      sort_order: 1,
    },
    {
      id: 2,
      name: 'period',
      display_name: '周期',
      param_type: 'string',
      description: '行情周期',
      default_value: 'daily',
      required: false,
      options: ['daily', 'weekly'],
      sort_order: 2,
    },
  ],
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string, params?: Record<string, unknown>) => (params?.count !== undefined ? `${k}:${params.count}` : k) }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

vi.mock('@/api/akshare', () => ({
  akshareInterfacesApi: {
    getCategories: vi.fn().mockResolvedValue([
      { id: 1, name: 'stock', description: '股票' },
      { id: 2, name: 'future', description: '' },
    ]),
    list: vi.fn().mockResolvedValue({ items: [interfaceFixture], total: 1 }),
    create: vi.fn().mockResolvedValue({ id: 1 }),
    update: vi.fn().mockResolvedValue({ id: 1 }),
    delete: vi.fn().mockResolvedValue(undefined),
    bootstrap: vi.fn().mockResolvedValue({ created: 2, updated: 1 }),
    getDetail: vi.fn().mockResolvedValue(interfaceFixture),
  },
}))

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => authState,
}))

const authState = vi.hoisted(() => ({ user: { is_admin: true } }))

import DataInterfacesPage from '@/views/data/DataInterfacesPage.vue'
import { akshareInterfacesApi } from '@/api/akshare'
import { ElMessage, ElMessageBox } from 'element-plus'
import { elStubs } from '@/test/stubs'

const api = akshareInterfacesApi as unknown as Record<string, ReturnType<typeof vi.fn>>

function doMount() {
  return mount(DataInterfacesPage, { global: { stubs: elStubs } })
}

describe('DataInterfacesPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    authState.user.is_admin = true
    api.getCategories.mockResolvedValue([
      { id: 1, name: 'stock', description: '股票' },
      { id: 2, name: 'future', description: '' },
    ])
    api.list.mockResolvedValue({ items: [{ ...interfaceFixture }], total: 1 })
    api.getDetail.mockResolvedValue({ ...interfaceFixture })
  })

  it('loads categories and interfaces on mount', async () => {
    doMount()
    await flushPromises()
    expect(api.getCategories).toHaveBeenCalled()
    expect(api.list).toHaveBeenCalled()
  })

  it('renders the redesigned interface registry workbench', async () => {
    const wrapper = doMount()
    await flushPromises()

    expect(wrapper.find('[data-test="interfaces-hero"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="interfaces-metrics"]').findAll('.interfaces-metric')).toHaveLength(4)
    expect(wrapper.find('[data-test="interfaces-workbench"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="interfaces-table"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="interfaces-mobile-list"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('A 股历史行情')
    expect(wrapper.text()).toContain('stock_zh_a_hist')
    expect(wrapper.text()).toContain('ifWorkbenchTitle')
  })

  it('isAdmin reflects the auth store', () => {
    expect((doMount().vm as any).isAdmin).toBe(true)
  })

  it('categoryNameMap maps id to description or name', async () => {
    const vm = doMount().vm as any
    await flushPromises()
    expect(vm.categoryNameMap[1]).toBe('股票')
    expect(vm.categoryNameMap[2]).toBe('future') // empty description falls back to name
  })

  it('resetForm restores defaults', () => {
    const vm = doMount().vm as any
    vm.form.name = 'dirty'
    vm.parametersText = '{"a":1}'
    vm.resetForm()
    expect(vm.form.name).toBe('')
    expect(vm.form.module_path).toBe('akshare')
    expect(vm.parametersText).toBe('{}')
  })

  it('openCreateDialog opens in create mode with a fresh form', () => {
    const vm = doMount().vm as any
    vm.openCreateDialog()
    expect(vm.dialogVisible).toBe(true)
    expect(vm.editingInterfaceId).toBeNull()
  })

  it('bootstrapInterfaces invokes the bootstrap API', async () => {
    const vm = doMount().vm as any
    await vm.bootstrapInterfaces()
    expect(api.bootstrap).toHaveBeenCalledWith(true)
  })

  it('openDetail fetches the interface detail', async () => {
    const vm = doMount().vm as any
    await vm.openDetail(1)
    expect(api.getDetail).toHaveBeenCalledWith(1)
    expect(vm.currentInterface?.id).toBe(1)
    expect(vm.currentInterface?.params).toHaveLength(2)
  })

  it('deleteInterface confirms and deletes', async () => {
    const vm = doMount().vm as any
    await vm.deleteInterface(7)
    expect(api.delete).toHaveBeenCalledWith(7)
  })

  it('filters interfaces, resets pagination, and displays an empty state', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.page = 2
    vm.categoryId = 2
    vm.search = 'fund flow'
    vm.activeFilter = 'active'
    api.list.mockResolvedValueOnce({ items: [], total: 0 })

    await vm.loadInterfaces()

    expect(api.list).toHaveBeenLastCalledWith({
      page: 2,
      page_size: 20,
      category_id: 2,
      search: 'fund flow',
      is_active: true,
    })
    expect(vm.interfaces).toEqual([])
    expect(vm.total).toBe(0)
    expect(vm.loading).toBe(false)
    expect(wrapper.find('.interfaces-empty').exists()).toBe(true)

    vm.page = 5
    vm.pageSize = 50
    vm.handleSizeChange()
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
  })

  it('rejects an incomplete create form before making an API request', async () => {
    const vm = doMount().vm as any
    await vm.submitForm()

    expect(api.create).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('dataPages.ifValidationFill')
    expect(vm.saving).toBe(false)
  })

  it('updates an edited interface with parsed JSON and trimmed fields', async () => {
    const vm = doMount().vm as any
    await flushPromises()
    vm.openEditDialog({ ...interfaceFixture })
    vm.form.display_name = '  Updated label  '
    vm.form.description = '   '
    vm.parametersText = '{"symbol":{"required":true}}'
    vm.extraConfigText = '{"throttle_ms":250}'

    await vm.submitForm()

    expect(api.update).toHaveBeenCalledWith(1, expect.objectContaining({
      display_name: 'Updated label',
      description: null,
      parameters: { symbol: { required: true } },
      extra_config: { throttle_ms: 250 },
    }))
    expect(vm.dialogVisible).toBe(false)
    expect(vm.saving).toBe(false)
  })

  it('resets loading after list failure and reports the error', async () => {
    const wrapper = doMount()
    await flushPromises()
    api.list.mockRejectedValueOnce(new Error('service unavailable'))

    await (wrapper.vm as any).loadInterfaces()

    expect((wrapper.vm as any).loading).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.ifLoadFailed')
  })

  it('does not delete an interface when confirmation is canceled', async () => {
    const vm = doMount().vm as any
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    await vm.deleteInterface(7)

    expect(api.delete).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('keeps interface data visible but hides edit and delete actions for non-admins', async () => {
    authState.user.is_admin = false
    const wrapper = doMount()
    await flushPromises()

    expect((wrapper.vm as any).isAdmin).toBe(false)
    expect(wrapper.text()).toContain('A 股历史行情')
    expect(wrapper.text()).not.toContain('dataPages.ifActionEdit')
    expect(wrapper.text()).not.toContain('dataPages.ifActionDelete')
  })

  it('renders fallbacks for interfaces with optional metadata missing', async () => {
    api.list.mockResolvedValueOnce({
      items: [{
        ...interfaceFixture,
        description: '',
        module_path: '',
        function_name: '',
        params: [],
        parameters: { symbol: { type: 'string' } },
        updated_at: null,
        is_active: false,
      }],
      total: 1,
    })
    const wrapper = doMount()
    await flushPromises()

    expect((wrapper.vm as any).visibleParamCount).toBe(1)
    expect(wrapper.text()).toContain('dataPages.ifNoDescription')
    expect(wrapper.text()).toContain('dataPages.ifStatusInactive')
    expect(wrapper.text()).toContain('stock_zh_a_hist')
  })
})
