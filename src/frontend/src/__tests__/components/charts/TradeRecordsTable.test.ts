import { afterEach, describe, expect, it, vi } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h, type PropType, type VNode, type VNodeChild } from 'vue'
import TradeRecordsTable from '@/components/charts/TradeRecordsTable.vue'
import type { TradeRecord } from '@/types/analytics'
import { elStubs } from '@/test/stubs'

type TradeColumnNode = VNode & {
  props?: Record<string, unknown> | null
  children?: {
    default?: (scope: { row: TradeRecord, $index: number }) => VNodeChild
  } | null
}

const tableStub = defineComponent({
  name: 'TradeRecordsTableRowsStub',
  inheritAttrs: false,
  props: {
    data: {
      type: Array as PropType<TradeRecord[]>,
      default: () => [],
    },
  },
  setup(props, { attrs, slots }) {
    return () => h('div', {
      ...attrs,
      class: ['el-table', attrs.class],
    }, props.data.map((row, rowIndex) => h('div', {
      class: 'el-table-row',
      'data-row-id': row.id,
    }, (slots.default?.() ?? []).map((rawColumn, columnIndex) => {
      const column = rawColumn as TradeColumnNode
      const columnProps = column.props ?? {}
      const prop = columnProps.prop
      const renderCell = column.children?.default
      const rawValue = typeof renderCell === 'function'
        ? renderCell({ row, $index: rowIndex })
        : typeof prop === 'string'
          ? row[prop as keyof TradeRecord]
          : ''
      const label = String(columnProps.label ?? prop ?? `column-${columnIndex}`)

      return h('div', {
        class: 'el-table-cell',
        'data-column': label,
      }, [h('span', { class: 'el-table-cell__value' }, rawValue ?? '')])
    }))))
  },
})

const selectStub = defineComponent({
  name: 'TradeRecordsSelectStub',
  inheritAttrs: false,
  props: ['modelValue', 'placeholder', 'size', 'clearable'],
  emits: ['update:modelValue', 'change'],
  setup(props, { attrs, emit, slots }) {
    return () => h('select', {
      ...attrs,
      class: ['el-select', attrs.class],
      value: String(props.modelValue ?? ''),
      onChange: (event: Event) => {
        const value = (event.target as HTMLSelectElement).value
        emit('update:modelValue', value)
        emit('change', value)
      },
    }, slots.default?.())
  },
})

const optionStub = defineComponent({
  name: 'TradeRecordsOptionStub',
  props: ['label', 'value'],
  setup(props) {
    return () => h('option', { value: String(props.value ?? '') }, String(props.label ?? ''))
  },
})

const mountedWrappers: VueWrapper[] = []

afterEach(() => {
  mountedWrappers.forEach(wrapper => wrapper.unmount())
  mountedWrappers.length = 0
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function trade(overrides: Partial<TradeRecord> & Pick<TradeRecord, 'id'>): TradeRecord {
  return {
    datetime: '2026-06-19T10:00:00',
    dtopen: '2026-06-19T09:30:00',
    dtclose: '2026-06-19T10:00:00',
    symbol: 'RB2510',
    direction: 'buy',
    price: 10,
    close_price: 11,
    size: 1,
    value: 10,
    commission: 0,
    pnl: 1,
    return_pct: 0.1,
    holding_days: 1,
    cumulative_pnl: 1,
    ...overrides,
  }
}

const sampleTrades: TradeRecord[] = [
  trade({
    id: 1,
    direction: 'buy',
    symbol: 'LONG-PROFIT',
    price: 10.5,
    close_price: 12.5,
    size: 2,
    value: 21,
    commission: 1.25,
    pnl: 4,
    return_pct: 0.2,
    holding_days: 2,
    cumulative_pnl: 4,
  }),
  trade({
    id: 2,
    direction: 'sell',
    symbol: 'SHORT-LOSS',
    price: 20,
    close_price: null,
    size: 1,
    value: 20,
    commission: 0.75,
    pnl: -3,
    return_pct: -0.15,
    holding_days: null,
    cumulative_pnl: 1,
  }),
  trade({
    id: 3,
    direction: 'sell',
    symbol: 'SHORT-FLAT',
    price: 15,
    close_price: 15,
    commission: 0.5,
    pnl: 0,
    return_pct: 0,
    holding_days: 0,
    cumulative_pnl: 0,
  }),
  trade({
    id: 4,
    direction: 'buy',
    symbol: 'OPEN-TRADE',
    dtopen: null,
    dtclose: null,
    close_price: null,
    commission: 0,
    pnl: null,
    return_pct: null,
    holding_days: null,
    cumulative_pnl: -2,
  }),
]

function mountTable(trades?: TradeRecord[]) {
  const wrapper = mount(TradeRecordsTable, {
    props: trades === undefined ? {} : { trades },
    global: {
      stubs: {
        ...elStubs,
        'el-table': tableStub,
        'el-select': selectStub,
        'el-option': optionStub,
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function cell(wrapper: VueWrapper, rowId: number, label: string) {
  return wrapper.get(`[data-row-id="${rowId}"] [data-column="${label}"] .el-table-cell__value`)
}

function rowIds(wrapper: VueWrapper) {
  return wrapper.findAll('.el-table-row').map(row => Number(row.attributes('data-row-id')))
}

describe('TradeRecordsTable', () => {
  it('renders trade slots, nullable fields, signs, and source-trade summaries', () => {
    const wrapper = mountTable(sampleTrades)

    expect(wrapper.get('.trade-records-table h4').text()).toBe('交易记录')
    expect(wrapper.findAll('.grid-cols-4 .font-semibold').map(item => item.text())).toEqual([
      '4',
      '1',
      '1',
      '¥2.50',
    ])
    expect(rowIds(wrapper)).toEqual([1, 2, 3, 4])

    expect(cell(wrapper, 1, '方向').text()).toBe('买入')
    expect(cell(wrapper, 1, '开仓价').text()).toBe('10.50')
    expect(cell(wrapper, 1, '平仓价').text()).toBe('12.50')
    expect(cell(wrapper, 1, '盈亏').text()).toBe('+¥4.00')
    expect(cell(wrapper, 1, '盈亏').find('span').classes()).toContain('text-green-600')
    expect(cell(wrapper, 1, '收益率').text()).toBe('+20.00%')
    expect(cell(wrapper, 1, '累计盈亏').text()).toBe('+¥4.00')
    expect(cell(wrapper, 1, '持仓天数').text()).toBe('2天')

    expect(cell(wrapper, 2, '方向').text()).toBe('卖出')
    expect(cell(wrapper, 2, '平仓价').text()).toBe('--')
    expect(cell(wrapper, 2, '盈亏').text()).toBe('¥-3.00')
    expect(cell(wrapper, 2, '盈亏').find('span').classes()).toContain('text-red-600')
    expect(cell(wrapper, 2, '收益率').text()).toBe('-15.00%')
    expect(cell(wrapper, 2, '持仓天数').text()).toBe('--')

    expect(cell(wrapper, 3, '盈亏').text()).toBe('+¥0.00')
    expect(cell(wrapper, 3, '收益率').text()).toBe('+0.00%')
    expect(cell(wrapper, 3, '持仓天数').text()).toBe('0天')
    expect(cell(wrapper, 4, '盈亏').text()).toBe('--')
    expect(cell(wrapper, 4, '盈亏').find('span').classes()).toContain('text-gray-400')
    expect(cell(wrapper, 4, '收益率').text()).toBe('--')
    expect(cell(wrapper, 4, '累计盈亏').text()).toBe('¥-2.00')
  })

  it('filters rows by direction and profit/loss while leaving summary totals based on all trades', async () => {
    const wrapper = mountTable(sampleTrades)
    const [directionSelect, pnlSelect] = wrapper.findAll('select.el-select')

    await directionSelect.setValue('sell')
    expect(rowIds(wrapper)).toEqual([2, 3])
    await pnlSelect.setValue('loss')
    expect(rowIds(wrapper)).toEqual([2])

    await directionSelect.setValue('buy')
    expect(rowIds(wrapper)).toEqual([])
    await pnlSelect.setValue('profit')
    expect(rowIds(wrapper)).toEqual([1])

    await directionSelect.setValue('')
    await pnlSelect.setValue('')
    expect(rowIds(wrapper)).toEqual([1, 2, 3, 4])
    expect(wrapper.findAll('.grid-cols-4 .font-semibold').map(item => item.text())).toEqual([
      '4',
      '1',
      '1',
      '¥2.50',
    ])
  })

  it('uses the empty default trade list without rendering rows', () => {
    const wrapper = mountTable()

    expect(wrapper.find('.trade-records-table').exists()).toBe(true)
    expect(rowIds(wrapper)).toEqual([])
    expect(wrapper.findAll('.grid-cols-4 .font-semibold').map(item => item.text())).toEqual([
      '0',
      '0',
      '0',
      '¥0.00',
    ])
  })

  it('exports the currently visible trade records as a UTF-8 CSV download', async () => {
    const wrapper = mountTable(sampleTrades)
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:trade-records')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    await wrapper.get('.trade-records-table .el-button').trigger('click')

    expect(createObjectURL).toHaveBeenCalledOnce()
    const csvBlob = createObjectURL.mock.calls[0][0]
    expect(csvBlob).toBeInstanceOf(Blob)
    const csv = await csvBlob.text()
    expect(csv.startsWith('\uFEFF序号,方向,开仓日期')).toBe(true)
    expect(csv).toContain('1,买入,2026-06-19T09:30:00,10.5')
    expect(csv).toContain('2,卖出,2026-06-19T09:30:00,20')
    expect(csv).not.toContain('null')
    expect(anchorClick).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:trade-records')
  })
})
