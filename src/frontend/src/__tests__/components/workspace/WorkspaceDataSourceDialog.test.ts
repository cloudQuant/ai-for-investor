import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import type { Workspace } from '@/types/workspace'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const workspaceMocks = vi.hoisted(() => ({
  updateWorkspace: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => workspaceMocks,
}))

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

import WorkspaceDataSourceDialog from '@/components/workspace/WorkspaceDataSourceDialog.vue'
import { ElMessage } from 'element-plus'
import { elStubs } from '@/test/stubs'

function mountDialog(workspace: Workspace | null = null) {
  return mount(WorkspaceDataSourceDialog, {
    props: { modelValue: true, workspaceId: 'ws-1', workspace },
    global: { stubs: elStubs },
  })
}

describe('WorkspaceDataSourceDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders the selected form for each supported data source', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm as any

    for (const [type, expectedInputCount] of [
      ['csv', 3],
      ['mysql', 5],
      ['postgresql', 6],
      ['mongodb', 6],
    ] as const) {
      vm.form.type = type
      await nextTick()
      expect(wrapper.findAll('input.el-input')).toHaveLength(expectedInputCount)
    }
  })

  it('fills defaults and migrates a legacy CSV file_path while merging partial settings', () => {
    const wrapper = mountDialog({
      settings: {
        data_source: {
          type: 'csv',
          csv: { file_path: '/legacy/market-data', delimiter: ';' },
          mysql: { host: 'db.internal' },
        },
      },
    } as unknown as Workspace)
    const vm = wrapper.vm as any

    vm.initForm()

    expect(vm.form.type).toBe('csv')
    expect(vm.form.csv).toMatchObject({
      directory_path: '/legacy/market-data',
      delimiter: ';',
      encoding: 'utf-8',
      has_header: true,
    })
    expect(vm.form.mysql).toMatchObject({ host: 'db.internal', port: 3306, database: '' })
    expect(vm.form.postgresql).toMatchObject({ host: '127.0.0.1', port: 5432, schema: 'public' })
    expect(vm.form.mongodb).toMatchObject({ uri: 'mongodb://127.0.0.1:27017', auth_source: 'admin' })
  })

  it('persists a cloned data source, closes the dialog, and emits saved', async () => {
    const wrapper = mountDialog()
    const vm = wrapper.vm as any
    vm.form.type = 'postgresql'
    vm.form.postgresql.host = 'postgres.internal'
    vm.form.postgresql.database = 'market'

    await vm.handleSave()

    expect(workspaceMocks.updateWorkspace).toHaveBeenCalledWith('ws-1', {
      settings: { data_source: expect.objectContaining({
        type: 'postgresql',
        postgresql: expect.objectContaining({ host: 'postgres.internal', database: 'market' }),
      }) },
    })
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    expect(wrapper.emitted('saved')).toEqual([[]])
    expect(ElMessage.success).toHaveBeenCalledWith('workspaceDialogs.wsDataSourceSaved')
    expect(vm.saving).toBe(false)
  })

  it('keeps the dialog open and reports a save failure', async () => {
    workspaceMocks.updateWorkspace.mockRejectedValueOnce(new Error('database unavailable'))
    const wrapper = mountDialog()
    const vm = wrapper.vm as any

    await vm.handleSave()

    expect(workspaceMocks.updateWorkspace).toHaveBeenCalledWith('ws-1', {
      settings: { data_source: expect.objectContaining({ type: 'csv' }) },
    })
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    expect(wrapper.emitted('saved')).toBeUndefined()
    expect(ElMessage.error).toHaveBeenCalledWith('workspaceDialogs.dataSourceSaveFailed')
    expect(vm.saving).toBe(false)
  })
})
