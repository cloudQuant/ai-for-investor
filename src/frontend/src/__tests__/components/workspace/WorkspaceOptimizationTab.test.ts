import { afterEach, describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { isReactive, nextTick } from 'vue'
import { ElMessageBox } from 'element-plus'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

const optimizationMocks = vi.hoisted(() => ({
  routerPush: vi.fn(),
  getOptimizationResults: vi.fn().mockResolvedValue({ rows: [], status: 'idle' }),
  getOptimizationProgress: vi.fn().mockResolvedValue({ status: 'idle' }),
  cancelOptimization: vi.fn().mockResolvedValue(undefined),
  applyBestParams: vi.fn().mockResolvedValue(undefined),
  update: vi.fn().mockResolvedValue(undefined),
  updateUnit: vi.fn().mockResolvedValue(undefined),
  runUnits: vi.fn().mockResolvedValue({ results: [] }),
  getUnitsStatus: vi.fn().mockResolvedValue([]),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
  ElMessageBox: {
    confirm: vi.fn().mockResolvedValue('confirm'),
    alert: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: optimizationMocks.routerPush }),
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
    units: [{ id: 'u-1', strategy_name: 'Alpha', last_optimization_task_id: 'task-1', params: { slow: 20 } }],
    currentWorkspace: { settings: {} },
    fetchUnits: vi.fn().mockResolvedValue(undefined),
  }),
}))

import WorkspaceOptimizationTab from '@/components/workspace/WorkspaceOptimizationTab.vue'
import { ElMessage } from 'element-plus'
import { elStubs } from '@/test/stubs'

const mountedWrappers = new Set<{ unmount: () => void }>()

function doMount(props: Record<string, unknown> = {}) {
  const wrapper = mount(WorkspaceOptimizationTab, {
    props: { workspaceId: 'ws-1', ...props },
    global: { stubs: elStubs },
  })
  mountedWrappers.add(wrapper)
  return wrapper
}

describe('WorkspaceOptimizationTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  afterEach(() => {
    const wrappers = [...mountedWrappers]
    mountedWrappers.clear()
    try {
      wrappers.forEach(wrapper => wrapper.unmount())
    } finally {
      vi.clearAllTimers()
      vi.useRealTimers()
    }
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

  it('keeps a selected source row stable across sorting and recalculates annual return by profile', () => {
    const vm = doMount().vm as any
    vm.resultRows = [
      { result_index: 8, params: { fast: 2 }, sharpe_ratio: 1, total_return: 12, trading_days: 120, annual_return: 8 },
      { result_index: 9, params: { fast: 4 }, sharpe_ratio: 3, total_return: 20, trading_days: 120 },
    ]
    vm.calcMethod = 'simple'
    vm.annualDays = 365
    expect(vm._recalcAnnual(vm.resultRows[0])).toBe(36.5)

    vm.calcMethod = 'compound'
    expect(vm._recalcAnnual(vm.resultRows[0])).toBeCloseTo((Math.pow(1.12, 365 / 120) - 1) * 100)
    expect(vm._recalcAnnual({ annual_return: 7, trading_days: 0 })).toBe(7)

    vm.sortKey = 'sharpe_ratio'
    vm.sortDir = 'desc'
    vm.handleSelectResult(vm.displayRows[0])
    expect(vm.selectedResult.result_index).toBe(9)
    vm.sortDir = 'asc'
    expect(vm.displayRows[0].result_index).toBe(8)
    expect(vm.selectedResult.result_index).toBe(9)
    vm.handleSelectResult({})
    expect(vm.selectedResult).toBe(null)
    vm.handleSelectResult(null)
    expect(vm.selectedResult).toBe(null)
  })

  it('restores saved display settings and filters stale analysis controls against loaded rows', () => {
    const vm = doMount().vm as any
    vm.store.currentWorkspace.settings.optimization_config = {
      sort_key: 'total_return',
      sort_dir: 'asc',
      view_mode: 'analysis',
      calc_method: 'compound',
      annual_days: 365,
      stat_time_range: ['2025-01-01', '2025-12-31'],
      visible_fields: ['total_return'],
      analysis_params: ['fast', 'slow', 'volume', 'stale'],
      analysis_metric: 'total_return',
    }

    vm._restoreOptDefaults()

    expect(vm.sortKey).toBe('total_return')
    expect(vm.sortDir).toBe('asc')
    expect(vm.viewMode).toBe('analysis')
    expect(vm.calcMethod).toBe('compound')
    expect(vm.annualDays).toBe(365)
    expect(vm.statTimeRange).toEqual(['2025-01-01', '2025-12-31'])
    expect(vm.visibleFields).toEqual(['total_return'])
    expect(vm.selectedAnalysisParams).toEqual(['fast', 'slow', 'volume'])

    vm.paramNames = ['fast', 'slow', 'volume']
    vm.selectedAnalysisParams = ['slow', 'missing', 'fast', 'volume']
    vm.analysisMetric = 'unsupported_metric'
    vm.resultRows = [{ params: { fast: 2 }, total_return: '12.5', sharpe_ratio: 'not-a-number' }]
    vm.initializeAnalysisControls()

    expect(vm.selectedAnalysisParams).toEqual(['slow', 'fast', 'volume'])
    expect(vm.analysisMetric).toBe('total_return')
    expect(vm.metricOptions.map((option: any) => option.value)).toContain('total_return')
    expect(vm.metricOptions.map((option: any) => option.value)).not.toContain('sharpe_ratio')
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

  it('loads legacy result payloads, derives parameter names, and keeps progress defaults', async () => {
    optimizationMocks.getOptimizationProgress.mockResolvedValueOnce({
      status: 'running',
      total: 4,
      completed: 2,
      failed: 1,
    })
    optimizationMocks.getOptimizationResults.mockResolvedValueOnce({
      task_id: 'legacy-task',
      results: [{ params: { fast: 5, slow: 20 }, total_return: 12 }],
      objective: 'unknown-objective',
      direction: 'sideways',
    })
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'

    await vm.loadResults()

    expect(optimizationMocks.getOptimizationProgress).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(optimizationMocks.getOptimizationResults).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(vm.paramNames).toEqual(['fast', 'slow'])
    expect(vm.optimizationTaskId).toBe('legacy-task')
    expect(vm.optimizationObjective).toBe(null)
    expect(vm.optimizationDirection).toBe(null)
    expect(vm.optimizationStatus).toBe('running')
    expect(vm.total).toBe(4)
    expect(vm.completed).toBe(2)
    expect(vm.failed).toBe(1)
    expect(vm.loading).toBe(false)
  })

  it('clears stale result state when the API has no result rows', async () => {
    optimizationMocks.getOptimizationResults.mockResolvedValueOnce(null)
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    vm.resultRows = [{ params: { stale: 1 } }]
    vm.paramNames = ['stale']
    vm.selectedAnalysisParams = ['stale']

    await vm.loadResults()

    expect(vm.resultRows).toEqual([])
    expect(vm.paramNames).toEqual([])
    expect(vm.selectedAnalysisParams).toEqual([])
    expect(vm.optimizationTaskId).toBe('')
    expect(vm.loading).toBe(false)
  })

  it('clears loading and stale result state when both optimization endpoints reject', async () => {
    optimizationMocks.getOptimizationProgress.mockRejectedValueOnce(new Error('progress offline'))
    optimizationMocks.getOptimizationResults.mockRejectedValueOnce(new Error('results offline'))
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    vm.resultRows = [{ params: { stale: 1 } }]
    vm.paramNames = ['stale']
    vm.selectedAnalysisParams = ['stale']

    await vm.loadResults()

    expect(optimizationMocks.getOptimizationProgress).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(optimizationMocks.getOptimizationResults).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(vm.resultRows).toEqual([])
    expect(vm.paramNames).toEqual([])
    expect(vm.selectedAnalysisParams).toEqual([])
    expect(vm.loading).toBe(false)
  })

  it('loads a JSON optimization profile and saves the same selected result as a download', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    vm.selectedUnitId = 'profile-12345678'

    const createElement = document.createElement.bind(document)
    const input = createElement('input') as HTMLInputElement
    const inputClick = vi.spyOn(input, 'click').mockImplementation(() => undefined)
    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation(
      ((tagName: string, options?: ElementCreationOptions) => (
        tagName === 'input' ? input : createElement(tagName, options)
      )) as typeof document.createElement,
    )
    const createUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:optimization-profile')
    const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const clicked: HTMLAnchorElement[] = []
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push(this)
    })
    try {
      vm.handleOpenFile()
      expect(input.type).toBe('file')
      expect(input.accept).toBe('.json')
      expect(inputClick).toHaveBeenCalledOnce()

      const profile = {
        task_id: 'profile-task',
        objective: 'total_return',
        direction: 'maximize',
        tie_break: 'lowest_trial_index',
        best: { result_index: 0, params: { fast: 5 }, total_return: 12 },
        param_names: ['fast'],
        results: [{ result_index: 0, params: { fast: 5 }, total_return: 12, trading_days: 120 }],
      }
      expect(input.onchange).toBeTypeOf('function')
      await input.onchange?.call(input, {
        target: { files: [{ text: vi.fn().mockResolvedValue(JSON.stringify(profile)) }] },
      } as unknown as Event)

      expect(vm.resultRows).toEqual(profile.results)
      expect(vm.paramNames).toEqual(['fast'])
      expect(vm.optimizationTaskId).toBe('profile-task')
      expect(vm.backendBestRow.result_index).toBe(0)
      expect(vm.sortKey).toBe('total_return')
      expect(vm.sortDir).toBe('desc')
      expect(ElMessage.success).toHaveBeenCalledWith('optimization.loaded 1 optimization.nResultsCount')

      vm.handleSaveResults()

      expect(createUrl).toHaveBeenCalledOnce()
      const [blob] = createUrl.mock.calls[0]
      expect(JSON.parse(await (blob as Blob).text())).toMatchObject({
        unit_id: 'profile-12345678',
        task_id: 'profile-task',
        objective: 'total_return',
        direction: 'maximize',
        tie_break: 'lowest_trial_index',
        best: profile.best,
        param_names: ['fast'],
        results: profile.results,
      })
      expect(clicked).toHaveLength(1)
      expect(clicked[0].download).toMatch(/^opt_results_profile-_\d{4}-\d{2}-\d{2}\.json$/)
      expect(revokeUrl).toHaveBeenCalledWith('blob:optimization-profile')
    } finally {
      createElementSpy.mockRestore()
      createUrl.mockRestore()
      revokeUrl.mockRestore()
      anchorClick.mockRestore()
      inputClick.mockRestore()
    }
  })

  it('warns on unsupported optimization profiles and reports malformed JSON', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    const createElement = document.createElement.bind(document)
    const input = createElement('input') as HTMLInputElement
    vi.spyOn(input, 'click').mockImplementation(() => undefined)
    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation(
      ((tagName: string, options?: ElementCreationOptions) => (
        tagName === 'input' ? input : createElement(tagName, options)
      )) as typeof document.createElement,
    )
    try {
      vm.handleOpenFile()
      await input.onchange?.call(input, {
        target: { files: [{ text: vi.fn().mockResolvedValue(JSON.stringify({ rows: [] })) }] },
      } as unknown as Event)
      expect(ElMessage.warning).toHaveBeenCalledWith('optimization.fileFormatErr')

      vm.handleOpenFile()
      await input.onchange?.call(input, {
        target: { files: [{ text: vi.fn().mockResolvedValue('{broken json') }] },
      } as unknown as Event)
      expect(ElMessage.error).toHaveBeenCalledWith('optimization.readFileFailed')
      expect(vm.loading).toBe(false)
    } finally {
      createElementSpy.mockRestore()
      vi.restoreAllMocks()
    }
  })

  it('clears loading when no unit is selected and clears an invalid selected result', async () => {
    const vm = doMount().vm as any
    vm.selectedUnitId = ''
    vm.resultRows = [{ params: { stale: 1 } }]
    vm.selectedAnalysisParams = ['stale']

    await vm.loadResults()
    expect(optimizationMocks.getOptimizationResults).not.toHaveBeenCalled()
    expect(vm.resultRows).toEqual([])
    expect(vm.loading).toBe(false)

    vm.resultRows = [{ result_index: 1, params: { fast: 5 } }]
    vm.handleSelectResult({ __workspaceSourceIndex: 9 })
    expect(vm.selectedResult).toBe(null)
  })

  it('persists the active optimization display settings and reports save failures', async () => {
    const vm = doMount().vm as any
    vm.sortKey = 'total_return'
    vm.sortDir = 'asc'
    vm.viewMode = 'analysis'
    vm.calcMethod = 'compound'
    vm.annualDays = 365
    vm.statTimeRange = ['2025-01-01', '2025-12-31']
    vm.visibleFields = ['total_return', 'sharpe_ratio']
    vm.selectedAnalysisParams = ['fast', 'slow']
    vm.analysisMetric = 'total_return'

    await vm.handleSetDefault()

    expect(optimizationMocks.update).toHaveBeenCalledWith('ws-1', {
      settings: {
        optimization_config: {
          sort_key: 'total_return',
          sort_dir: 'asc',
          view_mode: 'analysis',
          calc_method: 'compound',
          annual_days: 365,
          stat_time_range: ['2025-01-01', '2025-12-31'],
          visible_fields: ['total_return', 'sharpe_ratio'],
          analysis_params: ['fast', 'slow'],
          analysis_metric: 'total_return',
        },
      },
    })
    expect(ElMessage.success).toHaveBeenCalledWith('optimization.savedAsDefault')

    optimizationMocks.update.mockRejectedValueOnce(new Error('write rejected'))
    await vm.handleSetDefault()
    expect(ElMessage.error).toHaveBeenCalledWith('optimization.saveDefaultFailed')
  })

  it('cancels the selected optimization and reloads its results', async () => {
    const vm = doMount().vm as any

    await vm.handleCancel()
    expect(optimizationMocks.cancelOptimization).not.toHaveBeenCalled()

    vm.selectedUnitId = 'u-1'
    await vm.handleCancel()

    expect(optimizationMocks.cancelOptimization).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(optimizationMocks.getOptimizationResults).toHaveBeenCalledWith('ws-1', 'u-1')
    expect(ElMessage.success).toHaveBeenCalledWith('optimization.optimizationCancelled')
  })

  it('applies row parameters without losing existing parameters and reports an empty run result', async () => {
    let finishRun!: (value: unknown) => void
    optimizationMocks.runUnits.mockImplementationOnce(
      () => new Promise(resolve => { finishRun = resolve }),
    )
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    const row = { result_index: 2, params: { fast: 7 } }

    const run = vm.handleRunWithParams(row)
    await flushPromises()

    expect(optimizationMocks.updateUnit).toHaveBeenCalledWith('ws-1', 'u-1', {
      params: { slow: 20, fast: 7 },
    })
    expect(optimizationMocks.runUnits).toHaveBeenCalledWith('ws-1', ['u-1'], false)
    expect(vm.runningRow).not.toBe(row)
    expect(isReactive(vm.runningRow)).toBe(true)

    finishRun({ results: [] })
    await run

    expect(ElMessage.warning).toHaveBeenCalledWith('optimization.backtestNoTask')
    expect(vm.runningRow).toBe(null)
  })

  it('keeps a submitted row active until its backtest completes, then clears it and navigates', async () => {
    vi.useFakeTimers()
    optimizationMocks.runUnits.mockResolvedValueOnce({ results: [{ task_id: 'bt-9' }] })
    optimizationMocks.getUnitsStatus.mockResolvedValueOnce([
      { id: 'u-1', run_status: 'completed', last_task_id: 'bt-9' },
    ])
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    const row = { result_index: 3, params: { fast: 9 } }

    await vm.handleRunWithParams(row)

    expect(vm.runningRow).toMatchObject(row)
    expect(ElMessage.success).toHaveBeenCalledWith(
      'optimization.backtestSubmitted，optimization.waitingNavigate',
    )

    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()

    expect(optimizationMocks.getUnitsStatus).toHaveBeenCalledWith('ws-1')
    expect(vm.runningRow).toBe(null)
    expect(optimizationMocks.routerPush).toHaveBeenCalledWith({
      name: 'BacktestResult',
      params: { id: 'bt-9' },
      query: {
        workspaceId: 'ws-1',
        unitId: 'u-1',
        strategyName: 'Alpha',
      },
    })
  })

  it('clears the active row and reports a rejected backtest submission', async () => {
    let rejectRun!: (reason?: unknown) => void
    optimizationMocks.runUnits.mockImplementationOnce(
      () => new Promise((_resolve, reject) => { rejectRun = reject }),
    )
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    const row = { result_index: 5, params: { fast: 11 } }

    const run = vm.handleRunWithParams(row)
    await flushPromises()

    expect(optimizationMocks.updateUnit).toHaveBeenCalledWith('ws-1', 'u-1', {
      params: { slow: 20, fast: 11 },
    })
    expect(optimizationMocks.runUnits).toHaveBeenCalledWith('ws-1', ['u-1'], false)
    expect(vm.runningRow).not.toBe(row)
    expect(isReactive(vm.runningRow)).toBe(true)

    rejectRun(new Error('worker unavailable'))
    await run

    expect(ElMessage.error).toHaveBeenCalledWith('optimization.submitBacktestFailed')
    expect(vm.runningRow).toBe(null)
  })

  it('does not let a late response for an older row clear the newer active row', async () => {
    let finishFirstUpdate!: (value: unknown) => void
    let finishSecondUpdate!: (value: unknown) => void
    const firstUpdate = new Promise(resolve => { finishFirstUpdate = resolve })
    const secondUpdate = new Promise(resolve => { finishSecondUpdate = resolve })
    optimizationMocks.updateUnit
      .mockImplementationOnce(() => firstUpdate)
      .mockImplementationOnce(() => secondUpdate)
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'

    const firstRow = { result_index: 1, params: { fast: 1 } }
    const secondRow = { result_index: 2, params: { fast: 2 } }
    const firstRun = vm.handleRunWithParams(firstRow)
    const secondRun = vm.handleRunWithParams(secondRow)
    expect(vm.runningRow).toMatchObject(secondRow)

    finishFirstUpdate(undefined)
    await firstRun
    expect(vm.runningRow).toMatchObject(secondRow)

    finishSecondUpdate(undefined)
    await secondRun
    expect(vm.runningRow).toBe(null)
    expect(optimizationMocks.runUnits).toHaveBeenCalledTimes(2)
    expect(ElMessage.warning).toHaveBeenCalledTimes(2)
  })

  it('stops progress polling on unmount and ignores its in-flight response', async () => {
    vi.useFakeTimers()
    let finishProgress!: (value: unknown) => void
    optimizationMocks.getOptimizationProgress
      .mockResolvedValueOnce({ status: 'running', total: 4, completed: 1, failed: 0 })
      .mockImplementationOnce(() => new Promise(resolve => { finishProgress = resolve }))
    optimizationMocks.getOptimizationResults.mockResolvedValueOnce({ rows: [], status: 'running' })
    const wrapper = doMount()
    const vm = wrapper.vm as any
    vm.selectedUnitId = 'u-1'
    await vm.loadResults()
    await nextTick()

    expect(vi.getTimerCount()).toBe(1)
    await vi.advanceTimersByTimeAsync(3000)
    expect(optimizationMocks.getOptimizationProgress).toHaveBeenCalledTimes(2)

    wrapper.unmount()
    mountedWrappers.delete(wrapper)
    expect(vi.getTimerCount()).toBe(0)

    finishProgress({ status: 'completed', total: 4, completed: 4, failed: 0 })
    await flushPromises()
    expect(vm.optimizationStatus).toBe('running')

    await vi.advanceTimersByTimeAsync(6000)
    expect(optimizationMocks.getOptimizationProgress).toHaveBeenCalledTimes(2)
  })

  it('clears backtest polling and timeout timers when unmounted', async () => {
    vi.useFakeTimers()
    optimizationMocks.runUnits.mockResolvedValueOnce({ results: [{ task_id: 'bt-pending' }] })
    const wrapper = doMount()
    const vm = wrapper.vm as any
    vm.selectedUnitId = 'u-1'

    await vm.handleRunWithParams({ result_index: 6, params: { fast: 13 } })

    expect(vm.runningRow).toMatchObject({ result_index: 6, params: { fast: 13 } })
    expect(vi.getTimerCount()).toBe(2)

    wrapper.unmount()
    mountedWrappers.delete(wrapper)
    expect(vi.getTimerCount()).toBe(0)
    await vi.advanceTimersByTimeAsync(6000)
    expect(optimizationMocks.getUnitsStatus).not.toHaveBeenCalled()
  })

  it('opens an existing optimization artifact directly in its task report', async () => {
    const vm = doMount().vm as any
    vm.selectedUnitId = 'u-1'
    vm.optimizationTaskId = 'opt-task-9'

    await vm.handleRunWithParams({ result_index: 4, artifact_path: '/reports/4.json' })

    expect(optimizationMocks.routerPush).toHaveBeenCalledWith({
      name: 'BacktestResult',
      params: { id: 'opt-task-9' },
      query: {
        workspaceId: 'ws-1',
        optimizationUnitId: 'u-1',
        optimizationResultIndex: '4',
      },
    })
    expect(optimizationMocks.updateUnit).not.toHaveBeenCalled()
    expect(optimizationMocks.runUnits).not.toHaveBeenCalled()
  })
})
