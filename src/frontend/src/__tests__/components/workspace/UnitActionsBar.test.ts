import { afterEach, describe, expect, it } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import UnitActionsBar from '@/components/workspace/UnitActionsBar.vue'
import { elStubs } from '@/test/stubs'

const defaultProps = {
  active: false,
  toolbarInHeader: false,
  hasSelection: false,
  hasSingleSelection: false,
  running: false,
  autoTradingEnabled: false,
  autoTradingLoading: false,
  autoTradingScheduleSummary: '',
  selectedCount: 0,
  unitCount: 0,
}

const buttonStub = defineComponent({
  name: 'UnitActionsBarButtonStub',
  inheritAttrs: false,
  props: ['disabled', 'loading', 'nativeType', 'type', 'size', 'plain'],
  emits: ['click'],
  setup(props, { attrs, emit, slots }) {
    return () => h('button', {
      ...attrs,
      class: ['el-button', attrs.class],
      type: props.nativeType || 'button',
      disabled: Boolean(props.disabled || props.loading),
      onClick: (event: MouseEvent) => emit('click', event),
    }, slots.default?.())
  },
})

const tooltipStub = defineComponent({
  name: 'UnitActionsBarTooltipStub',
  props: ['content', 'placement'],
  setup(props, { slots }) {
    return () => h('span', {
      class: 'el-tooltip',
      'data-tooltip': props.content,
    }, slots.default?.())
  },
})

const groupStub = defineComponent({
  name: 'UnitActionsBarButtonGroupStub',
  setup(_props, { slots }) {
    return () => h('div', { class: 'el-button-group' }, slots.default?.())
  },
})

const mountedWrappers: VueWrapper[] = []

afterEach(() => {
  mountedWrappers.forEach(wrapper => wrapper.unmount())
  mountedWrappers.length = 0
})

function mountBar(props: Partial<typeof defaultProps> = {}) {
  const wrapper = mount(UnitActionsBar, {
    props: { ...defaultProps, ...props },
    global: {
      stubs: {
        ...elStubs,
        'el-button': buttonStub,
        'el-button-group': groupStub,
        'el-tooltip': tooltipStub,
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

function actionButton(wrapper: VueWrapper, tooltip: string) {
  const owner = wrapper.findAll('.el-tooltip')
    .find(candidate => candidate.attributes('data-tooltip') === tooltip)
  if (!owner) throw new Error(`Missing toolbar action tooltip: ${tooltip}`)
  return owner.get('button.el-button')
}

describe('UnitActionsBar', () => {
  it('emits actions for available selection and single-unit operations', async () => {
    const wrapper = mountBar({
      active: true,
      toolbarInHeader: true,
      hasSelection: true,
      hasSingleSelection: true,
      running: false,
      autoTradingEnabled: false,
      autoTradingScheduleSummary: '工作日 09:00',
      selectedCount: 1,
      unitCount: 1,
    })

    expect(wrapper.get('.trading-toolbar').classes()).toContain('mb-0')
    expect(wrapper.get('.trading-toolbar__meta').text()).toContain('自动交易已关闭')
    expect(wrapper.get('.trading-toolbar__meta').text()).toContain('工作日 09:00')
    expect(wrapper.get('.trading-toolbar__meta').text()).toContain('已选 1 / 1')

    const actions: Array<[string, string]> = [
      ['全选 / 取消全选', 'selectAll'],
      ['启动自动交易', 'enableAutoTrading'],
      ['锁定交易', 'lockTrading'],
      ['锁定运行', 'lockRunning'],
      ['解锁', 'unlock'],
      ['启动策略单元', 'startSelected'],
      ['停止策略单元', 'stopSelected'],
      ['新建策略单元', 'createUnit'],
      ['删除策略单元', 'bulkDelete'],
      ['导入策略单元', 'importUnits'],
      ['导出策略单元', 'exportUnits'],
      ['数据源设置', 'openDataSource'],
      ['单元设置', 'openUnitSettings'],
      ['公式应用设置', 'openStrategyParams'],
      ['头寸管理器', 'openPositionManager'],
      ['打开 K', 'openKline'],
      ['打开组合报告', 'openReport'],
      ['自动交易配置', 'openAutoTradingConfig'],
      ['新建优化任务', 'createOptimizationTask'],
      ['打开优化结果', 'openOptimization'],
      ['定时优化设置', 'openScheduledOptimization'],
      ['交易日统计选项', 'openTradingDayStats'],
      ['联动分组', 'openGroupLink'],
    ]

    for (const [tooltip, event] of actions) {
      const button = actionButton(wrapper, tooltip)
      expect((button.element as HTMLButtonElement).disabled, tooltip).toBe(false)
      await button.trigger('click')
      expect(wrapper.emitted(event), event).toHaveLength(1)
    }

    expect(actionButton(wrapper, '关闭自动交易').element).toHaveProperty('disabled', true)
  })

  it('disables actions that require selection or units and respects auto-trading loading', () => {
    const wrapper = mountBar({ autoTradingLoading: true })

    expect(wrapper.get('.trading-toolbar').classes()).toContain('mb-4')
    const disabledActions = [
      '启动自动交易',
      '关闭自动交易',
      '锁定交易',
      '锁定运行',
      '解锁',
      '启动策略单元',
      '停止策略单元',
      '删除策略单元',
      '导出策略单元',
      '数据源设置',
      '单元设置',
      '公式应用设置',
      '头寸管理器',
      '打开 K',
      '打开组合报告',
      '新建优化任务',
      '打开优化结果',
      '交易日统计选项',
      '联动分组',
    ]
    for (const tooltip of disabledActions) {
      expect((actionButton(wrapper, tooltip).element as HTMLButtonElement).disabled, tooltip).toBe(true)
    }

    for (const tooltip of ['全选 / 取消全选', '新建策略单元', '导入策略单元', '自动交易配置', '定时优化设置']) {
      expect((actionButton(wrapper, tooltip).element as HTMLButtonElement).disabled, tooltip).toBe(false)
    }
    expect(wrapper.get('.trading-toolbar__meta').text()).toContain('已选 0 / 0')
    expect(wrapper.findAll('.trading-toolbar__meta .text-slate-500')).toHaveLength(1)
    expect(wrapper.get('.trading-toolbar__meta').text()).not.toContain('工作日')
  })

  it('keeps stop and multi-selection actions available while running, but disables single-unit actions', async () => {
    const wrapper = mountBar({
      hasSelection: true,
      hasSingleSelection: false,
      running: true,
      autoTradingEnabled: true,
      selectedCount: 2,
      unitCount: 3,
    })

    expect(wrapper.get('.trading-toolbar__meta').text()).toContain('自动交易已启用')
    expect(wrapper.get('.trading-toolbar__meta').text()).toContain('已选 2 / 3')
    expect((actionButton(wrapper, '启动自动交易').element as HTMLButtonElement).disabled).toBe(true)
    expect((actionButton(wrapper, '关闭自动交易').element as HTMLButtonElement).disabled).toBe(false)
    expect((actionButton(wrapper, '启动策略单元').element as HTMLButtonElement).disabled).toBe(true)
    expect((actionButton(wrapper, '停止策略单元').element as HTMLButtonElement).disabled).toBe(false)
    expect((actionButton(wrapper, '锁定交易').element as HTMLButtonElement).disabled).toBe(false)
    expect((actionButton(wrapper, '删除策略单元').element as HTMLButtonElement).disabled).toBe(false)
    expect((actionButton(wrapper, '数据源设置').element as HTMLButtonElement).disabled).toBe(true)
    expect((actionButton(wrapper, '打开 K').element as HTMLButtonElement).disabled).toBe(true)
    expect((actionButton(wrapper, '头寸管理器').element as HTMLButtonElement).disabled).toBe(false)

    await actionButton(wrapper, '关闭自动交易').trigger('click')
    await actionButton(wrapper, '停止策略单元').trigger('click')
    await actionButton(wrapper, '删除策略单元').trigger('click')
    expect(wrapper.emitted('disableAutoTrading')).toHaveLength(1)
    expect(wrapper.emitted('stopSelected')).toHaveLength(1)
    expect(wrapper.emitted('bulkDelete')).toHaveLength(1)
  })
})
