import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import UnitRuntimeDialog from '@/components/workspace/UnitRuntimeDialog.vue'
import { workspaceApi } from '@/api/workspace'
import { ElMessage } from 'element-plus'
import type {
  StrategyUnit,
  StrategyUnitRuntimeFile,
  StrategyUnitRuntimeInfo,
  TradingSnapshot,
} from '@/types/workspace'
import { elStubs } from '@/test/stubs'

const runtimeApiMocks = vi.hoisted(() => ({
  getUnitRuntimeInfo: vi.fn(),
  getUnitRuntimeFile: vi.fn(),
  openUnitRuntimeDir: vi.fn(),
}))

vi.mock('@/api/workspace', () => ({ workspaceApi: runtimeApiMocks }))
vi.mock('@/api/index', () => ({
  default: {},
  getErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}))
vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn() },
}))

const dialogStub = defineComponent({
  name: 'RuntimeDialogStub',
  props: ['modelValue'],
  emits: ['close', 'update:modelValue'],
  setup(props, { emit, slots }) {
    return () => props.modelValue
      ? h('section', { class: 'dialog-harness' }, [
          h('button', {
            type: 'button',
            'data-test': 'dialog-close',
            onClick: () => {
              emit('close')
              emit('update:modelValue', false)
            },
          }, 'Close dialog'),
          h('div', { 'data-test': 'dialog-content' }, slots.default?.()),
        ])
      : h('section', { class: 'dialog-harness', 'data-test': 'dialog-hidden' })
  },
})

const selectStub = defineComponent({
  name: 'RuntimeSelectStub',
  props: ['modelValue', 'placeholder', 'loading'],
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    return () => h('select', {
      class: 'runtime-select',
      value: props.modelValue ?? '',
      'aria-label': props.placeholder,
      onChange: (event: Event) => {
        const rawValue = (event.target as HTMLSelectElement).value
        const value = rawValue !== '' && Number.isFinite(Number(rawValue))
          ? Number(rawValue)
          : rawValue
        emit('update:modelValue', value)
        emit('change', value)
      },
    }, slots.default?.())
  },
})

const optionStub = defineComponent({
  name: 'RuntimeOptionStub',
  props: ['label', 'value'],
  setup(props, { slots }) {
    return () => h('option', { value: props.value ?? '' }, slots.default?.() ?? String(props.label ?? ''))
  },
})

const fileTagStub = defineComponent({
  name: 'RuntimeFileTagStub',
  emits: ['click'],
  setup(_props, { emit, slots }) {
    return () => h('button', {
      type: 'button',
      'data-test': 'file-tag',
      onClick: () => emit('click'),
    }, slots.default?.())
  },
})

const runtimeStubs = {
  ...elStubs,
  'el-dialog': dialogStub,
  'el-select': selectStub,
  'el-option': optionStub,
  'el-tag': fileTagStub,
}

const snapshot: TradingSnapshot = {
  instance_id: null,
  instance_status: '',
  mode: 'paper',
  error: null,
  started_at: null,
  stopped_at: null,
  gateway_summary: null,
  long_position: 0,
  short_position: 0,
  today_pnl: null,
  position_pnl: null,
  latest_price: null,
  change_pct: null,
  long_market_value: null,
  short_market_value: null,
  leverage: null,
  cumulative_pnl: null,
  max_drawdown_rate: null,
  trading_day: null,
  updated_at: null,
  detail_route: null,
  positions: [],
  trades: [],
}

const unit: StrategyUnit = {
  id: 'unit-1',
  workspace_id: 'workspace-1',
  group_name: 'default',
  strategy_id: 'mean-reversion',
  strategy_name: '',
  symbol: 'IF2612',
  symbol_name: '沪深300',
  timeframe: '1m',
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
  trading_snapshot: snapshot,
  run_status: 'running',
  run_count: 1,
  last_run_time: null,
  last_task_id: null,
  last_optimization_task_id: null,
  bar_count: null,
  metrics_snapshot: {},
  created_at: '2026-10-01T00:00:00Z',
  updated_at: '2026-10-01T00:00:00Z',
}

const runtimeFiles: StrategyUnitRuntimeFile[] = [
  { name: 'runner', relative_path: 'run.py', size: 4, kind: 'file' },
  { name: 'system log', relative_path: 'logs/system.log', size: 1536, kind: 'file' },
  { name: 'error log', relative_path: 'logs/error.log', size: 2 * 1024 * 1024, kind: 'file' },
  { name: 'config', relative_path: 'config.yaml', size: 15, kind: 'file' },
]

function buildRuntimeInfo(files: StrategyUnitRuntimeFile[] = runtimeFiles): StrategyUnitRuntimeInfo {
  return {
    unit_id: unit.id,
    runtime_dir: '/data/workspaces/workspace-1/unit-1',
    log_dir: null,
    files,
  }
}

const mountedWrappers: Array<{ unmount: () => void }> = []

function mountDialog(props: Record<string, unknown> = {}) {
  const wrapper = mount(UnitRuntimeDialog, {
    props: { modelValue: true, workspaceId: 'workspace-1', unit, ...props },
    global: { stubs: runtimeStubs },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('UnitRuntimeDialog', () => {
  beforeEach(() => {
    vi.mocked(workspaceApi.getUnitRuntimeInfo).mockReset()
    vi.mocked(workspaceApi.getUnitRuntimeFile).mockReset()
    vi.mocked(workspaceApi.openUnitRuntimeDir).mockReset()
    vi.mocked(ElMessage.success).mockReset()
    vi.mocked(ElMessage.error).mockReset()
  })

  afterEach(() => {
    mountedWrappers.splice(0).forEach(wrapper => wrapper.unmount())
  })

  it('loads the unit summary, preferred log, file tail, and open-directory action', async () => {
    vi.mocked(workspaceApi.getUnitRuntimeInfo).mockResolvedValue(buildRuntimeInfo())
    vi.mocked(workspaceApi.getUnitRuntimeFile).mockImplementation(async (_workspaceId, _unitId, path, tail) =>
      `${path} content (tail=${tail ?? 'all'})`,
    )
    vi.mocked(workspaceApi.openUnitRuntimeDir).mockResolvedValue({
      unit_id: unit.id,
      runtime_dir: '/data/workspaces/workspace-1/unit-1',
      message: 'runtime directory opened',
    })

    const wrapper = mountDialog()
    await flushPromises()

    expect(workspaceApi.getUnitRuntimeInfo).toHaveBeenCalledWith('workspace-1', 'unit-1')
    expect(workspaceApi.getUnitRuntimeFile).toHaveBeenCalledWith(
      'workspace-1', 'unit-1', 'logs/error.log', 500,
    )
    expect(wrapper.text()).toContain('mean-reversion')
    expect(wrapper.text()).toContain('IF2612 / 1m')
    expect(wrapper.text()).toContain('running')
    expect(wrapper.text()).toContain('未分配实例')
    expect(wrapper.text()).toContain('/data/workspaces/workspace-1/unit-1')
    expect(wrapper.text()).toContain('1.5 KB')
    expect(wrapper.text()).toContain('2.0 MB')
    expect(wrapper.text()).toContain('4 B')
    expect(wrapper.find('pre').text()).toBe('logs/error.log content (tail=500)')

    const configTag = wrapper.findAll('[data-test="file-tag"]')
      .find(tag => tag.text() === 'config.yaml')
    expect(configTag).toBeDefined()
    await configTag!.trigger('click')
    await flushPromises()
    expect(workspaceApi.getUnitRuntimeFile).toHaveBeenLastCalledWith(
      'workspace-1', 'unit-1', 'config.yaml', 500,
    )
    expect(wrapper.find('pre').text()).toBe('config.yaml content (tail=500)')

    await wrapper.findAll('select')[1].setValue('200')
    await flushPromises()
    expect(workspaceApi.getUnitRuntimeFile).toHaveBeenLastCalledWith(
      'workspace-1', 'unit-1', 'config.yaml', 200,
    )
    expect(wrapper.find('pre').text()).toBe('config.yaml content (tail=200)')

    await wrapper.findAll('button.el-button')[0].trigger('click')
    await flushPromises()
    expect(workspaceApi.getUnitRuntimeInfo).toHaveBeenCalledTimes(2)
    expect(workspaceApi.getUnitRuntimeFile).toHaveBeenLastCalledWith(
      'workspace-1', 'unit-1', 'config.yaml', 200,
    )

    await wrapper.findAll('button.el-button')[1].trigger('click')
    await flushPromises()
    expect(workspaceApi.openUnitRuntimeDir).toHaveBeenCalledWith('workspace-1', 'unit-1')
    expect(ElMessage.success).toHaveBeenCalledWith('runtime directory opened')
  })

  it('shows the no-file prompt without requesting a file when runtime info is empty', async () => {
    vi.mocked(workspaceApi.getUnitRuntimeInfo).mockResolvedValue(buildRuntimeInfo([]))

    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('请选择要查看的文件')
    expect(wrapper.find('pre').exists()).toBe(false)
    expect(workspaceApi.getUnitRuntimeFile).not.toHaveBeenCalled()
  })

  it('does not load when closed or when there is no selected unit', async () => {
    const closed = mountDialog({ modelValue: false })
    const missingUnit = mountDialog({ unit: null })
    await flushPromises()

    expect(workspaceApi.getUnitRuntimeInfo).not.toHaveBeenCalled()
    expect(closed.find('[data-test="dialog-content"]').exists()).toBe(false)
    expect(missingUnit.find('[data-test="dialog-content"]').exists()).toBe(true)
    expect(missingUnit.text()).not.toContain('IF2612')
  })

  it('surfaces runtime-info, file-read, and directory-open errors', async () => {
    vi.mocked(workspaceApi.getUnitRuntimeInfo).mockRejectedValueOnce(new Error('runtime unavailable'))
    const wrapper = mountDialog()
    await flushPromises()

    expect(wrapper.text()).toContain('runtime unavailable')
    expect(workspaceApi.getUnitRuntimeFile).not.toHaveBeenCalled()

    vi.mocked(workspaceApi.getUnitRuntimeInfo).mockResolvedValueOnce(buildRuntimeInfo())
    vi.mocked(workspaceApi.getUnitRuntimeFile).mockRejectedValueOnce(new Error('log unreadable'))
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    expect(wrapper.text()).toContain('log unreadable')
    expect(wrapper.find('pre').exists()).toBe(false)

    vi.mocked(workspaceApi.openUnitRuntimeDir).mockRejectedValueOnce(new Error('open denied'))
    await wrapper.findAll('button.el-button')[1].trigger('click')
    await flushPromises()
    expect(ElMessage.error).toHaveBeenCalledWith('open denied')
  })

  it('emits close and reloads the default file after the parent closes and reopens it', async () => {
    vi.mocked(workspaceApi.getUnitRuntimeInfo).mockResolvedValue(buildRuntimeInfo())
    vi.mocked(workspaceApi.getUnitRuntimeFile).mockResolvedValue('log contents')
    const wrapper = mountDialog()
    await flushPromises()

    const configTag = wrapper.findAll('[data-test="file-tag"]')
      .find(tag => tag.text() === 'config.yaml')
    expect(configTag).toBeDefined()
    await configTag!.trigger('click')
    await flushPromises()
    expect(wrapper.findAll('select')[0].element.value).toBe('config.yaml')

    await wrapper.find('[data-test="dialog-close"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
    await wrapper.setProps({ modelValue: false })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(workspaceApi.getUnitRuntimeInfo).toHaveBeenCalledTimes(2)
    expect(wrapper.findAll('select')[0].element.value).toBe('logs/error.log')
    expect(workspaceApi.getUnitRuntimeFile).toHaveBeenLastCalledWith(
      'workspace-1', 'unit-1', 'logs/error.log', 500,
    )
  })
})
