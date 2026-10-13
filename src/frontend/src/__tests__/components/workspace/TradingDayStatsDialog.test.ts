import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, defineComponent, h, inject, provide, type ComputedRef, type InjectionKey } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import TradingDayStatsDialog from '@/components/workspace/TradingDayStatsDialog.vue'
import { useWorkspaceStore } from '@/stores/workspace'
import { workspaceApi } from '@/api/workspace'
import { ElMessage } from 'element-plus'
import type { StrategyUnit, TradingDailySummaryItem, TradingSnapshot } from '@/types/workspace'
import { elStubs } from '@/test/stubs'

const summaryApiMocks = vi.hoisted(() => ({
  getTradingDailySummary: vi.fn(),
}))

vi.mock('@/api/workspace', () => ({ workspaceApi: summaryApiMocks }))
vi.mock('@/api/index', () => ({
  default: {},
  getErrorMessage: (error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
}))
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn() } }))

const dialogStub = defineComponent({
  name: 'StatsDialogStub',
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
  name: 'StatsSelectStub',
  props: ['modelValue', 'placeholder', 'clearable', 'size'],
  emits: ['update:modelValue', 'change'],
  setup(props, { emit, slots }) {
    return () => h('select', {
      class: 'stats-select',
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
  name: 'StatsOptionStub',
  props: ['label', 'value'],
  setup(props, { slots }) {
    return () => h('option', { value: props.value ?? '' }, slots.default?.() ?? String(props.label ?? ''))
  },
})

const datePickerStub = defineComponent({
  name: 'StatsDatePickerStub',
  props: ['modelValue', 'type', 'valueFormat', 'placeholder', 'size'],
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    return () => h('input', {
      class: 'stats-date-picker',
      type: 'text',
      value: props.modelValue ?? '',
      placeholder: props.placeholder,
      onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLInputElement).value),
    })
  },
})

type SummaryRow = Record<string, unknown>
const tableRowsKey: InjectionKey<ComputedRef<SummaryRow[]>> = Symbol('summary-table-rows')

const tableStub = defineComponent({
  name: 'StatsTableStub',
  props: ['data', 'emptyText'],
  setup(props, { slots }) {
    const rows = computed(() => Array.isArray(props.data) ? props.data as SummaryRow[] : [])
    provide(tableRowsKey, rows)
    return () => h('div', { class: 'el-table' }, rows.value.length
      ? slots.default?.()
      : h('div', { class: 'el-table__empty-text' }, String(props.emptyText ?? '')),
    )
  },
})

const tableColumnStub = defineComponent({
  name: 'StatsTableColumnStub',
  props: ['prop', 'label'],
  setup(props, { slots }) {
    const rows = inject(tableRowsKey, computed<SummaryRow[]>(() => []))
    return () => h('section', {
      class: 'el-table-column',
      'data-column': props.label,
    }, [
      h('h3', { class: 'el-table-column__label' }, String(props.label ?? '')),
      ...rows.value.map((row, index) => h('div', {
        class: 'el-table-cell',
        'data-column': props.label,
        'data-row-index': String(index),
      }, slots.default?.({ row }) ?? String(props.prop ? row[props.prop] ?? '-' : ''))),
    ])
  },
})

const statsStubs = {
  ...elStubs,
  'el-dialog': dialogStub,
  'el-select': selectStub,
  'el-option': optionStub,
  'el-date-picker': datePickerStub,
  'el-table': tableStub,
  'el-table-column': tableColumnStub,
}

const snapshot: TradingSnapshot = {
  instance_id: null,
  instance_status: 'idle',
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

function buildUnit(id: string, strategyName: string): StrategyUnit {
  return {
    id,
    workspace_id: 'workspace-1',
    group_name: 'default',
    strategy_id: `strategy-${id}`,
    strategy_name: strategyName,
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
    run_status: 'idle',
    run_count: 0,
    last_run_time: null,
    last_task_id: null,
    last_optimization_task_id: null,
    bar_count: null,
    metrics_snapshot: {},
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
  }
}

function buildSummary(overrides: Partial<TradingDailySummaryItem> = {}): TradingDailySummaryItem {
  return {
    trading_date: '2026-10-13',
    daily_pnl: 12.5,
    trade_count: 2,
    cumulative_pnl: 12.5,
    max_drawdown: -1.25,
    ...overrides,
  }
}

const dailySummaries: TradingDailySummaryItem[] = [
  buildSummary({ trading_date: '2026-10-09', daily_pnl: 12.5, trade_count: 2, cumulative_pnl: 12.5, max_drawdown: -1.25 }),
  buildSummary({ trading_date: '2026-10-12', daily_pnl: -3.5, trade_count: 1, cumulative_pnl: 9, max_drawdown: -2 }),
  buildSummary({ trading_date: '2026-10-13', daily_pnl: 0, trade_count: 4, cumulative_pnl: 9, max_drawdown: 0 }),
]

const mountedWrappers: Array<{ unmount: () => void }> = []

function mountDialog(props: Record<string, unknown> = {}) {
  const wrapper = mount(TradingDayStatsDialog, {
    props: { modelValue: false, workspaceId: 'workspace-1', ...props },
    global: { stubs: statsStubs },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('TradingDayStatsDialog', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const store = useWorkspaceStore()
    store.units = [buildUnit('unit-1', 'Alpha'), buildUnit('unit-2', 'Beta')]
    vi.mocked(workspaceApi.getTradingDailySummary).mockReset()
    vi.mocked(workspaceApi.getTradingDailySummary).mockResolvedValue({ summaries: [] })
    vi.mocked(ElMessage.error).mockReset()
  })

  afterEach(() => {
    mountedWrappers.splice(0).forEach(wrapper => wrapper.unmount())
  })

  it('queries on open and renders daily rows, aggregate metrics, and PnL colors', async () => {
    vi.mocked(workspaceApi.getTradingDailySummary).mockResolvedValueOnce({ summaries: dailySummaries })
    const wrapper = mountDialog()

    expect(workspaceApi.getTradingDailySummary).not.toHaveBeenCalled()
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(workspaceApi.getTradingDailySummary).toHaveBeenCalledWith('workspace-1', {
      unit_id: undefined,
      start_date: undefined,
      end_date: undefined,
    })
    expect(wrapper.findAll('.grid .text-lg').map(value => value.text())).toEqual([
      '3', '+9.00', '7', '+12.50',
    ])
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="0"]').text()).toBe('+12.50')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="1"]').text()).toBe('-3.50')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="2"]').text()).toBe('+0.00')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="0"] span').classes())
      .toContain('text-red-600')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="1"] span').classes())
      .toContain('text-green-600')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="2"] span').classes())
      .toContain('text-slate-600')
    expect(wrapper.find('[data-column="最大回撤"][data-row-index="0"]').text()).toBe('-1.25%')
    expect(wrapper.text()).toContain('2026-10-09')
    expect(wrapper.text()).toContain('2026-10-12')
  })

  it('submits selected unit and date filters, then resets them through the UI', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    vi.mocked(workspaceApi.getTradingDailySummary).mockClear()

    await wrapper.find('select').setValue('unit-2')
    await wrapper.findAll('input')[0].setValue('2026-10-01')
    await wrapper.findAll('input')[1].setValue('2026-10-13')
    const queryButton = wrapper.findAll('button.el-button').find(button => button.text() === '查询')
    expect(queryButton).toBeDefined()
    await queryButton!.trigger('click')
    await flushPromises()

    expect(workspaceApi.getTradingDailySummary).toHaveBeenCalledWith('workspace-1', {
      unit_id: 'unit-2',
      start_date: '2026-10-01',
      end_date: '2026-10-13',
    })
    expect(wrapper.findAll('select')[0].element.value).toBe('unit-2')

    const resetButton = wrapper.findAll('button.el-button').find(button => button.text() === '重置')
    expect(resetButton).toBeDefined()
    await resetButton!.trigger('click')
    await flushPromises()

    expect(workspaceApi.getTradingDailySummary).toHaveBeenLastCalledWith('workspace-1', {
      unit_id: undefined,
      start_date: undefined,
      end_date: undefined,
    })
    expect(wrapper.find('select').element.value).toBe('')
    expect(wrapper.findAll('input').map(input => (input.element as HTMLInputElement).value))
      .toEqual(['', ''])
  })

  it('shows the localized empty-table fallback for an empty result and emits close', async () => {
    const wrapper = mountDialog()
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(wrapper.find('.el-table__empty-text').text()).toBe('暂无交易日统计数据')
    expect(wrapper.findAll('.grid .text-lg').map(value => value.text())).toEqual([
      '0', '+0.00', '0', '+0.00',
    ])

    await wrapper.find('[data-test="dialog-close"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('renders dash fallbacks for null or non-finite statistics and reports query errors', async () => {
    const incompleteSummary = buildSummary({
      daily_pnl: null as unknown as number,
      trade_count: 0,
      cumulative_pnl: Number.NaN,
      max_drawdown: null as unknown as number,
    })
    vi.mocked(workspaceApi.getTradingDailySummary).mockResolvedValueOnce({
      summaries: [incompleteSummary],
    })
    const wrapper = mountDialog()
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="0"]').text()).toBe('-')
    expect(wrapper.find('[data-column="累计盈亏"][data-row-index="0"]').text()).toBe('-')
    expect(wrapper.find('[data-column="最大回撤"][data-row-index="0"]').text()).toBe('-')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="0"] span').classes())
      .toContain('text-slate-600')

    vi.mocked(workspaceApi.getTradingDailySummary).mockRejectedValueOnce(new Error('summary service unavailable'))
    const queryButton = wrapper.findAll('button.el-button').find(button => button.text() === '查询')
    expect(queryButton).toBeDefined()
    await queryButton!.trigger('click')
    await flushPromises()

    expect(ElMessage.error).toHaveBeenCalledWith('summary service unavailable')
    expect(wrapper.find('[data-column="当日盈亏"][data-row-index="0"]').text()).toBe('-')
  })
})
