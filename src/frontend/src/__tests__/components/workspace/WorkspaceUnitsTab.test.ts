import { afterEach, describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
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

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    runUnits: vi.fn().mockResolvedValue(undefined),
    stopUnits: vi.fn().mockResolvedValue(undefined),
    updateUnit: vi.fn().mockResolvedValue(undefined),
    submitOptimization: vi.fn().mockResolvedValue({ task_id: 'opt-1', total_combinations: 3 }),
    getOptimizationProgress: vi.fn().mockResolvedValue({ status: 'completed', total: 3, completed: 3 }),
  },
}))

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const storeState = {
  units: [] as any[],
  selectedUnitIds: [] as string[],
  startPolling: vi.fn(),
  stopPolling: vi.fn(),
  setSelectedUnitIds: vi.fn((ids: string[]) => {
    storeState.selectedUnitIds = ids
  }),
  clearSelection: vi.fn(),
  fetchUnits: vi.fn().mockResolvedValue(undefined),
  bulkDeleteUnits: vi.fn().mockResolvedValue(undefined),
  runSelectedUnits: vi.fn().mockResolvedValue([]),
  stopSelectedUnits: vi.fn().mockResolvedValue(undefined),
  reorderUnits: vi.fn().mockResolvedValue(undefined),
  batchCreateUnits: vi.fn().mockResolvedValue(undefined),
  updateUnit: vi.fn().mockResolvedValue(undefined),
  pollStatus: vi.fn().mockImplementation(async () => {
    for (const unit of storeState.units) {
      if (unit.opt_status === 'pending' || unit.opt_status === 'queued') {
        unit.opt_status = 'completed'
        unit.opt_completed = unit.opt_total
      }
    }
  }),
}

const routerMocks = vi.hoisted(() => ({ push: vi.fn() }))

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => storeState,
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerMocks.push }),
}))

import WorkspaceUnitsTab from '@/components/workspace/WorkspaceUnitsTab.vue'
import { workspaceApi } from '@/api/workspace'
import { ElMessage, ElMessageBox } from 'element-plus'
import { elStubs } from '@/test/stubs'

const childStubs = {
  CreateUnitDialog: true,
  DataSourceDialog: true,
  UnitSettingsDialog: true,
  StrategyParamsDialog: true,
  OptimizationConfigDialog: true,
  OptimizationThreadDialog: true,
  BatchOptimizationConfigDialog: true,
  ChangeSymbolDialog: true,
  GroupRenameDialog: true,
  UnitRenameDialog: true,
  UnitTable: true,
  UnitsActionsBar: true,
  WorkspaceUnitRuntimeDialog: true,
}

const mountedWrappers: Array<{ unmount: () => void }> = []

function doMount(props: Record<string, unknown> = {}) {
  const wrapper = mount(WorkspaceUnitsTab, {
    props: { workspaceId: 'ws-1', ...props },
    global: { stubs: { ...elStubs, ...childStubs } },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('WorkspaceUnitsTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    storeState.units = []
    storeState.selectedUnitIds = []
    vi.clearAllMocks()
  })

  afterEach(() => {
    const wrappers = mountedWrappers.splice(0)
    try {
      wrappers.forEach(wrapper => wrapper.unmount())
      expect(storeState.stopPolling).toHaveBeenCalledTimes(wrappers.length)
    } finally {
      vi.useRealTimers()
    }
  })

  it('mounts cleanly', () => {
    expect(doMount().exists()).toBe(true)
  })

  it('inferBatchParamType returns int for integer ranges and float otherwise', () => {
    const vm = doMount().vm as any
    expect(vm.inferBatchParamType({ start: 1, end: 10, step: 1 })).toBe('int')
    expect(vm.inferBatchParamType({ start: 0.1, end: 1, step: 0.1 })).toBe('float')
  })

  it('calculateBatchTotalCombinations multiplies per-param counts', () => {
    const vm = doMount().vm as any
    expect(vm.calculateBatchTotalCombinations({})).toBe(0)
    expect(
      vm.calculateBatchTotalCombinations({
        a: { start: 0, end: 10, step: 5, type: 'int' }, // 3 values: 0,5,10
        b: { start: 1, end: 3, step: 1, type: 'int' }, // 3 values: 1,2,3
      }),
    ).toBe(9)
    expect(
      vm.calculateBatchTotalCombinations({ a: { start: 5, end: 5, step: 1, type: 'int' } }),
    ).toBe(0)
  })

  it('optimization status predicates classify states', () => {
    const vm = doMount().vm as any
    expect(vm.isOptimizationActiveStatus('running')).toBe(true)
    expect(vm.isOptimizationActiveStatus('completed')).toBe(false)
    expect(vm.isOptimizationPendingStatus('queued')).toBe(true)
    expect(vm.isOptimizationPendingStatus('running')).toBe(false)
    expect(vm.isOptimizationTerminalStatus('failed')).toBe(true)
    expect(vm.isOptimizationTerminalStatus('running')).toBe(false)
  })

  it('getOptimizationTotal/Completed clamp to >= 0', () => {
    const vm = doMount().vm as any
    expect(vm.getOptimizationTotal({ opt_total: 5 })).toBe(5)
    expect(vm.getOptimizationTotal({ opt_total: -3 })).toBe(0)
    expect(vm.getOptimizationCompleted({ opt_completed: 2 })).toBe(2)
    expect(vm.getOptimizationCompleted({})).toBe(0)
  })

  it('shouldShowOptimizationProgress reflects active vs terminal state', () => {
    const vm = doMount().vm as any
    expect(vm.shouldShowOptimizationProgress({ opt_status: 'running' })).toBe(true)
    expect(vm.shouldShowOptimizationProgress({ opt_status: 'completed' })).toBe(false)
    expect(
      vm.shouldShowOptimizationProgress({ opt_status: null, opt_total: 10, opt_completed: 3 }),
    ).toBe(true)
  })

  it('runStatusTagType and runStatusLabel map known statuses', () => {
    const vm = doMount().vm as any
    expect(vm.runStatusTagType('running')).toBe('primary')
    expect(vm.runStatusTagType('completed')).toBe('success')
    expect(vm.runStatusTagType('unknown')).toBe('info')
    expect(vm.runStatusLabel('idle')).toBe('units.statusIdle')
    expect(vm.runStatusLabel('weird')).toBe('weird')
  })

  it('optimizationStatusTagType/Label handle null', () => {
    const vm = doMount().vm as any
    expect(vm.optimizationStatusTagType('completed')).toBe('success')
    expect(vm.optimizationStatusTagType(null)).toBe('info')
    expect(vm.optimizationStatusLabel(null)).toBe('-')
    expect(vm.optimizationStatusLabel('failed')).toBe('units.statusFail')
  })

  it('objectiveLabel maps known objectives', () => {
    const vm = doMount().vm as any
    expect(vm.objectiveLabel('sharpe_max')).toBe('optimization.sharpe (optimization.maximize)')
    expect(vm.objectiveLabel('min_drawdown')).toBe('optimization.maxDrawdown (optimization.minimize)')
    expect(vm.objectiveLabel(undefined)).toBe('-')
    expect(vm.objectiveLabel('custom')).toBe('custom')
  })

  it('batch submission maps a legacy objective into the canonical request pair', async () => {
    storeState.units = [{
      id: 'u-1',
      strategy_name: 'Alpha',
      optimization_config: {
        objective: 'min_drawdown',
        param_layers: [{ param_name: 'fast', opt_type: 'equal_diff', start: 1, end: 3, step: 1 }],
      },
    }]
    storeState.selectedUnitIds = ['u-1']

    await (doMount().vm as any).handleBatchSubmitOpt()

    expect(workspaceApi.submitOptimization).toHaveBeenCalledWith('ws-1', expect.objectContaining({
      unit_id: 'u-1',
      objective: 'max_drawdown',
      direction: 'minimize',
    }))
  })

  it('formatOptimizationCount renders completed/total or dash', () => {
    const vm = doMount().vm as any
    expect(vm.formatOptimizationCount({ opt_total: 0 })).toBe('-')
    expect(vm.formatOptimizationCount({ opt_total: 10, opt_completed: 4 })).toBe('4/10')
  })

  it('unitResultSummary renders metrics and failure reasons', () => {
    const vm = doMount().vm as any
    expect(
      vm.unitResultSummary({
        run_status: 'completed',
        metrics_snapshot: { total_return: 0.1234, sharpe_ratio: 1.234, total_trades: 8 },
      }),
    ).toBe('收益 12.34% · Sharpe 1.23 · 交易 8')
    expect(
      vm.unitResultSummary({
        run_status: 'failed',
        error_message: 'No CSV file found for symbol=sa',
        metrics_snapshot: {},
      }),
    ).toBe('失败：No CSV file found for symbol=sa')
  })

  it('canOpenReport requires completed status and a task id', () => {
    const vm = doMount().vm as any
    expect(vm.canOpenReport({ run_status: 'completed', last_task_id: 't-1' })).toBe(true)
    expect(vm.canOpenReport({ run_status: 'completed', last_task_id: '' })).toBe(false)
    expect(vm.canOpenReport({ run_status: 'idle', last_task_id: 't-1' })).toBe(false)
  })

  it('selection computeds reflect store state', async () => {
    storeState.units = [{ id: 'u-1' }, { id: 'u-2' }]
    storeState.selectedUnitIds = ['u-1']
    const vm = doMount().vm as any
    expect(vm.hasSelection).toBe(true)
    expect(vm.hasSingleSelection).toBe(true)
    expect(vm.selectedUnit?.id).toBe('u-1')
  })

  it('routes eligible unit reports and ignores selection, controls, and incomplete rows on double click', () => {
    const completedUnit = {
      id: 'u-done',
      run_status: 'completed',
      last_task_id: 'bt-7',
      strategy_name: 'Alpha',
      group_name: 'ignored-group',
      strategy_id: 'alpha-id',
    }
    storeState.units = [completedUnit]
    storeState.selectedUnitIds = ['u-done']
    const vm = doMount().vm as any
    const interactiveTarget = { closest: vi.fn().mockReturnValue({}) }
    const plainTarget = { closest: vi.fn().mockReturnValue(null) }

    vm.handleOpenSelectedReport()
    expect(routerMocks.push).toHaveBeenCalledWith({
      name: 'BacktestResult',
      params: { id: 'bt-7' },
      query: { workspaceId: 'ws-1', unitId: 'u-done', strategyName: 'Alpha' },
    })

    routerMocks.push.mockClear()
    vm.handleRowDblClick(completedUnit, { type: 'selection' }, { target: plainTarget } as unknown as MouseEvent)
    vm.handleRowDblClick(completedUnit, null, { target: interactiveTarget } as unknown as MouseEvent)
    vm.handleRowDblClick(
      { ...completedUnit, run_status: 'running' },
      null,
      { target: plainTarget } as unknown as MouseEvent,
    )
    expect(routerMocks.push).not.toHaveBeenCalled()

    vm.handleRowDblClick(completedUnit, null, { target: plainTarget } as unknown as MouseEvent)
    expect(routerMocks.push).toHaveBeenCalledWith(expect.objectContaining({
      params: { id: 'bt-7' },
      query: expect.objectContaining({ strategyName: 'Alpha' }),
    }))
    expect(interactiveTarget.closest).toHaveBeenCalledWith('button, a, .el-checkbox')
  })

  it('synchronizes selection and refreshes workspace units through public callbacks', async () => {
    const vm = doMount().vm as any

    vm.onSelectionChange([{ id: 'u-1' }, { id: 'u-2' }])
    expect(storeState.setSelectedUnitIds).toHaveBeenCalledWith(['u-1', 'u-2'])
    await vm.onUnitUpdated()
    await vm.onUnitsRefresh()
    vm.onUnitCreated()
    vm.handleReloadStrategy()

    expect(storeState.fetchUnits).toHaveBeenCalledTimes(4)
    expect(storeState.fetchUnits).toHaveBeenCalledWith('ws-1')
    expect(storeState.pollStatus).toHaveBeenCalledTimes(2)
    expect(ElMessage.success).toHaveBeenCalledWith('units.strategyReloaded')
  })

  it('confirms bulk deletion and sends a stable selection snapshot', async () => {
    storeState.selectedUnitIds = ['u-1', 'u-2']
    const vm = doMount().vm as any

    await vm.handleBulkDelete()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      'units.confirmDeleteSelected 2 units.nUnitsSuffix？',
      'units.deleteConfirm',
      { type: 'warning' },
    )
    expect(storeState.bulkDeleteUnits).toHaveBeenCalledWith('ws-1', ['u-1', 'u-2'])
    expect(ElMessage.success).toHaveBeenCalledWith('units.deleted')
  })

  it('does not delete selected units after the confirmation is cancelled', async () => {
    storeState.selectedUnitIds = ['u-1']
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')

    await (doMount().vm as any).handleBulkDelete()

    expect(storeState.bulkDeleteUnits).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('runs and stops the selected units with the requested mode and feedback', async () => {
    storeState.selectedUnitIds = ['u-1', 'u-2']
    const vm = doMount().vm as any

    await vm.handleRunSelected(false)
    await vm.handleRunSelected(true)
    await vm.handleStopSelected()

    expect(storeState.runSelectedUnits).toHaveBeenNthCalledWith(1, 'ws-1', false)
    expect(storeState.runSelectedUnits).toHaveBeenNthCalledWith(2, 'ws-1', true)
    expect(storeState.stopSelectedUnits).toHaveBeenCalledWith('ws-1')
    expect(ElMessage.success).toHaveBeenCalledWith('units.serialStarted')
    expect(ElMessage.success).toHaveBeenCalledWith('units.parallelStarted')
    expect(ElMessage.success).toHaveBeenCalledWith('units.stopSent')
  })

  it('reorders one selected unit and leaves the first row unchanged when moving up', async () => {
    storeState.units = [{ id: 'u-1' }, { id: 'u-2' }, { id: 'u-3' }]
    storeState.selectedUnitIds = ['u-2']
    const vm = doMount().vm as any

    await vm.handleMove('up')
    expect(storeState.reorderUnits).toHaveBeenCalledWith('ws-1', ['u-2', 'u-1', 'u-3'])

    storeState.reorderUnits.mockClear()
    storeState.selectedUnitIds = ['u-1']
    await vm.handleMove('up')
    expect(storeState.reorderUnits).not.toHaveBeenCalled()
  })

  it('reorders selected units down, to top, and to bottom while rejecting invalid moves', async () => {
    storeState.units = [{ id: 'u-1' }, { id: 'u-2' }, { id: 'u-3' }]
    storeState.selectedUnitIds = ['u-2']
    const vm = doMount().vm as any

    await vm.handleMove('down')
    expect(storeState.reorderUnits).toHaveBeenLastCalledWith('ws-1', ['u-1', 'u-3', 'u-2'])

    storeState.selectedUnitIds = ['u-3']
    await vm.handleMove('top')
    expect(storeState.reorderUnits).toHaveBeenLastCalledWith('ws-1', ['u-3', 'u-1', 'u-2'])

    storeState.selectedUnitIds = ['u-1']
    await vm.handleMove('bottom')
    expect(storeState.reorderUnits).toHaveBeenLastCalledWith('ws-1', ['u-2', 'u-3', 'u-1'])

    storeState.reorderUnits.mockClear()
    storeState.selectedUnitIds = ['u-3']
    await vm.handleMove('down')
    storeState.selectedUnitIds = ['missing']
    await vm.handleMove('top')
    storeState.selectedUnitIds = ['u-1', 'u-2']
    const multiSelectionVm = doMount().vm as any
    await multiSelectionVm.handleMove('top')
    expect(storeState.reorderUnits).not.toHaveBeenCalled()
  })

  it('reports a reorder failure without changing the requested order', async () => {
    storeState.units = [{ id: 'u-1' }, { id: 'u-2' }]
    storeState.selectedUnitIds = ['u-2']
    storeState.reorderUnits.mockRejectedValueOnce(new Error('write denied'))
    const vm = doMount().vm as any

    await vm.handleMove('top')

    expect(storeState.reorderUnits).toHaveBeenCalledWith('ws-1', ['u-2', 'u-1'])
    expect(ElMessage.error).toHaveBeenCalledWith('units.sortFailed')
  })

  it('warns when a batch has no configured units and restores the submit state', async () => {
    storeState.selectedUnitIds = ['u-missing']
    const vm = doMount().vm as any

    await vm.handleBatchSubmitOpt()

    expect(workspaceApi.submitOptimization).not.toHaveBeenCalled()
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('units.needParamRange'))
    expect(vm.batchSubmittingOptimization).toBe(false)
    expect(storeState.fetchUnits).toHaveBeenCalledTimes(2)
  })

  it('warns when every configured batch range is invalid and does not ask for confirmation', async () => {
    storeState.units = [{
      id: 'u-invalid',
      strategy_name: 'Invalid range',
      optimization_config: {
        param_layers: [{ param_name: 'fast', opt_type: 'equal_diff', start: 3, end: 1, step: 0 }],
      },
    }]
    storeState.selectedUnitIds = ['u-invalid']
    const vm = doMount().vm as any

    await vm.handleBatchSubmitOpt()

    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('units.paramRangeAllInvalid'))
    expect(ElMessageBox.confirm).not.toHaveBeenCalled()
    expect(workspaceApi.submitOptimization).not.toHaveBeenCalled()
    expect(vm.batchSubmittingOptimization).toBe(false)
    expect(storeState.fetchUnits).toHaveBeenCalledTimes(2)
  })

  it('leaves a batch unsubmitted when confirmation is cancelled', async () => {
    storeState.units = [{
      id: 'u-cancel',
      optimization_config: {
        param_layers: [{ param_name: 'fast', opt_type: 'equal_diff', start: 1, end: 3, step: 1 }],
      },
    }]
    storeState.selectedUnitIds = ['u-cancel']
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    const vm = doMount().vm as any

    await vm.handleBatchSubmitOpt()

    expect(ElMessageBox.confirm).toHaveBeenCalledOnce()
    expect(workspaceApi.submitOptimization).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
    expect(vm.batchSubmittingOptimization).toBe(false)
    expect(storeState.fetchUnits).toHaveBeenCalledTimes(2)
  })

  it('submits only valid batch ranges and reports invalid selections', async () => {
    storeState.units = [
      {
        id: 'u-valid',
        strategy_name: 'Valid',
        optimization_config: {
          objective: 'total_return',
          direction: 'maximize',
          param_layers: [{ param_name: 'fast', opt_type: 'equal_diff', start: 1, end: 3, step: 1 }],
        },
      },
      {
        id: 'u-invalid',
        strategy_name: 'Invalid',
        optimization_config: {
          param_layers: [{ param_name: 'slow', opt_type: 'equal_diff', start: 5, end: 3, step: 1 }],
        },
      },
    ]
    storeState.selectedUnitIds = ['u-valid', 'u-invalid']
    const vm = doMount().vm as any

    await vm.handleBatchSubmitOpt()

    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('1 units.submitNUnits？'),
      'units.submitBatchOpt',
      { type: 'info' },
    )
    expect(ElMessageBox.confirm).toHaveBeenCalledWith(
      expect.stringContaining('1 units.paramRangeInvalid'),
      expect.any(String),
      expect.any(Object),
    )
    expect(workspaceApi.submitOptimization).toHaveBeenCalledTimes(1)
    expect(workspaceApi.submitOptimization).toHaveBeenCalledWith('ws-1', {
      unit_id: 'u-valid',
      param_ranges: { fast: { start: 1, end: 3, step: 1, type: 'int' } },
      objective: 'total_return',
      direction: 'maximize',
      n_workers: 4,
      mode: 'grid',
      timeout: 0,
    })
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('units.serialFinished'))
    expect(storeState.units[0].opt_status).toBe('completed')
    expect(vm.batchSubmittingOptimization).toBe(false)
  })

  it('applies optimization progress before reporting a completed batch task', async () => {
    storeState.units = [{
      id: 'u-progress',
      strategy_name: 'Progress unit',
      optimization_config: {
        param_layers: [{ param_name: 'fast', opt_type: 'equal_diff', start: 1, end: 3, step: 1 }],
      },
    }]
    storeState.selectedUnitIds = ['u-progress']
    storeState.pollStatus
      .mockImplementationOnce(async () => undefined)
      .mockImplementationOnce(async () => undefined)
    vi.mocked(workspaceApi.getOptimizationProgress).mockResolvedValueOnce({
      status: 'completed',
      total: 3,
      completed: 2,
      failed: 1,
      progress: 100,
    } as any)
    const vm = doMount().vm as any

    await vm.handleBatchSubmitOpt()

    expect(workspaceApi.getOptimizationProgress).toHaveBeenCalledWith('ws-1', 'u-progress')
    expect(storeState.units[0]).toMatchObject({
      last_optimization_task_id: 'opt-1',
      opt_status: 'completed',
      opt_total: 3,
      opt_completed: 3,
      opt_progress: 100,
    })
    expect(ElMessage.success).toHaveBeenCalledWith('units.serialFinished: 1 units.nUnitsFinished')
    expect(vm.batchSubmittingOptimization).toBe(false)
  })

  it('reports a batch submit failure and always restores the submit state', async () => {
    storeState.units = [{
      id: 'u-submit-fail',
      strategy_name: 'Unavailable unit',
      optimization_config: {
        param_layers: [{ param_name: 'fast', opt_type: 'equal_diff', start: 1, end: 3, step: 1 }],
      },
    }]
    storeState.selectedUnitIds = ['u-submit-fail']
    vi.mocked(workspaceApi.submitOptimization).mockRejectedValueOnce(new Error('worker unavailable'))
    const vm = doMount().vm as any

    await vm.handleBatchSubmitOpt()

    expect(workspaceApi.submitOptimization).toHaveBeenCalledWith('ws-1', expect.objectContaining({
      unit_id: 'u-submit-fail',
      param_ranges: { fast: { start: 1, end: 3, step: 1, type: 'int' } },
    }))
    expect(ElMessage.warning).toHaveBeenCalledWith(expect.stringContaining('1 units.nSubmitFailed'))
    expect(vm.batchSubmittingOptimization).toBe(false)
  })

  it('imports a JSON unit list and shows a warning for an empty file', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    const input = wrapper.get('input[type="file"]').element as HTMLInputElement
    const click = vi.spyOn(input, 'click').mockImplementation(() => undefined)
    await wrapper.findAll('button')[6].trigger('click')
    expect(click).toHaveBeenCalledOnce()

    const file = { text: vi.fn().mockResolvedValue(JSON.stringify([{ strategy_id: 'alpha' }])) }

    await vm.onImportFileSelected({ target: { files: [file] } } as unknown as Event)

    expect(storeState.batchCreateUnits).toHaveBeenCalledWith('ws-1', [{ strategy_id: 'alpha' }])
    expect(ElMessage.success).toHaveBeenCalledWith('units.importSuccess 1 units.nStrategyUnits')

    const emptyFile = { text: vi.fn().mockResolvedValue('[]') }
    await vm.onImportFileSelected({ target: { files: [emptyFile] } } as unknown as Event)

    expect(ElMessage.warning).toHaveBeenCalledWith('units.importNoUnits')
    expect(storeState.batchCreateUnits).toHaveBeenCalledTimes(1)
    click.mockRestore()
  })

  it('imports the object-wrapped unit format', async () => {
    const vm = doMount().vm as any
    const units = [{ strategy_id: 'beta', params: { fast: 3 } }]
    await vm.onImportFileSelected({
      target: { files: [{ text: vi.fn().mockResolvedValue(JSON.stringify({ units })) }] },
    } as unknown as Event)

    expect(storeState.batchCreateUnits).toHaveBeenCalledWith('ws-1', units)
    expect(ElMessage.success).toHaveBeenCalledWith('units.importSuccess 1 units.nStrategyUnits')
  })

  it('reports malformed and unreadable unit import files and ignores an empty file selection', async () => {
    const vm = doMount().vm as any

    await vm.onImportFileSelected({ target: { files: [] } } as unknown as Event)
    expect(ElMessage.error).not.toHaveBeenCalled()

    await vm.onImportFileSelected({
      target: { files: [{ text: vi.fn().mockResolvedValue('{broken json') }] },
    } as unknown as Event)
    await vm.onImportFileSelected({
      target: { files: [{ text: vi.fn().mockRejectedValue(new Error('read denied')) }] },
    } as unknown as Event)

    expect(storeState.batchCreateUnits).not.toHaveBeenCalled()
    expect(ElMessage.error).toHaveBeenCalledTimes(2)
    expect(ElMessage.error).toHaveBeenCalledWith('units.importFailed')
  })

  it('exports only the selected units as a dated JSON download', async () => {
    storeState.units = [{
      id: 'u-1',
      strategy_name: 'Alpha',
      strategy_id: 'alpha',
      symbol: '000001.SZ',
      symbol_name: '平安银行',
      timeframe: '1d',
      group_name: 'banking',
      category: 'stock',
      data_config: { source: 'local' },
      unit_settings: { capital: 100000 },
      params: { fast: 3 },
      optimization_config: { objective: 'sharpe_ratio' },
      internal_runtime_id: 'must-not-export',
    }, { id: 'u-2', strategy_name: 'Unselected' }]
    storeState.selectedUnitIds = ['u-1']

    const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:units-export')
    const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const clicked: HTMLAnchorElement[] = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
    try {
      const vm = doMount().vm as any
      vm.handleExportUnits()

      expect(createUrl).toHaveBeenCalledOnce()
      const [blob] = createUrl.mock.calls[0]
      expect(JSON.parse(await (blob as Blob).text())).toEqual([{
        strategy_name: 'Alpha',
        strategy_id: 'alpha',
        symbol: '000001.SZ',
        symbol_name: '平安银行',
        timeframe: '1d',
        group_name: 'banking',
        category: 'stock',
        data_config: { source: 'local' },
        unit_settings: { capital: 100000 },
        params: { fast: 3 },
        optimization_config: { objective: 'sharpe_ratio' },
      }])
      expect(clicked).toHaveLength(1)
      expect(clicked[0].href).toBe('blob:units-export')
      expect(clicked[0].download).toMatch(/^units_export_\d{4}-\d{2}-\d{2}\.json$/)
      expect(revokeUrl).toHaveBeenCalledWith('blob:units-export')
      expect(ElMessage.success).toHaveBeenCalledWith('units.exported 1 units.nStrategyUnits')
    } finally {
      createUrl.mockRestore()
      revokeUrl.mockRestore()
      click.mockRestore()
    }
  })
})
