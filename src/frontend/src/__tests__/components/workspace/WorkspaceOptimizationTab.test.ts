import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ElMessageBox } from 'element-plus'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

const optimizationMocks = vi.hoisted(() => ({
  getOptimizationResults: vi.fn().mockResolvedValue({ rows: [], status: 'idle' }),
  getOptimizationProgress: vi.fn().mockResolvedValue({ status: 'idle' }),
  cancelOptimization: vi.fn().mockResolvedValue(undefined),
  applyBestParams: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: {
    confirm: vi.fn().mockResolvedValue('confirm'),
    alert: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: optimizationMocks,
}))

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => ({
    units: [{ id: 'u-1', strategy_name: 'Alpha', last_optimization_task_id: 'task-1' }],
    currentWorkspace: { settings: {} },
    fetchUnits: vi.fn().mockResolvedValue(undefined),
  }),
}))

import WorkspaceOptimizationTab from '@/components/workspace/WorkspaceOptimizationTab.vue'
import { elStubs } from '@/test/stubs'

function doMount(props: Record<string, unknown> = {}) {
  return mount(WorkspaceOptimizationTab, {
    props: { workspaceId: 'ws-1', ...props },
    global: { stubs: elStubs },
  })
}

describe('WorkspaceOptimizationTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('mounts cleanly', () => {
    expect(doMount().exists()).toBe(true)
  })

  it('formatParams renders key=value pairs and handles non-objects', () => {
    const vm = doMount().vm as any
    expect(vm.formatParams({ fast: 5, slow: 20 })).toBe('fast=5, slow=20')
    expect(vm.formatParams(null)).toBe('-')
    expect(vm.formatParams('x')).toBe('-')
  })

  it('fmtVal formats numbers to 4 decimals', () => {
    const vm = doMount().vm as any
    expect(vm.fmtVal(1.23456)).toBe('1.2346')
    expect(vm.fmtVal(null)).toBe('-')
    expect(vm.fmtVal('abc')).toBe('abc')
  })

  it('fmtMoney formats numbers and passes strings', () => {
    const vm = doMount().vm as any
    expect(vm.fmtMoney(null)).toBe('-')
    expect(vm.fmtMoney('x')).toBe('x')
    expect(typeof vm.fmtMoney(1000)).toBe('string')
  })

  it('progressPct computes percentage from completed/total', () => {
    const vm = doMount().vm as any
    expect(vm.progressPct).toBe(0)
    vm.total = 4
    vm.completed = 1
    expect(vm.progressPct).toBe(25)
  })

  it('hasResults reflects rows or running state', () => {
    const vm = doMount().vm as any
    expect(vm.hasResults).toBe(false)
    vm.resultRows = [{ params: {}, sharpe_ratio: 1 }]
    expect(vm.hasResults).toBe(true)
  })

  it('does not call the first displayed row best without objective metadata', () => {
    const vm = doMount().vm as any
    vm.resultRows = [
      { result_index: 3, params: { fast: 5 }, sharpe_ratio: 2.5 },
      { result_index: 7, params: { fast: 8 }, sharpe_ratio: 1.5 },
    ]
    expect(vm.bestParamsStr).toContain('optimization.selectResultToContinue')
    vm.handleSelectResult(vm.displayRows[0])
    expect(vm.bestParamsStr).toBe('fast=5')
    expect(vm.featuredMetricValue).toBe('2.5000')
  })

  it('displayRows sorts by the active sort key descending by default', () => {
    const vm = doMount().vm as any
    vm.resultRows = [
      { params: {}, sharpe_ratio: 1 },
      { params: {}, sharpe_ratio: 3 },
      { params: {}, sharpe_ratio: 2 },
    ]
    vm.sortKey = 'sharpe_ratio'
    vm.sortDir = 'desc'
    const sharpes = vm.displayRows.map((r: any) => r.sharpe_ratio)
    expect(sharpes).toEqual([3, 2, 1])
  })

  it('keeps the backend maximize best when the user reverses display sorting', async () => {
    optimizationMocks.getOptimizationResults.mockResolvedValue({
      task_id: 'task-1',
      status: 'completed',
      total: 2,
      completed: 2,
      failed: 0,
      param_names: ['fast'],
      objective: 'total_return',
      direction: 'maximize',
      tie_break: 'lowest_trial_index',
      best: { result_index: 1, params: { fast: 8 }, total_return: 12, sharpe_ratio: 1.8 },
      rows: [
        { result_index: 0, params: { fast: 5 }, total_return: 4, sharpe_ratio: 2.5 },
        { result_index: 1, params: { fast: 8 }, total_return: 12, sharpe_ratio: 1.8 },
      ],
    })
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    await vm.loadResults()

    expect(vm.featuredResult.result_index).toBe(1)
    expect(vm.featuredMetricLabel).toBe('optimization.totalReturn')
    expect(vm.featuredMetricValue).toBe('12.0000')
    vm.sortKey = 'total_return'
    vm.sortDir = 'asc'
    expect(vm.displayRows[0].result_index).toBe(0)
    expect(vm.featuredResult.result_index).toBe(1)

    vm.handleTestReport()
    expect(ElMessageBox.alert).toHaveBeenCalledWith(
      expect.stringContaining('fast=8'),
      'optimization.paramReportTitle',
      expect.any(Object),
    )
    await vm.handleApplyBest()
    expect(optimizationMocks.applyBestParams).toHaveBeenCalledWith('ws-1', {
      unit_id: 'u-1',
      optimization_task_id: 'task-1',
      result_index: 1,
    })
  })

  it('uses the backend minimize best and its stable tie metadata', async () => {
    optimizationMocks.getOptimizationResults.mockResolvedValue({
      task_id: 'task-1',
      status: 'completed',
      total: 2,
      completed: 2,
      failed: 0,
      param_names: ['fast'],
      objective: 'max_drawdown',
      direction: 'minimize',
      tie_break: 'lowest_trial_index',
      best: { result_index: 1, params: { fast: 8 }, max_drawdown: 3.2, sharpe_ratio: 1.8 },
      rows: [
        { result_index: 0, params: { fast: 5 }, max_drawdown: 8.4, sharpe_ratio: 2.5 },
        { result_index: 1, params: { fast: 8 }, max_drawdown: 3.2, sharpe_ratio: 1.8 },
      ],
    })
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    await vm.loadResults()

    expect(vm.sortDir).toBe('asc')
    expect(vm.displayRows[0].result_index).toBe(1)
    expect(vm.featuredResult.result_index).toBe(1)
    expect(vm.featuredMetricLabel).toBe('optimization.maxDrawdown')
    expect(vm.optimizationTieBreak).toBe('lowest_trial_index')
  })

  it('requires explicit legacy row selection for report and apply', async () => {
    optimizationMocks.getOptimizationResults.mockResolvedValue({
      task_id: 'legacy-task',
      status: 'completed',
      total: 2,
      completed: 2,
      failed: 0,
      param_names: ['fast'],
      objective: null,
      direction: null,
      best: null,
      rows: [
        { result_index: 10, params: { fast: 5 }, sharpe_ratio: 2.5 },
        { result_index: 11, params: { fast: 8 }, sharpe_ratio: 1.5 },
      ],
    })
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    await vm.loadResults()
    expect(vm.canApplyFeaturedResult).toBe(false)
    expect(vm.canReportFeaturedResult).toBe(false)

    vm.handleSelectResult(vm.displayRows[1])
    expect(vm.bestParamsStr).toBe('fast=8')
    expect(vm.canApplyFeaturedResult).toBe(true)
    vm.sortKey = 'sharpe_ratio'
    vm.sortDir = 'desc'
    expect(vm.selectedResult.result_index).toBe(11)
    vm.handleTestReport()
    expect(optimizationMocks.applyBestParams).not.toHaveBeenCalled()
    await vm.handleApplyBest()
    expect(optimizationMocks.applyBestParams).toHaveBeenCalledWith('ws-1', {
      unit_id: 'u-1',
      optimization_task_id: 'legacy-task',
      result_index: 11,
    })
  })

  it('does not invent a best row for an empty objective-bound result', async () => {
    optimizationMocks.getOptimizationResults.mockResolvedValue({
      task_id: 'task-1',
      status: 'completed',
      total: 2,
      completed: 0,
      failed: 2,
      param_names: [],
      objective: 'sharpe_ratio',
      direction: 'maximize',
      tie_break: 'lowest_trial_index',
      best: null,
      rows: [],
    })
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    await vm.loadResults()
    expect(vm.featuredResult).toBe(null)
    expect(vm.bestParamsStr).toContain('optimization.noBestResult')
    expect(vm.canApplyFeaturedResult).toBe(false)
    expect(vm.canReportFeaturedResult).toBe(false)
  })

  it('emptyStateDescription varies by optimization status', () => {
    const vm = doMount().vm as any
    vm.optimizationStatus = 'cancelled'
    expect(vm.emptyStateDescription).toContain('optimization.taskCancelled')
    vm.optimizationStatus = 'failed'
    expect(vm.emptyStateDescription).toContain('optimization.taskFailed')
  })
})
