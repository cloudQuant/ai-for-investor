import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/api/akshare', () => ({
  akshareScriptsApi: {
    list: vi.fn().mockResolvedValue({ items: [], total: 0 }),
    getCategories: vi.fn().mockResolvedValue(['stock', 'future']),
    getStats: vi.fn().mockResolvedValue({
      total_scripts: 3,
      active_scripts: 2,
      custom_scripts: 1,
      categories: [],
    }),
    create: vi.fn().mockResolvedValue({ script_id: 's-1' }),
    update: vi.fn().mockResolvedValue({ script_id: 's-1' }),
    delete: vi.fn().mockResolvedValue(undefined),
    run: vi.fn().mockResolvedValue({ execution_id: 'e-1' }),
    scan: vi.fn().mockResolvedValue({ created: 1, updated: 0 }),
    toggle: vi.fn().mockResolvedValue(undefined),
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

import DataScriptsPage from '@/views/data/DataScriptsPage.vue'
import { akshareScriptsApi } from '@/api/akshare'
import { ElMessage, ElMessageBox } from 'element-plus'
import { elStubs } from '@/test/stubs'

const api = akshareScriptsApi as unknown as Record<string, ReturnType<typeof vi.fn>>

function doMount() {
  return mount(DataScriptsPage, { global: { stubs: elStubs } })
}

describe('DataScriptsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    authState.user.is_admin = true
  })

  it('loads categories, stats and scripts on mount', async () => {
    doMount()
    await new Promise(r => setTimeout(r, 0))
    expect(api.getCategories).toHaveBeenCalled()
    expect(api.getStats).toHaveBeenCalled()
    expect(api.list).toHaveBeenCalled()
  })

  it('isAdmin reflects the auth store', () => {
    const vm = doMount().vm as any
    expect(vm.isAdmin).toBe(true)
  })

  it('resetForm clears the form back to defaults', () => {
    const vm = doMount().vm as any
    vm.form.script_id = 'dirty'
    vm.form.function_name = 'changed'
    vm.dependenciesText = '{"a":1}'
    vm.resetForm()
    expect(vm.form.script_id).toBe('')
    expect(vm.form.function_name).toBe('main')
    expect(vm.dependenciesText).toBe('{}')
  })

  it('openCreateDialog resets form and opens dialog in create mode', () => {
    const vm = doMount().vm as any
    vm.openCreateDialog()
    expect(vm.dialogVisible).toBe(true)
    expect(vm.dialogMode).toBe('create')
    expect(vm.form.script_id).toBe('')
  })

  it('openEditDialog loads the script into the form in edit mode', () => {
    const vm = doMount().vm as any
    vm.openEditDialog({
      script_id: 's-9',
      script_name: 'Nine',
      category: 'stock',
      frequency: 'daily',
      function_name: 'run',
      dependencies: {},
    })
    expect(vm.dialogVisible).toBe(true)
    expect(vm.dialogMode).toBe('edit')
    expect(vm.form.script_id).toBe('s-9')
  })

  it('handleScan invokes the scan API', async () => {
    const vm = doMount().vm as any
    await vm.handleScan()
    expect(api.scan).toHaveBeenCalled()
  })

  it('runScript invokes the run API', async () => {
    const vm = doMount().vm as any
    await vm.runScript('s-1')
    expect(api.run).toHaveBeenCalledWith('s-1', { parameters: {} })
  })

  it('toggleScript invokes the toggle API', async () => {
    const vm = doMount().vm as any
    await vm.toggleScript('s-1')
    expect(api.toggle).toHaveBeenCalledWith('s-1')
  })

  it('routes secondary script actions through the overflow handler', async () => {
    const vm = doMount().vm as any
    const script = {
      script_id: 's-1',
      script_name: 'One',
      category: 'stock',
      frequency: 'daily',
      is_custom: true,
      is_active: true,
    }
    await vm.handleScriptAction(script, 'run')
    vm.handleScriptAction(script, 'edit')

    expect(api.run).toHaveBeenCalledWith('s-1', { parameters: {} })
    expect(vm.dialogVisible).toBe(true)
    expect(vm.dialogMode).toBe('edit')
  })

  it('sends script filters and pagination and renders an empty result', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.page = 3
    vm.filters.category = 'stock'
    vm.filters.keyword = 'history'
    vm.activeFilter = 'inactive'
    api.list.mockResolvedValueOnce({ items: [], total: 0 })

    await vm.loadScripts()

    expect(api.list).toHaveBeenLastCalledWith({
      page: 3,
      page_size: 20,
      category: 'stock',
      keyword: 'history',
      is_active: false,
    })
    expect(vm.scripts).toEqual([])
    expect(vm.total).toBe(0)
    expect(vm.loading).toBe(false)
    expect(wrapper.find('.scripts-empty').exists()).toBe(true)

    vm.page = 4
    vm.pageSize = 50
    vm.handleSizeChange()
    await flushPromises()
    expect(api.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
  })

  it('shows an empty state and clears loading after a list request fails', async () => {
    api.list.mockRejectedValueOnce(new Error('offline'))
    const wrapper = doMount()
    await flushPromises()

    expect((wrapper.vm as any).loading).toBe(false)
    expect(wrapper.find('.scripts-empty').exists()).toBe(true)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.scriptsLoadFailed')
  })

  it('validates create fields and submits trimmed values with parsed dependencies', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.openCreateDialog()
    await vm.submitForm()
    expect(api.create).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('dataPages.scriptsValidationFill')

    Object.assign(vm.form, {
      script_id: '  custom-script  ',
      script_name: '  Custom script  ',
      category: ' stock ',
      description: '  daily prices  ',
      target_table: ' ',
      module_path: ' akshare.stock ',
    })
    vm.dependenciesText = '{"symbol": "close"}'
    await vm.submitForm()

    expect(api.create).toHaveBeenCalledWith(expect.objectContaining({
      script_id: 'custom-script',
      script_name: 'Custom script',
      category: 'stock',
      description: 'daily prices',
      target_table: null,
      module_path: 'akshare.stock',
      dependencies: { symbol: 'close' },
    }))
    expect(vm.dialogVisible).toBe(false)
    expect(vm.saving).toBe(false)
  })

  it('keeps the edit dialog open and resets saving when update fails', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.openEditDialog({
      script_id: 's-9',
      script_name: 'Before',
      category: 'stock',
      source: 'akshare',
      dependencies: {},
      estimated_duration: 60,
      timeout: 300,
      is_active: true,
    })
    vm.form.script_name = 'After'
    api.update.mockRejectedValueOnce(new Error('write failed'))

    await vm.submitForm()

    expect(api.update).toHaveBeenCalledWith('s-9', expect.any(Object))
    expect((api.update.mock.calls[0][1] as object)).not.toHaveProperty('script_id')
    expect(vm.dialogVisible).toBe(true)
    expect(vm.saving).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.scriptsSaveFailed')
  })

  it('does not delete a script when the confirmation dialog is canceled', async () => {
    const vm = doMount().vm as any
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    await vm.deleteScript({ script_id: 's-1', script_name: 'One' })

    expect(api.delete).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('hides script management actions from non-admin users', async () => {
    authState.user.is_admin = false
    api.list.mockResolvedValueOnce({
      items: [{
        script_id: 'builtin-1',
        script_name: 'Built-in script',
        category: 'stock',
        source: 'akshare',
        is_custom: false,
        is_active: false,
        description: null,
        target_table: null,
        frequency: null,
        updated_at: null,
      }],
      total: 1,
    })
    const wrapper = doMount()
    await flushPromises()

    expect((wrapper.vm as any).isAdmin).toBe(false)
    expect(wrapper.find('.scripts-action-more').exists()).toBe(false)
    expect(wrapper.text()).toContain('Built-in script')
    expect(wrapper.text()).toContain('dataPages.scriptsNoDescription')
    expect(wrapper.text()).toContain('dataPages.scriptsStatusInactive')
  })
})
