import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const tradingMocks = vi.hoisted(() => ({
  units: [] as Array<Record<string, any>>,
  selectedUnitIds: [] as string[],
  running: false,
  startPolling: vi.fn(),
  stopPolling: vi.fn(),
  setSelectedUnitIds: vi.fn(),
  clearSelection: vi.fn(),
  fetchUnits: vi.fn().mockResolvedValue(undefined),
  pollStatus: vi.fn().mockResolvedValue(undefined),
  runSelectedUnits: vi.fn().mockResolvedValue([]),
  stopSelectedUnits: vi.fn().mockResolvedValue(undefined),
  patchUnits: vi.fn().mockResolvedValue(undefined),
  bulkDeleteUnits: vi.fn().mockResolvedValue(undefined),
}))

const tradingApiMocks = vi.hoisted(() => ({
  openUnitRuntimeDir: vi.fn().mockResolvedValue({ message: 'Opened unit folder' }),
}))

const autoTradingMocks = vi.hoisted(() => ({
  loadAutoTradingState: vi.fn().mockResolvedValue(undefined),
  handleEnableAutoTrading: vi.fn(),
  handleDisableAutoTrading: vi.fn(),
  handleAutoTradingSaved: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => tradingMocks,
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: tradingApiMocks,
}))

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  getErrorMessage: (_error: unknown, fallback: string) => fallback,
}))

vi.mock('@/composables/useAutoTradingControls', () => ({
  useAutoTradingControls: () => ({
    autoTradingEnabled: false,
    autoTradingLoading: false,
    autoTradingScheduleSummary: '',
    ...autoTradingMocks,
  }),
}))

import TradingWorkspaceUnitsTab from '@/components/workspace/TradingWorkspaceUnitsTab.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { elStubs } from '@/test/stubs'

const childStubs = {
  UnitActionsBar: true,
  UnitTable: true,
  AutoTradingConfigDialog: true,
  TradingUnitDetailDialog: true,
  BatchOptimizationConfigDialog: true,
  CreateUnitDialog: true,
  DataSourceDialog: true,
  ExportTradingUnitsDialog: true,
  GroupLinkDialog: true,
  ImportTradingUnitsDialog: true,
  OptimizationConfigDialog: true,
  PositionManagerDialog: true,
  ScheduledOptimizationDialog: true,
  StrategyParamsDialog: true,
  TradingDayStatsDialog: true,
  UnitRuntimeDialog: true,
  UnitSettingsDialog: true,
}

function mountTab() {
  return mount(TradingWorkspaceUnitsTab, {
    props: { workspaceId: 'ws-1' },
    global: { stubs: { ...elStubs, ...childStubs } },
  })
}

describe('TradingWorkspaceUnitsTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    tradingMocks.units = []
    tradingMocks.selectedUnitIds = []
    tradingMocks.running = false
    vi.clearAllMocks()
  })

  it('starts and stops workspace polling and derives trading-unit status counts', async () => {
    tradingMocks.units = [
      {
        id: 'u-live',
        trading_mode: 'live',
        lock_trading: true,
        run_status: 'idle',
        trading_snapshot: { instance_status: 'running', today_pnl: 10, updated_at: '2026-10-10T09:00:00Z' },
      },
      {
        id: 'u-paper',
        trading_mode: 'paper',
        lock_running: true,
        run_status: 'queued',
        trading_snapshot: { instance_status: 'queued', today_pnl: -2 },
        updated_at: '2026-10-11T09:00:00Z',
      },
    ]
    const wrapper = mountTab()
    await flushPromises()
    const vm = wrapper.vm as any

    expect(tradingMocks.clearSelection).toHaveBeenCalledOnce()
    expect(tradingMocks.startPolling).toHaveBeenCalledWith('ws-1')
    expect(autoTradingMocks.loadAutoTradingState).toHaveBeenCalledOnce()
    expect(vm.runningUnitCount).toBe(2)
    expect(vm.lockedUnitCount).toBe(2)
    expect(vm.liveUnitCount).toBe(1)
    expect(vm.paperUnitCount).toBe(1)
    expect(vm.profitableUnitCount).toBe(1)
    expect(vm.lastUpdatedLabel).not.toBe('-')

    wrapper.unmount()
    expect(tradingMocks.stopPolling).toHaveBeenCalledOnce()
  })

  it('warns without a selection and opens the correct optimization dialog by selection count', () => {
    let wrapper = mountTab()
    let vm = wrapper.vm as any

    vm.handleCreateOptimizationTask()
    expect(ElMessage.warning).toHaveBeenCalledWith('tradingUnits.selectUnitForOpt')
    wrapper.unmount()

    tradingMocks.selectedUnitIds = ['u-1']
    wrapper = mountTab()
    vm = wrapper.vm as any
    vm.handleCreateOptimizationTask()
    expect(vm.showOptConfig).toBe(true)
    expect(vm.showBatchOptConfig).toBe(false)
    wrapper.unmount()

    tradingMocks.selectedUnitIds = ['u-1', 'u-2']
    wrapper = mountTab()
    vm = wrapper.vm as any
    vm.handleCreateOptimizationTask()
    expect(vm.showOptConfig).toBe(false)
    expect(vm.showBatchOptConfig).toBe(true)
    wrapper.unmount()
  })

  it('selects all table rows and clears the selection when all rows are already selected', () => {
    tradingMocks.units = [{ id: 'u-1' }, { id: 'u-2' }]
    const vm = mountTab().vm as any
    const table = { clearSelection: vi.fn(), toggleRowSelection: vi.fn() }
    vm.tableRef = table
    tradingMocks.clearSelection.mockClear()

    vm.handleSelectAll()

    expect(table.clearSelection).toHaveBeenCalledOnce()
    expect(table.toggleRowSelection).toHaveBeenNthCalledWith(1, tradingMocks.units[0], true)
    expect(table.toggleRowSelection).toHaveBeenNthCalledWith(2, tradingMocks.units[1], true)

    tradingMocks.selectedUnitIds = ['u-1', 'u-2']
    vm.handleSelectAll()
    expect(table.clearSelection).toHaveBeenCalledTimes(2)
    expect(tradingMocks.clearSelection).toHaveBeenCalledOnce()
  })

  it('requires live-start confirmation and reports partial launch failures', async () => {
    tradingMocks.units = [
      { id: 'u-live', trading_mode: 'live' },
      { id: 'u-paper', trading_mode: 'paper' },
    ]
    tradingMocks.selectedUnitIds = ['u-live', 'u-paper']
    tradingMocks.runSelectedUnits.mockResolvedValueOnce([{ id: 'u-paper', status: 'failed' }])
    const vm = mountTab().vm as any

    await vm.handleStartSelected()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      'tradingUnits.willStart 1 tradingUnits.nLiveUnits。tradingUnits.confirmGateway。',
      'tradingUnits.liveStartConfirm',
      {
        type: 'warning',
        confirmButtonText: 'tradingUnits.confirmStart',
        cancelButtonText: 'tradingUnits.cancel',
      },
    )
    expect(tradingMocks.runSelectedUnits).toHaveBeenCalledWith('ws-1', false)
    expect(ElMessage.warning).toHaveBeenCalledWith(
      'tradingUnits.startSubmitted，1 tradingUnits.nUnitsLaunchFailed',
    )
    expect(tradingMocks.fetchUnits).toHaveBeenCalledWith('ws-1')
    expect(tradingMocks.pollStatus).toHaveBeenCalledWith('ws-1')
  })

  it('does not start live units when the confirmation is cancelled', async () => {
    tradingMocks.units = [{ id: 'u-live', trading_mode: 'live' }]
    tradingMocks.selectedUnitIds = ['u-live']
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    await (mountTab().vm as any).handleStartSelected()

    expect(tradingMocks.runSelectedUnits).not.toHaveBeenCalled()
    expect(tradingMocks.fetchUnits).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('applies lock changes to a copied selection and refreshes unit status', async () => {
    tradingMocks.selectedUnitIds = ['u-1', 'u-2']
    const vm = mountTab().vm as any

    vm.handleLockTrading()
    await flushPromises()

    expect(tradingMocks.patchUnits).toHaveBeenCalledWith('ws-1', ['u-1', 'u-2'], { lock_trading: true })
    expect(ElMessage.success).toHaveBeenCalledWith('tradingUnits.lockedTrading')
    expect(tradingMocks.fetchUnits).toHaveBeenCalledWith('ws-1')
    expect(tradingMocks.pollStatus).toHaveBeenCalledWith('ws-1')
  })

  it('confirms bulk deletion and reports the completed operation', async () => {
    tradingMocks.selectedUnitIds = ['u-1', 'u-2']
    const vm = mountTab().vm as any

    await vm.handleBulkDelete()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      'tradingUnits.confirmDeleteSelected 2 tradingUnits.nUnits？',
      'tradingUnits.deleteConfirm',
      { type: 'warning' },
    )
    expect(tradingMocks.bulkDeleteUnits).toHaveBeenCalledWith('ws-1', ['u-1', 'u-2'])
    expect(ElMessage.success).toHaveBeenCalledWith('tradingUnits.unitDeleted')
  })

  it('warns when exporting no selection and opens export for selected rows', () => {
    tradingMocks.units = [{ id: 'u-1' }, { id: 'u-2' }]
    let wrapper = mountTab()
    let vm = wrapper.vm as any

    vm.handleExportUnits()
    expect(ElMessage.warning).toHaveBeenCalledWith('tradingUnits.selectUnitForExport')
    expect(vm.showExportDialog).toBe(false)
    wrapper.unmount()

    tradingMocks.selectedUnitIds = ['u-2']
    wrapper = mountTab()
    vm = wrapper.vm as any
    expect(vm.selectedUnits).toEqual([{ id: 'u-2' }])
    vm.handleExportUnits()
    expect(vm.showExportDialog).toBe(true)
    wrapper.unmount()
  })

  it('reports runtime-directory success and failure using the selected unit id', async () => {
    const vm = mountTab().vm as any
    const unit = { id: 'u-1' }

    await vm.handleOpenRuntimeDirectory(unit)
    expect(tradingApiMocks.openUnitRuntimeDir).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(ElMessage.success).toHaveBeenCalledWith('Opened unit folder')

    tradingApiMocks.openUnitRuntimeDir.mockRejectedValueOnce(new Error('permission denied'))
    await vm.handleOpenRuntimeDirectory(unit)
    expect(ElMessage.error).toHaveBeenCalledWith('tradingUnits.openUnitFailed')
  })
})
