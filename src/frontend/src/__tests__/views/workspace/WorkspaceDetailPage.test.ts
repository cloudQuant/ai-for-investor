import { describe, it, expect, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { reactive } from 'vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string, params?: Record<string, unknown>) => {
    if (!params) return key
    return `${key}:${JSON.stringify(params)}`
  } }),
}))

const route = reactive({
  params: { id: 'workspace-1' },
  meta: { workspaceType: 'research' },
})

vi.mock('vue-router', () => ({
  useRoute: () => route,
  useRouter: () => ({ push: vi.fn() }),
}))

const fetchWorkspace = vi.fn().mockResolvedValue(undefined)
const fetchUnits = vi.fn().mockResolvedValue(undefined)
let storeState: any
const activateWorkspace = vi.fn((id: string) => {
  if (storeState.activeWorkspaceId === id) return
  storeState.activeWorkspaceId = id
  storeState.currentWorkspace = null
  storeState.units = []
  storeState.selectedUnitIds = []
  storeState.loading = true
})

vi.mock('@/stores/workspace', () => ({
  useWorkspaceStore: () => storeState,
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    getOptimizationProgress: vi.fn().mockResolvedValue({
      status: 'idle',
      total: 0,
      completed: 0,
      failed: 0,
    }),
    getOptimizationResults: vi.fn().mockResolvedValue({ rows: [] }),
  },
}))

import WorkspaceDetailPage from '@/views/workspace/WorkspaceDetailPage.vue'
import { elStubs } from '@/test/stubs'

function buildWorkspace(overrides: Record<string, unknown> = {}) {
  return {
    id: 'workspace-1',
    user_id: 'user-1',
    name: 'Alpha Research',
    description: 'A compact research workspace.',
    workspace_type: 'research',
    settings: { data_source: { type: 'mysql' } },
    trading_config: {},
    unit_count: 3,
    completed_count: 1,
    status: 'running',
    created_at: '2026-06-20T09:30:00Z',
    updated_at: '2026-07-01T02:20:00Z',
    ...overrides,
  }
}

function buildUnit(id: string, runStatus = 'idle', overrides: Record<string, unknown> = {}) {
  return {
    id,
    workspace_id: 'workspace-1',
    group_name: 'default',
    strategy_id: null,
    strategy_name: 'Trend',
    symbol: '000001.SZ',
    symbol_name: 'Ping An',
    timeframe: '1d',
    timeframe_n: 1,
    category: 'trend',
    sort_order: 0,
    data_config: {},
    unit_settings: {},
    params: {},
    optimization_config: {},
    trading_mode: 'paper',
    gateway_config: {},
    lock_trading: false,
    lock_running: false,
    trading_instance_id: null,
    trading_snapshot: {},
    run_status: runStatus,
    run_count: 1,
    last_run_time: null,
    last_task_id: null,
    last_optimization_task_id: null,
    bar_count: null,
    metrics_snapshot: {},
    created_at: '2026-06-20T09:30:00Z',
    updated_at: '2026-07-01T02:20:00Z',
    ...overrides,
  }
}

function doMount() {
  return mount(WorkspaceDetailPage, {
    global: {
      stubs: {
        ...elStubs,
        WorkspaceDataSourceDialog: true,
        WorkspaceReportTab: {
          props: ['workspaceId', 'active', 'initialUnitId', 'initialUnitIds'],
          template: '<div data-test="report-tab" :data-workspace-id="workspaceId" :data-active="active" :data-initial-unit-id="initialUnitId" :data-initial-unit-ids="initialUnitIds.join(\',\')">report</div>',
        },
        TradingWorkspaceUnitsTab: { template: '<div data-test="trading-units-tab">trading units</div>' },
        WorkspaceUnitsTab: {
          props: ['workspaceId'],
          emits: ['switch-tab'],
          template: '<div><button data-test="units-tab" :data-workspace-id="workspaceId" @click="$emit(\'switch-tab\', \'optimization\', \'unit-1\')">units</button><button data-test="units-report-multi" @click="$emit(\'switch-tab\', \'report\', \'unit-1\', [\'unit-1\', \'unit-3\'])">report multi</button><button data-test="units-report-single" @click="$emit(\'switch-tab\', \'report\', \'unit-2\')">report single</button><button data-test="units-report-all" @click="$emit(\'switch-tab\', \'report\')">report all</button></div>',
        },
      },
    },
  })
}

describe('WorkspaceDetailPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    fetchWorkspace.mockReset().mockResolvedValue(undefined)
    fetchUnits.mockReset().mockResolvedValue(undefined)
    route.params.id = 'workspace-1'
    route.meta.workspaceType = 'research'
    storeState = {
      loading: false,
      activeWorkspaceId: 'workspace-1',
      currentWorkspace: buildWorkspace(),
      units: [
        buildUnit('unit-1', 'running'),
        buildUnit('unit-2', 'completed'),
        buildUnit('unit-3', 'idle'),
      ],
      fetchWorkspace,
      fetchUnits,
      activateWorkspace,
    }
  })

  it('fetches workspace detail and units from the route id', async () => {
    doMount()
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(fetchWorkspace).toHaveBeenCalledWith('workspace-1')
    expect(fetchUnits).toHaveBeenCalledWith('workspace-1')
  })

  it('keeps a reused route component and its unit actions bound to the new workspace id', async () => {
    fetchWorkspace.mockImplementation(async (id: string) => {
      storeState.currentWorkspace = buildWorkspace({ id, name: 'Beta Workspace' })
      storeState.loading = false
    })
    fetchUnits.mockImplementation(async (id: string) => {
      storeState.units = [buildUnit('unit-b', 'idle', { workspace_id: id })]
      storeState.loading = false
    })

    const wrapper = doMount()
    const vm = wrapper.vm
    route.params.id = 'workspace-2'
    await flushPromises()

    expect(wrapper.vm).toBe(vm)
    expect(activateWorkspace).toHaveBeenCalledWith('workspace-2')
    expect(fetchWorkspace).toHaveBeenCalledWith('workspace-2')
    expect(fetchUnits).toHaveBeenCalledWith('workspace-2')
    expect(wrapper.text()).toContain('Beta Workspace')
    expect(wrapper.text()).not.toContain('Alpha Research')
    expect(wrapper.get('[data-test="units-tab"]').attributes('data-workspace-id')).toBe('workspace-2')
  })

  it('renders the research workspace overview and metrics', () => {
    const wrapper = doMount()
    expect(wrapper.text()).toContain('Alpha Research')
    expect(wrapper.text()).toContain('A compact research workspace.')
    expect(wrapper.findAll('.workspace-detail-metric')).toHaveLength(4)
    expect(wrapper.text()).toContain('MySQL')
    expect(wrapper.find('[data-test="trading-detail-ops"]').exists()).toBe(false)
  })

  it('renders the trading runtime overview for trading workspaces', () => {
    route.meta.workspaceType = 'trading'
    storeState.currentWorkspace = buildWorkspace({
      name: 'Live Ops',
      description: '',
      workspace_type: 'trading',
      settings: {},
      status: 'running',
    })
    storeState.units = [
      buildUnit('unit-1', 'running', {
        trading_mode: 'live',
        gateway_config: { preset_id: 'ctp-sim' },
        trading_instance_id: 'instance-1',
        trading_snapshot: {
          instance_status: 'running',
          today_pnl: 120.5,
          updated_at: '2026-07-01T03:20:00Z',
        },
      }),
      buildUnit('unit-2', 'completed', {
        trading_mode: 'paper',
        gateway_config: {},
        trading_snapshot: {
          instance_status: 'stopped',
          today_pnl: -20,
          updated_at: '2026-07-01T03:00:00Z',
        },
      }),
      buildUnit('unit-3', 'idle', {
        trading_mode: 'live',
        gateway_config: { name: 'ibkr' },
        lock_running: true,
        trading_snapshot: {
          instance_status: 'idle',
          today_pnl: 0,
          updated_at: '2026-07-01T02:50:00Z',
        },
      }),
    ]

    const wrapper = doMount()
    expect(wrapper.find('[data-test="trading-detail-ops"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="trading-units-tab"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="units-tab"]').exists()).toBe(false)
    expect(wrapper.findAll('.trading-detail-ops-card')).toHaveLength(4)
    expect(wrapper.text()).toContain('workspaceDetail.tradingOpsTitle')
    expect(wrapper.text()).toContain('workspaceDetail.tradingReadinessReview')
    expect(wrapper.text()).toContain('+100.50')
  })

  it('opens the optimization tab when a unit tab requests it', async () => {
    const wrapper = doMount()
    await wrapper.get('[data-test="units-tab"]').trigger('click')
    await flushPromises()
    await vi.dynamicImportSettled()
    await flushPromises()
    expect((wrapper.vm as any).activeTab).toBe('optimization')
    expect((wrapper.vm as any).showOptTab).toBe(true)
    expect(wrapper.find('.workspace-optimization-tab').exists()).toBe(true)
    wrapper.unmount()
  })

  it('shows the not-found empty state', () => {
    storeState.currentWorkspace = null
    storeState.units = []
    const wrapper = doMount()
    expect(wrapper.find('.workspace-detail-empty').exists()).toBe(true)
  })

  it('passes multi-unit report selection through from the units tab', async () => {
    const wrapper = doMount()
    await wrapper.get('[data-test="units-report-multi"]').trigger('click')
    await flushPromises()

    const reportTab = wrapper.get('[data-test="report-tab"]')
    expect((wrapper.vm as any).activeTab).toBe('report')
    expect(reportTab.attributes('data-workspace-id')).toBe('workspace-1')
    expect(reportTab.attributes('data-initial-unit-id')).toBe('unit-1')
    expect(reportTab.attributes('data-initial-unit-ids')).toBe('unit-1,unit-3')
  })

  it('falls back to a single selected unit and then to all units when opening reports', async () => {
    const wrapper = doMount()
    await wrapper.get('[data-test="units-report-single"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="report-tab"]').attributes('data-initial-unit-ids')).toBe('unit-2')

    await wrapper.get('[data-test="units-report-all"]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-test="report-tab"]').attributes('data-initial-unit-id')).toBe('unit-2')
    expect(wrapper.get('[data-test="report-tab"]').attributes('data-initial-unit-ids')).toBe('')
  })

  it('shows data-source configuration for research workspaces but hides it for trading workspaces', () => {
    const research = doMount()
    expect(research.find('.workspace-detail-actions button').exists()).toBe(true)

    storeState.currentWorkspace = buildWorkspace({ workspace_type: 'trading' })
    route.meta.workspaceType = 'trading'
    const trading = doMount()
    expect(trading.find('.workspace-detail-actions button').exists()).toBe(false)
    expect(trading.find('[data-test="trading-detail-ops"]').exists()).toBe(true)
  })

  it('does not show stale workspace data after the routed workspace has no lookup result', async () => {
    fetchWorkspace.mockImplementation(async () => {
      storeState.currentWorkspace = null
      storeState.loading = false
    })
    route.params.id = 'workspace-2'
    const wrapper = doMount()
    await flushPromises()

    expect(fetchWorkspace).toHaveBeenCalledWith('workspace-2')
    expect(wrapper.find('.workspace-detail-empty').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('Alpha Research')
  })
})
