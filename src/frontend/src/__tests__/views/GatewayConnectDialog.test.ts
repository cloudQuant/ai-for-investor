import { defineComponent, h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import GatewayConnectDialog from '@/views/GatewayConnectDialog.vue'
import { elStubs } from '@/test/stubs'

type GatewayConnectDialogProps = InstanceType<typeof GatewayConnectDialog>['$props']

const DialogStub = defineComponent({
  name: 'DialogStub',
  props: ['modelValue'],
  setup(props, { slots }) {
    return () => h('section', { 'data-visible': String(props.modelValue) }, [
      slots.default?.(),
      slots.footer?.(),
    ])
  },
})

const SelectStub = defineComponent({
  name: 'SelectStub',
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  setup(_props, { slots }) {
    return () => h('div', { class: 'select-stub' }, slots.default?.())
  },
})

const RadioGroupStub = defineComponent({
  name: 'RadioGroupStub',
  props: ['modelValue'],
  emits: ['update:modelValue', 'change'],
  setup(_props, { slots }) {
    return () => h('div', { class: 'radio-group-stub' }, slots.default?.())
  },
})

function makeProps(): GatewayConnectDialogProps {
  return {
    visible: true,
    connectForm: { exchange_type: '', credentials: {} },
    ctpEnv: 'simnow',
    ctpGroup: 1,
    mt5Env: 'demo',
    ibEnv: 'paper',
    connecting: false,
    onExchangeChange: vi.fn(),
    onCtpEnvChange: vi.fn(),
    onCtpGroupChange: vi.fn(),
    onMt5EnvChange: vi.fn(),
    onIbEnvChange: vi.fn(),
    onConnect: vi.fn(),
  }
}

function mountDialog(props = makeProps()) {
  return mount(GatewayConnectDialog, {
    props,
    global: {
      stubs: {
        ...elStubs,
        'el-dialog': DialogStub,
        'el-select': SelectStub,
        'el-radio-group': RadioGroupStub,
      },
    },
  })
}

describe('GatewayConnectDialog', () => {
  it('emits visibility and CTP preset updates and calls the connect action', async () => {
    const props = makeProps()
    const wrapper = mountDialog(props)

    expect(wrapper.get('[data-visible]').attributes('data-visible')).toBe('true')
    expect(wrapper.findAll('button')).toHaveLength(2)
    await wrapper.findAll('button')[0].trigger('click')
    expect(wrapper.emitted('update:visible')).toEqual([[false]])

    const exchangeSelect = wrapper.findAllComponents(SelectStub)[0]
    exchangeSelect.vm.$emit('update:modelValue', 'CTP')
    exchangeSelect.vm.$emit('change', 'CTP')
    await nextTick()
    expect(props.connectForm.exchange_type).toBe('CTP')
    expect(props.onExchangeChange).toHaveBeenCalledTimes(1)

    const ctpEnv = wrapper.findAllComponents(RadioGroupStub)[0]
    ctpEnv.vm.$emit('update:modelValue', 'simnow_7x24')
    ctpEnv.vm.$emit('change', 'simnow_7x24')
    await nextTick()
    expect(wrapper.emitted('update:ctpEnv')).toEqual([['simnow_7x24']])
    expect(props.onCtpEnvChange).toHaveBeenCalledTimes(1)
    expect(wrapper.text()).toContain('7×24')

    const ctpGroup = wrapper.findAllComponents(SelectStub)[1]
    ctpGroup.vm.$emit('update:modelValue', 2)
    ctpGroup.vm.$emit('change', 2)
    await nextTick()
    expect(wrapper.emitted('update:ctpGroup')).toEqual([[2]])
    expect(props.onCtpGroupChange).toHaveBeenCalledTimes(1)

    await wrapper.findAll('button')[1].trigger('click')
    expect(props.onConnect).toHaveBeenCalledTimes(1)
  })

  it('wires MT5 and IB environment updates and exposes their account fields', async () => {
    const mt5Props = makeProps()
    mt5Props.connectForm.exchange_type = 'MT5'
    const mt5Wrapper = mountDialog(mt5Props)

    expect(mt5Wrapper.find('input[placeholder="MT5 Login"]').exists()).toBe(true)
    mt5Wrapper.findAllComponents(RadioGroupStub)[0].vm.$emit('update:modelValue', 'live')
    mt5Wrapper.findAllComponents(RadioGroupStub)[0].vm.$emit('change', 'live')
    await nextTick()
    expect(mt5Wrapper.emitted('update:mt5Env')).toEqual([['live']])
    expect(mt5Props.onMt5EnvChange).toHaveBeenCalledTimes(1)
    mt5Wrapper.unmount()

    const ibProps = makeProps()
    ibProps.connectForm.exchange_type = 'IB_WEB'
    const ibWrapper = mountDialog(ibProps)

    expect(ibWrapper.find('input[placeholder="https://localhost:5000"]').exists()).toBe(true)
    ibWrapper.findAllComponents(RadioGroupStub)[0].vm.$emit('update:modelValue', 'live')
    ibWrapper.findAllComponents(RadioGroupStub)[0].vm.$emit('change', 'live')
    await nextTick()
    expect(ibWrapper.emitted('update:ibEnv')).toEqual([['live']])
    expect(ibProps.onIbEnvChange).toHaveBeenCalledTimes(1)
    expect(ibWrapper.find('input[placeholder="如 DU123456"]').exists()).toBe(true)
    ibWrapper.unmount()
  })
})
