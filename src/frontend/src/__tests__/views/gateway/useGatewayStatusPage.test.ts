import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useGatewayStatusPage } from '@/views/gateway/useGatewayStatusPage'

const mocks = vi.hoisted(() => ({
  listGatewayHealth: vi.fn(),
  getErrorMessage: vi.fn((error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
  ),
}))

vi.mock('@/api', () => ({
  getErrorMessage: mocks.getErrorMessage,
}))

vi.mock('@/api/liveTrading', () => ({
  liveTradingApi: {
    listGatewayHealth: mocks.listGatewayHealth,
  },
}))

const Harness = defineComponent({
  setup() {
    return useGatewayStatusPage()
  },
  render: () => null,
})

function makeGateway(overrides: Record<string, unknown> = {}) {
  return {
    gateway_key: 'manual:CTP:account-1',
    state: 'running',
    is_healthy: true,
    market_connection: 'connected',
    trade_connection: 'connected',
    uptime_sec: 120,
    last_heartbeat: Math.floor(Date.parse('2026-10-13T00:00:00.000Z') / 1000),
    heartbeat_age_sec: 5,
    last_tick_time: null,
    last_order_time: null,
    strategy_count: 1,
    symbol_count: 2,
    tick_count: 10,
    order_count: 1,
    recent_errors: [],
    ref_count: 1,
    instances: ['instance-1'],
    exchange: 'CTP',
    asset_type: 'FUTURE',
    account_id: 'account-1',
    ...overrides,
  }
}

async function flushUi() {
  await flushPromises()
}

function mountPage() {
  return mount(Harness)
}

describe('useGatewayStatusPage', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-13T00:00:10.000Z'))
    vi.clearAllMocks()
    mocks.listGatewayHealth.mockResolvedValue({ total: 0, gateways: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads healthy, disconnected and direct gateways and applies visible filters', async () => {
    mocks.listGatewayHealth.mockResolvedValueOnce({
      total: 3,
      gateways: [
        makeGateway(),
        makeGateway({
          gateway_key: 'manual:IB_WEB:account-2',
          state: 'error',
          is_healthy: false,
          market_connection: 'disconnected',
          trade_connection: 'error',
          symbol_count: 3,
          recent_errors: [{ source: 'market', message: 'permission denied' }],
        }),
        makeGateway({ gateway_key: 'direct:sim:account-3', symbol_count: 50 }),
      ],
    })

    const wrapper = mountPage()
    await flushUi()
    const page = wrapper.vm as any

    expect(mocks.listGatewayHealth).toHaveBeenCalledTimes(1)
    expect(page.gateways).toHaveLength(3)
    expect(page.visibleGateways.map((gateway: { gateway_key: string }) => gateway.gateway_key)).toEqual([
      'manual:CTP:account-1',
      'manual:IB_WEB:account-2',
    ])
    expect(page.healthyCount).toBe(1)
    expect(page.totalSymbolCount).toBe(5)
    expect(page.totalOrderCount).toBe(2)

    page.stateFilter = 'error'
    await wrapper.vm.$nextTick()
    expect(page.visibleGateways.map((gateway: { state: string }) => gateway.state)).toEqual(['error'])

    page.stateFilter = 'all'
    page.healthFilter = 'healthy'
    await wrapper.vm.$nextTick()
    expect(page.visibleGateways.map((gateway: { is_healthy: boolean }) => gateway.is_healthy)).toEqual([true])

    page.healthFilter = 'all'
    page.gatewaySearch = 'permission denied'
    await wrapper.vm.$nextTick()
    expect(page.visibleGateways.map((gateway: { gateway_key: string }) => gateway.gateway_key)).toEqual([
      'manual:IB_WEB:account-2',
    ])

    page.gatewaySearch = 'no matching gateway'
    await wrapper.vm.$nextTick()
    expect(page.visibleGateways).toEqual([])
    wrapper.unmount()
  })

  it('surfaces an access error and clears it when an empty health response succeeds', async () => {
    mocks.listGatewayHealth.mockRejectedValueOnce(new Error('forbidden'))
    const wrapper = mountPage()
    await flushUi()
    const page = wrapper.vm as any

    expect(page.loadError).toBe('forbidden')
    expect(page.loading).toBe(false)

    mocks.listGatewayHealth.mockResolvedValueOnce({ total: 0, gateways: [] })
    await page.fetchHealth()
    await flushUi()

    expect(page.loadError).toBe('')
    expect(page.gateways).toEqual([])
    expect(page.loading).toBe(false)
    wrapper.unmount()
  })

  it('keeps manual credential and runtime controls out of the health controller', async () => {
    const wrapper = mountPage()
    await flushUi()
    const page = wrapper.vm as any
    expect(page.openConnectDialog).toBeUndefined()
    expect(page.handleConnect).toBeUndefined()
    expect(page.handleDisconnect).toBeUndefined()
    expect(mocks.listGatewayHealth).toHaveBeenCalledOnce()
    wrapper.unmount()
  })

  it('polls health and stops both timers when unmounted', async () => {
    const wrapper = mountPage()
    await flushUi()
    const page = wrapper.vm as any
    expect(typeof page.nowMs).toBe('number')
    mocks.listGatewayHealth.mockClear()

    await vi.advanceTimersByTimeAsync(10_000)
    await flushUi()
    expect(mocks.listGatewayHealth).toHaveBeenCalledTimes(1)

    wrapper.unmount()
    mocks.listGatewayHealth.mockClear()
    await vi.advanceTimersByTimeAsync(20_000)
    expect(mocks.listGatewayHealth).not.toHaveBeenCalled()
  })
})
