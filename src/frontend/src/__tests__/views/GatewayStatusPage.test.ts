import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import GatewayStatusPage from '@/views/GatewayStatusPage.vue'
import { elStubs } from '@/test/stubs'

const liveTradingApiMocks = vi.hoisted(() => ({
  listGatewayHealth: vi.fn(),
  getGatewayCredentials: vi.fn(),
  connectGateway: vi.fn(),
  disconnectGateway: vi.fn(),
}))

const serviceGatewayOperatorApiMocks = vi.hoisted(() => ({
  list: vi.fn(),
  status: vi.fn(),
  act: vi.fn(),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('@element-plus/icons-vue', () => ({
  Refresh: { template: '<span />' },
  Loading: { template: '<span />' },
  CircleCheckFilled: { template: '<span />' },
  CircleCloseFilled: { template: '<span />' },
  Connection: { template: '<span />' },
  Grid: { template: '<span />' },
  List: { template: '<span />' },
  Search: { template: '<span />' },
}))

vi.mock('@/api/liveTrading', () => ({
  liveTradingApi: {
    listGatewayHealth: liveTradingApiMocks.listGatewayHealth,
    getGatewayCredentials: liveTradingApiMocks.getGatewayCredentials,
    connectGateway: liveTradingApiMocks.connectGateway,
    disconnectGateway: liveTradingApiMocks.disconnectGateway,
  },
}))

vi.mock('@/api/serviceGatewayOperator', () => ({
  serviceGatewayOperatorApi: serviceGatewayOperatorApiMocks,
}))

function makeGateway(overrides: Record<string, unknown> = {}) {
  return {
    gateway_key: 'manual:CTP:088888',
    state: 'running',
    is_healthy: true,
    market_connection: 'connected',
    trade_connection: 'connected',
    uptime_sec: 120,
    last_heartbeat: Math.floor(Date.parse('2026-04-02T00:00:05.000Z') / 1000),
    heartbeat_age_sec: 5,
    last_tick_time: null,
    last_order_time: null,
    strategy_count: 1,
    symbol_count: 2,
    tick_count: 10,
    order_count: 1,
    recent_errors: [],
    ref_count: 1,
    instances: ['inst-1'],
    exchange: 'CTP',
    asset_type: 'FUTURE',
    account_id: '088888',
    ...overrides,
  }
}

async function flushUi() {
  await Promise.resolve()
  await Promise.resolve()
  await nextTick()
}

const GatewayAlertStub = defineComponent({
  name: 'GatewayAlertStub',
  props: ['title'],
  setup(props) {
    return () => h('div', { role: 'alert' }, String(props.title ?? ''))
  },
})

describe('GatewayStatusPage', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-02T00:00:10.000Z'))
    setActivePinia(createPinia())
    vi.clearAllMocks()
    document.body.innerHTML = ''
    liveTradingApiMocks.listGatewayHealth.mockResolvedValue({
      total: 2,
      gateways: [
        makeGateway(),
        makeGateway({
          gateway_key: 'manual:IB_WEB:DU123456',
          state: 'error',
          is_healthy: false,
          market_connection: 'error',
          trade_connection: 'disconnected',
          exchange: 'IB_WEB',
          asset_type: 'STK',
          account_id: 'DU123456',
          strategy_count: 0,
          symbol_count: 3,
          tick_count: 0,
          order_count: 0,
          recent_errors: [{ timestamp: 0, source: 'trade', message: 'session expired' }],
          instances: [],
        }),
      ],
    })
    liveTradingApiMocks.getGatewayCredentials.mockResolvedValue({})
    liveTradingApiMocks.connectGateway.mockResolvedValue({ message: 'ok' })
    liveTradingApiMocks.disconnectGateway.mockResolvedValue({ message: 'ok' })
    serviceGatewayOperatorApiMocks.list.mockResolvedValue({ operators: [] })
    serviceGatewayOperatorApiMocks.status.mockResolvedValue({})
    serviceGatewayOperatorApiMocks.act.mockResolvedValue({})
  })

  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  const doMount = () => mount(GatewayStatusPage, {
    attachTo: document.body,
    global: { stubs: { ...elStubs, 'el-alert': GatewayAlertStub } },
  })

  it('mounts without error', () => {
    expect(doMount().exists()).toBe(true)
  })

  it('renders redesigned gateway operations workbench', async () => {
    const wrapper = doMount()
    await flushUi()

    expect(wrapper.find('[data-test="gateway-hero"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="gateway-metrics"]').findAll('.gateway-metric')).toHaveLength(4)
    expect(wrapper.find('[data-test="gateway-workbench"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="service-gateway-operators"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="gateway-card-grid"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('交易网关控制台')
    expect(wrapper.text()).toContain('088888')
    expect(wrapper.text()).toContain('DU123456')
    expect(wrapper.text()).toContain('session expired')
  })

  it('computes healthyCount', async () => {
    const vm = doMount().vm as any
    await flushUi()
    expect(vm.healthyCount).toBe(1)
    expect(vm.totalSymbolCount).toBe(5)
  })

  it('filters gateways by state, health, and keyword', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    await flushUi()

    vm.stateFilter = 'error'
    await nextTick()
    expect(wrapper.text()).not.toContain('088888')
    expect(wrapper.text()).toContain('DU123456')

    vm.stateFilter = 'all'
    vm.healthFilter = 'healthy'
    await nextTick()
    expect(wrapper.text()).toContain('088888')
    expect(wrapper.text()).not.toContain('DU123456')

    vm.healthFilter = 'all'
    vm.gatewaySearch = 'IB_WEB'
    await nextTick()
    expect(wrapper.text()).not.toContain('088888')
    expect(wrapper.text()).toContain('DU123456')
  })

  it('updates heartbeat latency locally between backend polls', async () => {
    const wrapper = doMount()
    const vm = wrapper.vm as any
    await vm.fetchHealth()
    await flushUi()
    expect(vm.gateways).toHaveLength(2)
    expect(vm.formatHeartbeatAge(vm.gateways[0])).toBe('5s')

    liveTradingApiMocks.listGatewayHealth.mockClear()

    await vi.advanceTimersByTimeAsync(3_000)
    await flushUi()

    expect(vm.formatHeartbeatAge(vm.gateways[0])).toBe('8s')
    expect(liveTradingApiMocks.listGatewayHealth).not.toHaveBeenCalled()
  })

  it('shows a health access error and recovers to the empty gateway state', async () => {
    liveTradingApiMocks.listGatewayHealth.mockRejectedValueOnce(new Error('access denied'))
    const wrapper = doMount()
    await flushUi()

    expect(wrapper.get('[data-test="gateway-alert"]').text()).toBe('access denied')
    expect(wrapper.get('[data-test="gateway-empty"]').text()).toContain('暂无已连接网关')

    liveTradingApiMocks.listGatewayHealth.mockResolvedValueOnce({ total: 0, gateways: [] })
    await (wrapper.vm as any).fetchHealth()
    await flushUi()

    expect(wrapper.find('[data-test="gateway-alert"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="gateway-empty"]').text()).toBeTruthy()
    expect(liveTradingApiMocks.listGatewayHealth).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('does not start a trusted operator or connect a legacy Gateway when the page opens', async () => {
    const wrapper = doMount()
    await flushUi()

    expect(serviceGatewayOperatorApiMocks.list).toHaveBeenCalledOnce()
    expect(serviceGatewayOperatorApiMocks.status).not.toHaveBeenCalled()
    expect(serviceGatewayOperatorApiMocks.act).not.toHaveBeenCalled()
    expect(liveTradingApiMocks.connectGateway).not.toHaveBeenCalled()
    expect(wrapper.get('[data-test="operator-empty"]').text()).toContain('没有已授权的 Service Gateway operator')
    wrapper.unmount()
  })
})
