import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import PositionManagerDialog from '@/components/workspace/PositionManagerDialog.vue'
import { ElMessage } from 'element-plus'
import { workspaceApi } from '@/api/workspace'
import { elStubs } from '@/test/stubs'

vi.mock('element-plus', () => ({
  ElMessage: { error: vi.fn() },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key, locale: ref('zh-CN') }),
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    getTradingPositions: vi.fn().mockResolvedValue({
      positions: [],
      total_long_value: 0,
      total_short_value: 0,
      total_pnl: 0,
    }),
  },
}))

describe('PositionManagerDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(workspaceApi.getTradingPositions).mockResolvedValue({
      positions: [],
      total_long_value: 0,
      total_short_value: 0,
      total_pnl: 0,
    })
  })

  const mountDialog = (props: Record<string, unknown> = {}) => mount(PositionManagerDialog, {
    props: {
      modelValue: false,
      workspaceId: 'workspace-1',
      ...props,
    },
    global: {
      stubs: {
        ...elStubs,
        'el-dialog': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<div class="el-dialog"><button data-test="dialog-cancel" @click="$emit(\'update:modelValue\', false)">Cancel</button><slot /></div>',
        },
      },
    },
  })

  it('preserves micro nonzero position quantities when formatting', () => {
    const vm = mountDialog().vm as any

    expect(vm.formatQuantity(0.00004)).toBe('0.00004')
    expect(vm.formatQuantity(-0.00004)).toBe('-0.00004')
    expect(vm.formatQuantity(1.23456)).toBe('1.2346')
    expect(vm.formatQuantity(0)).toBe('-')
  })

  it('hides flat positions returned by the API', async () => {
    const { workspaceApi } = await import('@/api/workspace')
    vi.mocked(workspaceApi.getTradingPositions).mockResolvedValueOnce({
      positions: [
        {
          unit_id: 'unit-flat',
          unit_name: 'Flat Unit',
          symbol: 'rb2601',
          symbol_name: '螺纹钢',
          trading_mode: 'paper',
          long_position: 0,
          short_position: 0,
          avg_price: 0,
          latest_price: 0,
          position_pnl: 0,
          market_value: 0,
        },
        {
          unit_id: 'unit-active',
          unit_name: 'Active Unit',
          symbol: 'IF2609',
          symbol_name: '沪深300',
          trading_mode: 'live',
          long_position: 1,
          short_position: 0,
          avg_price: 5000,
          latest_price: 5001,
          position_pnl: 265.5,
          market_value: 1500300,
          long_market_value: 1500400,
          short_market_value: 0,
          margin_value: 150030,
          multiplier: 300,
          margin_rate: 0.1,
          leverage: 10,
          commission: 34.5,
          gross_pnl: 300,
          position_source: 'gateway',
          asset_spec_source: 'ctp_gateway',
          valuation_status: 'confirmed',
          valuation_warnings: [],
        },
      ],
      total_long_value: 999999,
      total_short_value: 888888,
      total_pnl: 777,
    })
    const vm = mountDialog().vm as any

    await vm.loadPositions()

    expect(vm.positions).toHaveLength(1)
    expect(vm.positions[0].unit_id).toBe('unit-active')
    expect(vm.summary.total_long_value).toBe(1500400)
    expect(vm.summary.total_short_value).toBe(0)
    expect(vm.summary.total_pnl).toBe(265.5)
  })

  it('requests the selected units, summarizes visible exposure, and emits close on cancel', async () => {
    vi.mocked(workspaceApi.getTradingPositions).mockResolvedValueOnce({
      positions: [
        {
          unit_id: 'unit-mixed',
          unit_name: 'Mixed Position',
          symbol: 'IF2609',
          symbol_name: '沪深300',
          trading_mode: 'paper',
          long_position: 2,
          short_position: 1,
          avg_price: 100,
          latest_price: 102,
          position_pnl: 15.25,
          market_value: 300,
        },
        {
          unit_id: 'unit-zero',
          unit_name: 'Zero Position',
          symbol: 'rb2601',
          symbol_name: '螺纹钢',
          trading_mode: 'paper',
          long_position: 0,
          short_position: 0,
          avg_price: 0,
          latest_price: 0,
          position_pnl: 0,
          market_value: 0,
        },
      ],
      total_long_value: 900,
      total_short_value: 600,
      total_pnl: 900,
    })
    const wrapper = mountDialog({ unitIds: ['unit-mixed'] })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()
    const vm = wrapper.vm as any

    expect(workspaceApi.getTradingPositions).toHaveBeenCalledWith('workspace-1', ['unit-mixed'])
    expect(vm.positions.map((position: { unit_id: string }) => position.unit_id)).toEqual(['unit-mixed'])
    expect(vm.summary).toMatchObject({
      total_long_value: 200,
      total_short_value: 100,
      total_pnl: 15.25,
    })

    await wrapper.get('[data-test="dialog-cancel"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')).toEqual([[false]])
  })

  it('keeps an empty summary and reports an error when position loading fails', async () => {
    vi.mocked(workspaceApi.getTradingPositions).mockRejectedValueOnce(new Error('gateway unavailable'))
    const wrapper = mountDialog({ unitIds: ['unit-1', 'unit-2'] })
    await wrapper.setProps({ modelValue: true })
    await flushPromises()

    expect(workspaceApi.getTradingPositions).toHaveBeenCalledWith('workspace-1', ['unit-1', 'unit-2'])
    expect(ElMessage.error).toHaveBeenCalledWith('gateway unavailable')
    expect((wrapper.vm as any).positions).toEqual([])
    expect((wrapper.vm as any).loading).toBe(false)
  })
})
