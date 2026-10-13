import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import type { DatabaseSyncInfo, SyncConfig, SyncConnectionStatus, SyncTaskStatus } from '@/types'
import { elStubs } from '@/test/stubs'

const configFixture: SyncConfig = {
  connection_mode: 'direct_mysql',
  local_mysql_host: '127.0.0.1',
  local_mysql_port: 3306,
  local_mysql_user: 'root',
  local_mysql_password: 'local-secret',
  sync_parallel_workers: 4,
  remote_host: '',
  remote_user: 'root',
  remote_ssh_key: '~/.ssh/id_rsa',
  remote_container: 'backtrader_mysql',
  remote_install_dir: '/opt/ai-for-investor',
  remote_mysql_host: '10.0.0.2',
  remote_mysql_port: 3306,
  remote_mysql_user: 'remote',
  remote_mysql_password: 'remote-secret',
  sync_databases: ['ai_for_investor', 'akshare_data'],
}

const databaseRows: DatabaseSyncInfo[] = [
  {
    name: 'ai_for_investor',
    local: { name: 'ai_for_investor', size_bytes: 1024, size_display: '1 KB', table_count: 12, exists: true },
    remote: { name: 'ai_for_investor', size_bytes: 512, size_display: '512 B', table_count: 10, exists: true },
  },
  {
    name: 'akshare_data',
    local: { name: 'akshare_data', size_bytes: 2048, size_display: '2 KB', table_count: 8, exists: true },
    remote: { name: 'akshare_data', size_bytes: 0, size_display: '0 B', table_count: 0, exists: false },
  },
]

const historyItem: SyncTaskStatus = {
  task_id: 'sync-1',
  status: 'completed',
  direction: 'upload',
  databases: ['ai_for_investor'],
  current_database: null,
  completed_databases: ['ai_for_investor'],
  stage: 'done',
  progress_pct: 100,
  message: 'synced',
  started_at: '2026-07-01T08:00:00Z',
  finished_at: '2026-07-01T08:00:12Z',
  duration_seconds: 12,
  error: null,
  sync_mode: 'full',
}

const connectionStatus: SyncConnectionStatus = {
  success: true,
  checks: {
    local_mysql: true,
    remote_mysql: true,
  },
  details: {
    local_mysql: 'local ok',
    remote_mysql: 'remote ok',
  },
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, unknown>) => {
      if (!params) return key
      return `${key}:${Object.values(params).join('|')}`
    },
  }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

vi.mock('@/api/sync', () => ({
  syncApi: {
    getConfig: vi.fn(),
    saveConfig: vi.fn(),
    testConnection: vi.fn(),
    getDatabases: vi.fn(),
    upload: vi.fn(),
    download: vi.fn(),
    getStatus: vi.fn(),
    getHistory: vi.fn(),
  },
}))

vi.mock('@/api/index', () => ({
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

import { ElMessage, ElMessageBox } from 'element-plus'
import DataSyncPage from '@/views/data/DataSyncPage.vue'
import DataSyncConfigForm from '@/views/data/components/DataSyncConfigForm.vue'
import { syncApi } from '@/api/sync'

const api = syncApi as unknown as Record<string, ReturnType<typeof vi.fn>>

async function flushAll() {
  await flushPromises()
  await new Promise(resolve => setTimeout(resolve, 0))
}

function doMount() {
  return mount(DataSyncPage, { global: { stubs: elStubs } })
}

describe('DataSyncPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.getConfig.mockResolvedValue({ ...configFixture })
    api.saveConfig.mockImplementation(async (payload: SyncConfig) => ({ ...payload }))
    api.testConnection.mockResolvedValue({ ...connectionStatus })
    api.getDatabases.mockResolvedValue({ items: databaseRows.map(row => ({ ...row })) })
    api.getHistory.mockResolvedValue({ items: [{ ...historyItem }] })
    api.upload.mockResolvedValue({ task_id: 'sync-2', status: 'pending', message: 'queued' })
    api.download.mockResolvedValue({ task_id: 'sync-3', status: 'pending', message: 'queued' })
    api.getStatus.mockResolvedValue({
      ...historyItem,
      task_id: 'sync-2',
      databases: ['ai_for_investor'],
    })
  })

  it('loads config, database state and sync history on mount', async () => {
    const wrapper = doMount()
    await flushAll()

    expect(api.getConfig).toHaveBeenCalled()
    expect(api.getDatabases).toHaveBeenCalled()
    expect(api.getHistory).toHaveBeenCalled()
    expect(wrapper.find('[data-test="sync-hero"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="sync-metrics"]').findAll('.sync-metric')).toHaveLength(4)
    expect(wrapper.find('[data-test="sync-config-panel"]').exists()).toBe(true)
    expect(wrapper.findComponent(DataSyncConfigForm).exists()).toBe(true)
    expect(wrapper.find('[data-test="sync-database-grid"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="sync-history-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="sync-history-table"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('ai_for_investor')
    expect(wrapper.text()).toContain('dataPages.syncConfigTitle')
  })

  it('saves config before testing connection and renders check results', async () => {
    const wrapper = doMount()
    await flushAll()

    await (wrapper.vm as unknown as { handleTestConnection: () => Promise<void> }).handleTestConnection()
    await flushAll()

    expect(api.saveConfig).toHaveBeenCalledWith(expect.objectContaining({
      connection_mode: 'direct_mysql',
      sync_databases: ['ai_for_investor', 'akshare_data'],
    }))
    expect(api.testConnection).toHaveBeenCalledWith(expect.objectContaining({
      remote_mysql_host: '10.0.0.2',
    }))
    expect(wrapper.find('[data-test="sync-connection-grid"]').exists()).toBe(true)
    expect(ElMessage.success).toHaveBeenCalledWith('dataPages.syncTestPassed')
  })

  it('starts an upload task and refreshes state after completion', async () => {
    const wrapper = doMount()
    await flushAll()

    await (wrapper.vm as unknown as {
      startSync: (direction: 'upload', databases: string[]) => Promise<void>
    }).startSync('upload', ['ai_for_investor'])
    await flushAll()

    expect(ElMessageBox.confirm).toHaveBeenCalled()
    expect(api.upload).toHaveBeenCalledWith({
      databases: ['ai_for_investor'],
      confirm: true,
      compress: true,
      sync_mode: 'full',
    })
    expect(api.getStatus).toHaveBeenCalledWith('sync-2')
    expect(api.getDatabases).toHaveBeenCalledTimes(2)
    expect(api.getHistory).toHaveBeenCalledTimes(2)
  })

  it('shows partial connection results and resets the connection loading state', async () => {
    const wrapper = doMount()
    await flushAll()
    api.testConnection.mockResolvedValueOnce({
      ...connectionStatus,
      success: false,
      checks: { local_mysql: true, remote_mysql: false },
      details: { local_mysql: 'local ok', remote_mysql: 'remote unavailable' },
    })

    await (wrapper.vm as any).handleTestConnection()

    expect((wrapper.vm as any).connectionStatus.success).toBe(false)
    expect((wrapper.vm as any).connectionSummary).toBe('dataPages.syncConnectionIssue')
    expect((wrapper.vm as any).testingConnection).toBe(false)
    expect(ElMessage.success).toHaveBeenCalledWith('dataPages.syncTestPartial')
  })

  it('clears connection loading and reports a failed connection test', async () => {
    const wrapper = doMount()
    await flushAll()
    api.testConnection.mockRejectedValueOnce(new Error('connection refused'))

    await (wrapper.vm as any).handleTestConnection()

    expect((wrapper.vm as any).testingConnection).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.syncTestFailed')
  })

  it('skips empty or canceled sync requests and clears upload loading after API failure', async () => {
    const wrapper = doMount()
    await flushAll()
    const vm = wrapper.vm as any
    await vm.startSync('upload', [])
    expect(ElMessage.warning).toHaveBeenCalledWith('dataPages.syncNoDatabases')
    expect(api.upload).not.toHaveBeenCalled()

    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    await vm.startSync('upload', ['ai_for_investor'])
    expect(api.upload).not.toHaveBeenCalled()

    vi.mocked(ElMessageBox.confirm).mockResolvedValueOnce(
      'confirm' as unknown as Awaited<ReturnType<typeof ElMessageBox.confirm>>
    )
    api.upload.mockRejectedValueOnce(new Error('remote unavailable'))
    await vm.startSync('upload', ['ai_for_investor'])
    expect(api.upload).toHaveBeenCalledWith({
      databases: ['ai_for_investor'],
      confirm: true,
      compress: true,
      sync_mode: 'full',
    })
    expect(vm.submittingBulkUpload).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.syncStartFailed')
  })

  it('starts a download and surfaces the terminal task failure after refreshing state', async () => {
    const wrapper = doMount()
    await flushAll()
    api.download.mockResolvedValueOnce({ task_id: 'sync-failed', status: 'pending', message: 'queued' })
    api.getStatus.mockResolvedValueOnce({
      ...historyItem,
      task_id: 'sync-failed',
      direction: 'download',
      status: 'failed',
      error: 'remote disk full',
    })

    await (wrapper.vm as any).startSync('download', ['akshare_data'])
    await flushAll()

    expect(api.download).toHaveBeenCalledWith({
      databases: ['akshare_data'],
      confirm: true,
      compress: true,
      sync_mode: 'full',
    })
    expect(api.getStatus).toHaveBeenCalledWith('sync-failed')
    expect((wrapper.vm as any).submittingBulkDownload).toBe(false)
    expect((wrapper.vm as any).activeTaskMap['sync-failed'].status).toBe('failed')
    expect(api.getDatabases).toHaveBeenCalledTimes(2)
    expect(api.getHistory).toHaveBeenCalledTimes(2)
    expect(ElMessage.error).toHaveBeenCalledWith('remote disk full')
  })

  it('renders partial history fields and clears history loading after refresh', async () => {
    const wrapper = doMount()
    await flushAll()
    api.getHistory.mockResolvedValueOnce({
      items: [{
        ...historyItem,
        task_id: 'sync-error',
        direction: 'download',
        status: 'failed',
        started_at: null,
        duration_seconds: null,
        error: 'remote disk full',
        message: '',
      }],
    })

    await (wrapper.vm as any).loadHistory()
    await flushPromises()

    expect((wrapper.vm as any).loadingHistory).toBe(false)
    expect(wrapper.find('[data-test="sync-history-mobile-list"]').text()).toContain('remote disk full')
  })

  it('formats sync states and normalizes database configuration inputs', async () => {
    const vm = doMount().vm as any
    await flushAll()

    expect(vm.formatDateTime(null)).toBe('-')
    expect(vm.formatDuration(null)).toBe('-')
    expect(vm.formatDuration(Number.NaN)).toBe('-')
    expect(vm.formatDuration(30)).toBe('30.0s')
    expect(vm.formatDuration(61)).toBe('1m1s')
    expect(vm.statusLabel('pending')).toBe('dataPages.syncStatusPending')
    expect(vm.statusLabel('running')).toBe('dataPages.syncStatusRunning')
    expect(vm.statusLabel('completed')).toBe('dataPages.syncStatusCompleted')
    expect(vm.statusLabel('failed')).toBe('dataPages.syncStatusFailed')
    expect(vm.syncModeLabel('schema_only')).toBe('dataPages.syncModeSchemaOnly')
    expect(vm.syncModeLabel('data_only')).toBe('dataPages.syncModeDataOnly')
    expect(vm.syncModeLabel('full')).toBe('dataPages.syncModeFull')
    expect(vm.labelForCheck('local_tools')).toBe('dataPages.syncCheckLocalTools')
    expect(vm.labelForCheck('ssh')).toBe('dataPages.syncCheckSsh')
    expect(vm.labelForCheck('docker')).toBe('dataPages.syncCheckDocker')
    expect(vm.labelForCheck('remote_env')).toBe('dataPages.syncCheckRemoteEnv')
    expect(vm.labelForCheck('unrecognized')).toBe('unrecognized')
    expect(vm.formatRemoteState(databaseRows[0])).toContain('512 B')
    expect(vm.formatRemoteState(databaseRows[1])).toBe('dataPages.syncStateNotExists')
    expect(vm.formatLocalState(databaseRows[0])).toContain('1 KB')
    expect(vm.formatLocalState(databaseRows[1])).toContain('2 KB')

    vm.syncDatabasesInput = ' ai_for_investor, ,akshare_data\ncustom_db，'
    expect(vm.buildConfigPayload().sync_databases).toEqual([
      'ai_for_investor',
      'akshare_data',
      'custom_db',
    ])
  })

  it('saves configuration with refreshed databases and handles save failure', async () => {
    const wrapper = doMount()
    await flushAll()
    const vm = wrapper.vm as any

    await vm.handleSaveConfig()
    expect(api.saveConfig).toHaveBeenCalledWith(expect.objectContaining({
      connection_mode: 'direct_mysql',
      sync_databases: ['ai_for_investor', 'akshare_data'],
    }))
    expect(api.getDatabases).toHaveBeenCalledTimes(2)
    expect(vm.savingConfig).toBe(false)
    expect(ElMessage.success).toHaveBeenCalledWith('dataPages.syncSavedSuccess')

    api.saveConfig.mockRejectedValueOnce(new Error('write failed'))
    await vm.handleSaveConfig()
    expect(vm.savingConfig).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith('dataPages.syncSaveFailed')
  })
})
