import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import {
  computed,
  defineComponent,
  h,
  inject,
  provide,
  ref,
  type ComputedRef,
  type InjectionKey,
  type PropType,
} from 'vue'
import type { StrategyUnit } from '@/types/workspace'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

import UnitTable from '@/components/workspace/UnitTable.vue'
import { elStubs } from '@/test/stubs'

const tableRowsKey: InjectionKey<ComputedRef<StrategyUnit[]>> = Symbol('unit-table-rows')

const unitTableStub = defineComponent({
  name: 'UnitTableHarness',
  props: {
    data: { type: Array as PropType<StrategyUnit[]>, default: () => [] },
    emptyText: { type: String, default: '' },
  },
  emits: ['selection-change', 'row-dblclick'],
  setup(props, { emit, expose, slots }) {
    const selectedIds = ref(new Set<string>())
    const rows = computed(() => props.data)
    provide(tableRowsKey, rows)

    const selectedRows = computed(() => props.data.filter(row => selectedIds.value.has(row.id)))
    const clearSelection = vi.fn(() => {
      selectedIds.value = new Set()
      emit('selection-change', [])
    })
    const toggleRowSelection = vi.fn((row: StrategyUnit, selected?: boolean) => {
      const nextIds = new Set(selectedIds.value)
      const shouldSelect = selected ?? !nextIds.has(row.id)
      if (shouldSelect) nextIds.add(row.id)
      else nextIds.delete(row.id)
      selectedIds.value = nextIds
      emit('selection-change', selectedRows.value)
    })
    expose({ clearSelection, toggleRowSelection })

    return () => h('div', { class: 'test-unit-table' }, [
      props.data.length === 0
        ? h('p', { class: 'test-empty-text' }, props.emptyText)
        : null,
      ...props.data.map(row => h('div', {
        class: 'test-table-row',
        'data-row-id': row.id,
      }, [
        h('span', { class: 'test-table-row-name' }, row.strategy_name || row.strategy_id || '-'),
        h('button', {
          type: 'button',
          'data-test': 'select-row',
          onClick: () => toggleRowSelection(row),
        }, 'Select'),
        h('button', {
          type: 'button',
          'data-test': 'double-click-row',
          onDblclick: (event: MouseEvent) => emit('row-dblclick', row, null, event),
        }, 'Open row'),
      ])),
      slots.default?.(),
    ])
  },
})

const unitTableColumnStub = defineComponent({
  name: 'UnitTableColumnHarness',
  props: {
    label: { type: String, default: '' },
    prop: { type: String, default: '' },
  },
  setup(props, { slots }) {
    const rows = inject(tableRowsKey, computed(() => [] as StrategyUnit[]))
    return () => h('div', {
      class: 'test-table-column',
      'data-label': props.label,
      'data-prop': props.prop,
    }, rows.value.map((row, index) => {
      const value = props.prop ? row[props.prop as keyof StrategyUnit] : undefined
      return h('div', {
        class: 'test-table-cell',
        'data-row-id': row.id,
      }, slots.default
        ? slots.default({ row, $index: index })
        : String(value ?? ''))
    }))
  },
})

const units: StrategyUnit[] = [
  {
    id: 'u-1',
    workspace_id: 'ws-1',
    group_name: 'Primary',
    strategy_id: 'ma-cross',
    strategy_name: 'Alpha',
    symbol: '000001.SZ',
    symbol_name: 'Ping An',
    timeframe: '1d',
    timeframe_n: 1,
    category: 'trend',
    sort_order: 0,
    data_config: { start_date: '2026-01-01', use_end_date: true, end_date: '2026-01-31' },
    unit_settings: {},
    params: {},
    optimization_config: {},
    trading_mode: 'live',
    gateway_config: {},
    lock_trading: true,
    lock_running: false,
    trading_instance_id: 'instance-1',
    trading_snapshot: {
      instance_id: 'instance-1',
      instance_status: 'running',
      mode: 'live',
      error: null,
      started_at: null,
      stopped_at: null,
      gateway_summary: null,
      long_position: 2,
      short_position: 0,
      today_pnl: 12.34,
      position_pnl: -1.25,
      latest_price: 12.3456,
      change_pct: 2.5,
      long_market_value: 123456,
      short_market_value: 500,
      leverage: 1.5,
      cumulative_pnl: -10,
      max_drawdown_rate: 0,
      trading_day: '2026-10-13',
      updated_at: '2026-10-13T09:00:00Z',
      detail_route: null,
      positions: [],
      trades: [],
    },
    run_status: 'completed',
    run_count: 1,
    last_run_time: null,
    last_task_id: 't-1',
    last_optimization_task_id: null,
    bar_count: 120,
    metrics_snapshot: {},
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-10-12T09:00:00Z',
  },
  {
    id: 'u-2',
    workspace_id: 'ws-1',
    group_name: 'Secondary',
    strategy_id: null,
    strategy_name: '',
    symbol: '',
    symbol_name: '',
    timeframe: '',
    timeframe_n: 1,
    category: 'custom',
    sort_order: 1,
    data_config: {},
    unit_settings: {},
    params: {},
    optimization_config: {},
    trading_mode: 'paper',
    gateway_config: {},
    lock_trading: false,
    lock_running: true,
    trading_instance_id: null,
    trading_snapshot: {
      instance_id: null,
      instance_status: 'error',
      mode: 'paper',
      error: 'connection failed',
      started_at: null,
      stopped_at: null,
      gateway_summary: null,
      long_position: 0,
      short_position: 0,
      today_pnl: 0,
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
    },
    run_status: 'idle',
    run_count: 0,
    last_run_time: null,
    last_task_id: null,
    last_optimization_task_id: null,
    bar_count: null,
    metrics_snapshot: {},
    created_at: '2026-01-02T00:00:00Z',
    updated_at: '',
  },
]

function doMount(rows: StrategyUnit[] = units) {
  return mount(UnitTable, {
    props: { units: rows },
    global: {
      stubs: {
        ...elStubs,
        'el-table': unitTableStub,
        'el-table-column': unitTableColumnStub,
      },
    },
  })
}

describe('UnitTable', () => {
  it('mounts and renders without error for a set of units', () => {
    const wrapper = doMount()
    expect(wrapper.exists()).toBe(true)
  })

  it('renders a compact mobile card with a details action for every unit', async () => {
    const wrapper = doMount()
    expect(wrapper.findAll('.trading-unit-card')).toHaveLength(2)
    expect(wrapper.find('.trading-unit-card').text()).toContain('Alpha')

    await wrapper.find('.trading-unit-card__identity').trigger('click')
    expect(wrapper.emitted('open-detail')?.[0]).toEqual([units[0]])
  })

  it('renders table and mobile rows with status, metric, and date fallbacks', () => {
    const wrapper = doMount()
    const indexCells = wrapper.findAll(
      '.test-table-column[data-label="workspaceDialogs.indexNo"] .test-table-cell',
    )
    const endDateCells = wrapper.findAll(
      '.test-table-column[data-label="workspaceDialogs.rangeEndDate"] .test-table-cell',
    )
    const longPositionCells = wrapper.findAll(
      '.test-table-column[data-label="workspaceDialogs.longShare"] .test-table-cell',
    )

    expect(wrapper.findAll('.test-table-row')).toHaveLength(2)
    expect(indexCells.map(cell => cell.text())).toEqual(['1', '2'])
    expect(endDateCells.map(cell => cell.text())).toEqual(['2026-01-31', '-'])
    expect(longPositionCells.map(cell => cell.text())).toEqual(['2.0000', '-'])
    expect(wrapper.find('.status-dot.is-running').exists()).toBe(true)
    expect(wrapper.find('.status-dot.is-error').exists()).toBe(true)
    expect(wrapper.findAll('.trading-unit-card__header .status-flag')).toHaveLength(2)

    const sparseCard = wrapper.find('.trading-unit-card[aria-label="- "]')
    expect(sparseCard.exists()).toBe(true)
    expect(sparseCard.findAll('.trading-unit-card__metrics dd').map(value => value.text()))
      .toEqual(['-', '-', '-', '0.00'])
  })

  it('forwards row selection and double-click events and exposes clear/toggle controls', async () => {
    const wrapper = doMount()
    const table = wrapper.findComponent(unitTableStub)
    const exposedTable = table.vm as unknown as {
      clearSelection: ReturnType<typeof vi.fn>
      toggleRowSelection: ReturnType<typeof vi.fn>
    }

    await wrapper.find('.test-table-row[data-row-id="u-1"] [data-test="select-row"]')
      .trigger('click')
    expect(wrapper.emitted('selection-change')?.[0]).toEqual([[units[0]]])

    await wrapper.find('.test-table-row[data-row-id="u-2"] [data-test="double-click-row"]')
      .trigger('dblclick')
    const rowDoubleClick = wrapper.emitted('row-dblclick')?.[0]
    expect(rowDoubleClick?.[0]).toMatchObject({ id: units[1].id, run_status: units[1].run_status })
    expect(rowDoubleClick?.[1]).toBeNull()
    expect(rowDoubleClick?.[2]).toBeInstanceOf(MouseEvent)

    const exposedUnitTable = wrapper.vm as unknown as {
      clearSelection: () => void
      toggleRowSelection: (row: StrategyUnit, selected?: boolean) => void
    }
    exposedUnitTable.toggleRowSelection(units[1], true)
    expect(exposedTable.toggleRowSelection).toHaveBeenCalledWith(units[1], true)
    expect(wrapper.emitted('selection-change')?.at(-1)).toEqual([[units[0], units[1]]])

    exposedUnitTable.clearSelection()
    expect(exposedTable.clearSelection).toHaveBeenCalledOnce()
    expect(wrapper.emitted('selection-change')?.at(-1)).toEqual([[]])
  })

  it('shows the table empty prompt and no mobile cards for an empty unit list', () => {
    const wrapper = doMount([])

    expect(wrapper.find('.test-empty-text').text()).toContain('workspaceDialogs.emptyUnits')
    expect(wrapper.findAll('.test-table-row')).toHaveLength(0)
    expect(wrapper.findAll('.trading-unit-card')).toHaveLength(0)
  })

  it('keeps the detail action available for a row with missing optional values', async () => {
    const invalidUnit = {
      id: 'invalid-unit',
      sort_order: 0,
      strategy_id: null,
      strategy_name: '',
      symbol: '',
      symbol_name: '',
      timeframe: '',
      data_config: null,
      trading_snapshot: null,
    } as unknown as StrategyUnit
    const wrapper = doMount([invalidUnit])
    const card = wrapper.find('.trading-unit-card')
    const detailButton = card.find('.trading-unit-card__actions .el-button')

    expect(card.attributes('aria-label')).toBe('- ')
    expect(card.findAll('.trading-unit-card__metrics dd').map(value => value.text()))
      .toEqual(['-', '-', '-', '-'])
    expect(detailButton.exists()).toBe(true)
    expect((detailButton.element as HTMLButtonElement).disabled).toBe(false)

    await detailButton.trigger('click')
    expect(wrapper.emitted('open-detail')?.[0]).toEqual([invalidUnit])
  })

  it('exposes clearSelection and toggleRowSelection that delegate to the inner table', () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    const inner = { clearSelection: vi.fn(), toggleRowSelection: vi.fn() }
    vm.tableRef = inner
    vm.clearSelection()
    vm.toggleRowSelection(units[0], true)
    expect(inner.clearSelection).toHaveBeenCalled()
    expect(inner.toggleRowSelection).toHaveBeenCalledWith(units[0], true)
  })

  it('tolerates a null inner table ref (no throw)', () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    vm.tableRef = null
    expect(() => vm.clearSelection()).not.toThrow()
    expect(() => vm.toggleRowSelection(units[0])).not.toThrow()
  })
})
