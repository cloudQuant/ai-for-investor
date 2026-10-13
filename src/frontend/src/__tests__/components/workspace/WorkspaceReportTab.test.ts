import { afterEach, describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import type { WorkspaceReportResponse, WorkspaceReportUnitRow } from '@/types/workspace'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
  ElMessageBox: { confirm: vi.fn().mockResolvedValue('confirm') },
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    getReport: vi.fn(),
    createReport: vi.fn(),
    update: vi.fn().mockResolvedValue(undefined),
    deleteReport: vi.fn().mockResolvedValue(undefined),
  },
}))

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
  getErrorMessage: (_e: unknown, fallback: string) => fallback,
}))

const units = [
  { id: 'u-1', strategy_name: 'Alpha', strategy_id: 's-1' },
  { id: 'u-2', strategy_name: '', strategy_id: 's-2' },
]

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => ({
    units,
    currentWorkspace: { settings: {} },
  }),
}))

import WorkspaceReportTab from '@/components/workspace/WorkspaceReportTab.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { workspaceApi } from '@/api/workspace'
import { elStubs } from '@/test/stubs'

function buildReportUnit(
  id: string,
  overrides: Partial<WorkspaceReportUnitRow> = {},
): WorkspaceReportUnitRow {
  return {
    id,
    strategy_name: 'Trend',
    symbol: '000001.SZ',
    symbol_name: 'Ping An',
    timeframe: '1d',
    group_name: 'default',
    category: 'trend',
    run_status: 'completed',
    run_count: 1,
    last_run_time: null,
    last_task_id: null,
    start_date: null,
    data_source: 'mysql',
    ...overrides,
  }
}

function buildReport(units: WorkspaceReportUnitRow[] = []): WorkspaceReportResponse {
  return {
    workspace_id: 'ws-1',
    workspace_name: 'Alpha Research',
    summary: {
      total_units: units.length,
      completed_units: units.filter(unit => unit.run_status === 'completed' || unit.last_task_id).length,
      avg_total_return: null,
      avg_annual_return: null,
      avg_sharpe_ratio: null,
      avg_max_drawdown: null,
      avg_win_rate: null,
      total_trades: null,
      best_return_unit: null,
      worst_drawdown_unit: null,
      config: {},
    },
    units,
  }
}

function doMount(props: Record<string, unknown> = {}) {
  return mount(WorkspaceReportTab, {
    props: { workspaceId: 'ws-1', ...props },
    global: { stubs: elStubs },
  })
}

describe('WorkspaceReportTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(workspaceApi.getReport).mockResolvedValue(buildReport())
    vi.mocked(workspaceApi.createReport).mockResolvedValue(buildReport())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('mounts cleanly', () => {
    expect(doMount().exists()).toBe(true)
  })

  it('fmtPct formats percentages and handles null', () => {
    const vm = doMount().vm as any
    expect(vm.fmtPct(12.345)).toBe('12.35%')
    expect(vm.fmtPct(null)).toBe('-')
    expect(vm.fmtPct(undefined)).toBe('-')
  })

  it('fmtNum formats to 2 decimals and handles null', () => {
    const vm = doMount().vm as any
    expect(vm.fmtNum(3.14159)).toBe('3.14')
    expect(vm.fmtNum(null)).toBe('-')
  })

  it('fmtVal formats numbers to 4 decimals, passes strings through', () => {
    const vm = doMount().vm as any
    expect(vm.fmtVal(1.23456)).toBe('1.2346')
    expect(vm.fmtVal('abc')).toBe('abc')
    expect(vm.fmtVal(null)).toBe('-')
  })

  it('fmtMoney formats numbers with locale and passes strings', () => {
    const vm = doMount().vm as any
    expect(vm.fmtMoney(null)).toBe('-')
    expect(vm.fmtMoney('n/a')).toBe('n/a')
    expect(typeof vm.fmtMoney(1234567.89)).toBe('string')
  })

  it('returnColor maps sign to a tailwind class', () => {
    const vm = doMount().vm as any
    expect(vm.returnColor(1)).toBe('text-green-500')
    expect(vm.returnColor(-1)).toBe('text-red-500')
    expect(vm.returnColor(0)).toBe('text-green-500')
    expect(vm.returnColor(null)).toBe('')
  })

  it('weightModeLabel reflects the weight mode', () => {
    const vm = doMount().vm as any
    expect(vm.weightModeLabel).toBe('report.weightEqual')
    vm.weightMode = 'custom'
    expect(vm.weightModeLabel).toBe('report.weightCustom')
  })

  it('formatRangeValue slices ISO dates and stringifies others', () => {
    const vm = doMount().vm as any
    expect(vm.formatRangeValue('')).toBe('')
    expect(vm.formatRangeValue('2024-01-15T09:00:00')).toBe('2024-01-15')
    expect(vm.formatRangeValue('plain')).toBe('plain')
  })

  it('statRangeLabel uses fullRange when no range set', () => {
    const vm = doMount().vm as any
    expect(vm.statRangeLabel).toBe('report.fullRange')
    vm.reportStatRange = ['2024-01-01', '2024-02-01']
    expect(vm.statRangeLabel).toContain('~')
  })

  it('selectedUnitNames maps ids to names with fallback', () => {
    const vm = doMount().vm as any
    vm.selectedReportUnitIds = ['u-1', 'u-2', 'u-x']
    const names = vm.selectedUnitNames
    expect(names).toContain('Alpha')
    expect(names).toContain('s-2') // u-2 has empty strategy_name -> strategy_id
    expect(names).toContain('u-x') // unknown id -> itself
  })

  it('filteredUnits returns all when no selection, subset otherwise', () => {
    const vm = doMount().vm as any
    vm.report = { units: [{ id: 'u-1' }, { id: 'u-2' }], summary: {} }
    expect(vm.filteredUnits).toHaveLength(2)
    vm.selectedReportUnitIds = ['u-1']
    expect(vm.filteredUnits).toHaveLength(1)
  })

  it('renders an empty-report state after a successful fetch with no unit rows', async () => {
    vi.mocked(workspaceApi.getReport).mockResolvedValueOnce(buildReport())
    const wrapper = doMount()
    await flushPromises()

    expect(workspaceApi.getReport).toHaveBeenCalledWith('ws-1')
    expect((wrapper.vm as any).filteredSummary).toMatchObject({ total_units: 0, completed_units: 0 })
    expect(wrapper.find('.el-empty').exists()).toBe(true)
  })

  it('shows the empty fallback when report loading fails and preserves a useful error', async () => {
    vi.mocked(workspaceApi.getReport).mockRejectedValueOnce(new Error('offline'))
    const wrapper = doMount()
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('report.loadFailed')
    expect((wrapper.vm as any).report).toBeNull()
    expect(wrapper.find('.el-empty').exists()).toBe(true)
  })

  it('keeps missing metrics null instead of rendering invalid numeric values', async () => {
    vi.mocked(workspaceApi.getReport).mockResolvedValueOnce({
      ...buildReport([buildReportUnit('u-1', { strategy_name: 'Alpha' })]),
    })
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.filteredSummary).toMatchObject({
      total_units: 1,
      completed_units: 1,
      avg_total_return: null,
      avg_annual_return: null,
      total_trades: null,
    })
    expect(wrapper.text()).not.toContain('NaN')
  })

  it('submits the selected date range and calculation settings, then shows the returned report', async () => {
    const nextReport = buildReport([buildReportUnit('u-1', { strategy_name: 'Alpha', total_return: 12.5 })])
    vi.mocked(workspaceApi.createReport).mockResolvedValueOnce(nextReport)
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    vm.reportStatRange = ['2026-01-01', '2026-06-30']
    vm.reportCalcMethod = 'compound'
    vm.reportAnnualDays = 365
    vm.weightMode = 'custom'
    vm.maxCash = 250000

    await vm.recalculateReport()

    expect(workspaceApi.createReport).toHaveBeenCalledWith('ws-1', {
      calc_method: 'compound',
      annual_days: 365,
      weight_mode: 'custom',
      max_cash: 250000,
      start_date: '2026-01-01',
      end_date: '2026-06-30',
    })
    expect(vm.report).toMatchObject(nextReport)
    expect(ElMessage.success).toHaveBeenCalledWith('report.recalculated')
  })

  it('exports the displayed report as a downloadable JSON blob', async () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:report')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const wrapper = doMount()
    await flushPromises()
    const vm = wrapper.vm as any
    const report = buildReport([buildReportUnit('u-1', { total_return: 8.2 })])
    vm.report = report

    vm.handleSaveReport()

    expect(createObjectURL).toHaveBeenCalledTimes(1)
    const blob = createObjectURL.mock.calls[0][0] as Blob
    expect(blob.type).toBe('application/json')
    await expect(blob.text()).resolves.toContain('"total_return": 8.2')
    expect(click).toHaveBeenCalledTimes(1)
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:report')
    expect(ElMessage.success).toHaveBeenCalledWith('report.saved')
  })

  it('treats a canceled report deletion as a no-op', async () => {
    vi.mocked(ElMessageBox.confirm).mockRejectedValueOnce('cancel')
    const wrapper = doMount()
    await flushPromises()

    await (wrapper.vm as any).handleDeleteReport()

    expect(workspaceApi.deleteReport).not.toHaveBeenCalled()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })
})
