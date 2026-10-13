import { defineComponent } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useGatewayStatusPage } from '@/views/gateway/useGatewayStatusPage'

const mocks = vi.hoisted(() => ({
  listGatewayHealth: vi.fn(),
  getGatewayCredentials: vi.fn(),
  connectGateway: vi.fn(),
  disconnectGateway: vi.fn(),
  success: vi.fn(),
  getErrorMessage: vi.fn((error: unknown, fallback: string) =>
    error instanceof Error ? error.message : fallback,
  ),
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: mocks.success, error: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/api', () => ({
  getErrorMessage: mocks.getErrorMessage,
}))

vi.mock('@/api/liveTrading', () => ({
  liveTradingApi: {
    listGatewayHealth: mocks.listGatewayHealth,
    getGatewayCredentials: mocks.getGatewayCredentials,
    connectGateway: mocks.connectGateway,
    disconnectGateway: mocks.disconnectGateway,
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
    mocks.getGatewayCredentials.mockResolvedValue({})
    mocks.connectGateway.mockResolvedValue({ message: 'Gateway connected' })
    mocks.disconnectGateway.mockResolvedValue({ message: 'Gateway disconnected' })
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

  it('loads saved presets, connects with the chosen environment, and clears the form', async () => {
    const wrapper = mountPage()
    await flushUi()
    const page = wrapper.vm as any
    mocks.getGatewayCredentials.mockResolvedValueOnce({
      CTP: {
        broker_id: 'saved-broker',
        app_id: 'saved-app',
        auth_code: 'saved-auth',
        user_id: 'saved-user',
        password: 'saved-pass',
      },
      MT5: {
        demo: { login: 1001, password: 'demo-pass', server: 'demo-server' },
        live: { login: 1002, password: 'live-pass', server: 'live-server' },
      },
      IB_WEB: {
        paper: { account_id: 'paper-account', asset_type: 'STK' },
        live: { account_id: 'live-account', asset_type: 'FUT' },
      },
      BINANCE: { account_id: 'binance-account', api_key: 'k', secret_key: 's' },
      OKX: { account_id: 'okx-account', api_key: 'o', secret_key: 's', passphrase: 'p' },
      CUSTOM: { endpoint: 'custom-endpoint' },
    })

    await page.openConnectDialog()
    expect(page.showConnectDialog).toBe(true)
    expect(page.connectForm).toEqual({ exchange_type: '', credentials: {} })

    page.connectForm.exchange_type = 'CTP'
    page.onExchangeChange()
    expect(page.connectForm.credentials).toMatchObject({
      broker_id: 'saved-broker',
      user_id: 'saved-user',
      password: 'saved-pass',
    })
    page.ctpEnv = 'simnow_7x24'
    page.onCtpEnvChange()
    expect(page.connectForm.credentials.td_front).toBe('tcp://182.254.243.31:40001')
    page.ctpEnv = 'simnow'
    page.ctpGroup = 3
    page.onCtpGroupChange()
    expect(page.connectForm.credentials.md_front).toBe('tcp://182.254.243.31:30013')

    page.connectForm.exchange_type = 'MT5'
    page.onExchangeChange()
    expect(page.connectForm.credentials).toMatchObject({ login: 1001, server: 'demo-server' })
    page.mt5Env = 'live'
    page.onMt5EnvChange()
    expect(page.connectForm.credentials).toMatchObject({ login: 1002, server: 'live-server' })

    page.connectForm.exchange_type = 'IB_WEB'
    page.onExchangeChange()
    page.ibEnv = 'live'
    page.onIbEnvChange()
    expect(page.connectForm.credentials).toMatchObject({ account_id: 'live-account', login_mode: 'live' })
    await page.handleConnect()
    await flushUi()

    expect(mocks.connectGateway).toHaveBeenCalledWith({
      exchange_type: 'IB_WEB',
      credentials: expect.objectContaining({ account_id: 'live-account', login_mode: 'live' }),
    })
    expect(mocks.success).toHaveBeenCalledWith('Gateway connected')
    expect(page.showConnectDialog).toBe(false)
    expect(page.connectForm).toEqual({ exchange_type: '', credentials: {} })

    page.connectForm.exchange_type = 'BINANCE'
    page.onExchangeChange()
    expect(page.connectForm.credentials).toMatchObject({ account_id: 'binance-account', asset_type: 'SWAP' })
    page.connectForm.exchange_type = 'OKX'
    page.onExchangeChange()
    expect(page.connectForm.credentials).toMatchObject({ account_id: 'okx-account', passphrase: 'p' })
    page.connectForm.exchange_type = 'CUSTOM'
    page.onExchangeChange()
    expect(page.connectForm.credentials).toMatchObject({ endpoint: 'custom-endpoint' })
    wrapper.unmount()
  })

  it('ignores credential lookup failure and always clears the connect and disconnect states', async () => {
    const wrapper = mountPage()
    await flushUi()
    const page = wrapper.vm as any
    mocks.getGatewayCredentials.mockRejectedValueOnce(new Error('credentials unavailable'))
    await expect(page.openConnectDialog()).resolves.toBeUndefined()
    expect(page.showConnectDialog).toBe(true)

    page.connectForm.exchange_type = 'BINANCE'
    mocks.connectGateway.mockRejectedValueOnce(new Error('connection refused'))
    await page.handleConnect()
    expect(mocks.connectGateway).toHaveBeenCalledWith({ exchange_type: 'BINANCE', credentials: {} })
    expect(page.connecting).toBe(false)
    expect(page.showConnectDialog).toBe(true)

    const gateway = makeGateway()
    page.gateways = [gateway]
    mocks.disconnectGateway.mockRejectedValueOnce(new Error('gateway is busy'))
    await page.handleDisconnect(gateway.gateway_key)
    expect(mocks.disconnectGateway).toHaveBeenCalledWith(gateway.gateway_key)
    expect(page.gateways).toEqual([gateway])
    expect(page.disconnecting).toBe(null)

    mocks.disconnectGateway.mockResolvedValueOnce({ message: 'Disconnected' })
    mocks.listGatewayHealth.mockResolvedValueOnce({ total: 0, gateways: [] })
    await page.handleDisconnect(gateway.gateway_key)
    await flushUi()
    expect(page.gateways).toEqual([])
    expect(mocks.success).toHaveBeenCalledWith('Disconnected')
    expect(page.disconnecting).toBe(null)
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
