import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const routerMock = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, params: {}, path: '/config/data/tasks' }),
  useRouter: () => routerMock,
}))

vi.mock('@/api/akshare', () => ({
  akshareScriptsApi: {
    list: vi.fn().mockResolvedValue({
      items: [{ script_id: 's-1', script_name: 'Alpha' }],
      total: 1,
    }),
  },
  akshareTasksApi: {
    list: vi.fn().mockResolvedValue({
      items: [
        {
          id: 3,
          name: 'Daily stock sync',
          description: 'Refresh daily stock bars',
          user_id: 'admin',
          script_id: 's-1',
          schedule_type: 'cron',
          schedule_expression: '0 8 * * 1-5',
          parameters: {},
          is_active: true,
          retry_on_failure: true,
          max_retries: 3,
          timeout: 300,
          last_execution_at: '2026-07-01T08:00:00Z',
          next_execution_at: '2026-07-02T08:00:00Z',
          created_at: '2026-06-30T08:00:00Z',
          updated_at: '2026-07-01T08:00:00Z',
        },
      ],
      total: 1,
    }),
    getScheduleTemplates: vi.fn().mockResolvedValue({
      templates: [{ value: 'every_day', label: 'Daily', cron_expression: '0 8 * * *' }],
    }),
    create: vi.fn().mockResolvedValue({ id: 1 }),
    update: vi.fn().mockResolvedValue({ id: 1 }),
    delete: vi.fn().mockResolvedValue(undefined),
    run: vi.fn().mockResolvedValue({ execution_id: 'e-1' }),
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

import DataTasksPage from '@/views/data/DataTasksPage.vue'
import { akshareTasksApi } from '@/api/akshare'
import { ElMessage, ElMessageBox } from 'element-plus'
import { elStubs } from '@/test/stubs'

const tasksApi = akshareTasksApi as unknown as Record<string, ReturnType<typeof vi.fn>>

function doMount() {
  return mount(DataTasksPage, { global: { stubs: elStubs } })
}

describe('DataTasksPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    authState.user.is_admin = true
  })

  it('loads scripts, templates and tasks on mount', async () => {
    doMount()
    await new Promise(r => setTimeout(r, 0))
    expect(tasksApi.list).toHaveBeenCalled()
    expect(tasksApi.getScheduleTemplates).toHaveBeenCalled()
  })

  it('renders the redesigned schedule governance workbench', async () => {
    const wrapper = doMount()
    await new Promise(r => setTimeout(r, 0))
    expect(wrapper.find('[data-test="tasks-hero"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="tasks-metrics"]').findAll('.tasks-metric')).toHaveLength(4)
    expect(wrapper.find('[data-test="tasks-workbench"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="tasks-table"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('tasksWorkbenchTitle')
    expect(wrapper.text()).toContain('Daily stock sync')
  })

  it('isAdmin reflects the auth store', () => {
    expect((doMount().vm as any).isAdmin).toBe(true)
  })

  it('scriptNameMap maps script_id to script_name', async () => {
    const vm = doMount().vm as any
    await new Promise(r => setTimeout(r, 0))
    expect(vm.scriptNameMap['s-1']).toBe('Alpha')
  })

  it('resetForm restores defaults', () => {
    const vm = doMount().vm as any
    vm.form.name = 'dirty'
    vm.paramsText = '{"a":1}'
    vm.resetForm()
    expect(vm.form.name).toBe('')
    expect(vm.form.schedule_type).toBe('cron')
    expect(vm.paramsText).toBe('{}')
  })

  it('handleTemplateChange applies the chosen template schedule', async () => {
    const vm = doMount().vm as any
    await new Promise(r => setTimeout(r, 0))
    vm.handleTemplateChange('every_day')
    expect(vm.form.schedule_type).toBe('cron')
    expect(vm.form.schedule_expression).toBe('0 8 * * *')
  })

  it('openCreateDialog opens in create mode', () => {
    const vm = doMount().vm as any
    vm.openCreateDialog()
    expect(vm.dialogVisible).toBe(true)
    expect(vm.editingTaskId).toBeNull()
  })

  it('runTask invokes the run API', async () => {
    const vm = doMount().vm as any
    await vm.runTask(3)
    expect(tasksApi.run).toHaveBeenCalledWith(3)
    expect(routerMock.push).toHaveBeenCalledWith({
      name: 'ConfigDataExecutions',
      query: { task_id: '3' },
    })
  })

  it('toggleTask invokes the toggle API', async () => {
    const vm = doMount().vm as any
    await vm.toggleTask(3)
    expect(tasksApi.toggle).toHaveBeenCalledWith(3)
  })

  it('deleteTask confirms and deletes', async () => {
    const vm = doMount().vm as any
    await vm.deleteTask(9)
    expect(tasksApi.delete).toHaveBeenCalledWith(9)
  })

  it('applies the active filter, resets pagination, and renders no tasks', async () => {
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.page = 2
    vm.activeFilter = 'inactive'
    tasksApi.list.mockResolvedValueOnce({ items: [], total: 0 })

    await vm.loadTasks()

    expect(tasksApi.list).toHaveBeenLastCalledWith({ page: 2, page_size: 20, is_active: false })
    expect(vm.tasks).toEqual([])
    expect(vm.total).toBe(0)
    expect(vm.loading).toBe(false)
    expect(wrapper.find('.tasks-empty').exists()).toBe(true)

    vm.page = 4
    vm.pageSize = 50
    vm.handleSizeChange()
    await flushPromises()
    expect(tasksApi.list).toHaveBeenLastCalledWith(expect.objectContaining({ page: 1, page_size: 50 }))
  })

  it('validates a new task and submits its normalized parameters', async () => {
    const vm = doMount().vm as any
    await flushPromises()
    vm.openCreateDialog()
    await vm.submitForm()
    expect(tasksApi.create).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith('dataPages.tasksValidationFill')

    vm.form.name = '  Nightly import  '
    vm.form.script_id = 's-1'
    vm.form.description = '  refresh bars  '
    vm.paramsText = '{"symbol":"RB2510"}'
    await vm.submitForm()

    expect(tasksApi.create).toHaveBeenCalledWith(expect.objectContaining({
      name: 'Nightly import',
      script_id: 's-1',
      description: 'refresh bars',
      parameters: { symbol: 'RB2510' },
    }))
    expect(vm.dialogVisible).toBe(false)
    expect(vm.saving).toBe(false)
  })

  it('keeps an edited task open when saving fails and clears the saving state', async () => {
    const vm = doMount().vm as any
    await flushPromises()
    vm.openEditDialog({
      id: 3,
      name: 'Before',
      script_id: 's-1',
      description: null,
      schedule_type: 'cron',
      schedule_expression: '0 8 * * 1-5',
      parameters: { symbol: 'old' },
      is_active: true,
      retry_on_failure: true,
      max_retries: 3,
      timeout: 0,
    })
    vm.form.name = 'After'
    tasksApi.update.mockRejectedValueOnce(new Error('write failed'))

    await vm.submitForm()

    expect(tasksApi.update).toHaveBeenCalledWith(3, expect.objectContaining({ name: 'After' }))
    expect(vm.dialogVisible).toBe(true)
    expect(vm.saving).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.tasksSaveFailed')
  })

  it('does not delete a task when the confirmation dialog is canceled', async () => {
    const vm = doMount().vm as any
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    await vm.deleteTask(9)

    expect(tasksApi.delete).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('shows scheduled tasks without exposing admin actions to non-admins', async () => {
    authState.user.is_admin = false
    tasksApi.list.mockResolvedValueOnce({
      items: [{
        id: 4,
        name: 'Read-only schedule',
        description: '',
        script_id: 'missing-script',
        schedule_type: 'once',
        schedule_expression: '2026-10-14T09:00:00',
        parameters: {},
        is_active: false,
        retry_on_failure: false,
        max_retries: 0,
        timeout: 0,
        last_execution_at: null,
        next_execution_at: null,
      }],
      total: 1,
    })
    const wrapper = doMount()
    await flushPromises()

    expect((wrapper.vm as any).isAdmin).toBe(false)
    expect(wrapper.text()).toContain('Read-only schedule')
    expect(wrapper.text()).toContain('missing-script')
    expect(wrapper.text()).toContain('dataPages.tasksNoDescription')
    expect(wrapper.text()).toContain('dataPages.tasksStatusInactive')
    expect(wrapper.text()).not.toContain('dataPages.tasksActionRunNow')
    expect(wrapper.text()).not.toContain('dataPages.tasksActionEdit')
  })
})
