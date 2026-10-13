import { flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'

import DataTopicsPage from '@/views/data/DataTopicsPage.vue'
import { mountWithPlugins } from '../mountWithPlugins'

const apiMocks = vi.hoisted(() => ({
  listTopics: vi.fn(),
  refreshTopic: vi.fn(),
  getStats: vi.fn(),
  buildTopicStreamUrl: vi.fn((topic: string) => `ws://test/${topic}`),
  buildPatternStreamUrl: vi.fn((pattern: string) => `ws://test?pattern=${pattern}`),
  getWebSocketProtocols: vi.fn(() => ['access-token', 'token']),
}))

const authStoreState = vi.hoisted(() => ({
  user: { is_admin: true },
}))

vi.mock('@/api/dataTopics', () => ({
  dataTopicsApi: apiMocks,
}))

vi.mock('element-plus', () => ({
  ElMessage: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}))

vi.mock('@/stores/auth', () => ({
  useAuthStore: () => authStoreState,
}))

describe('DataTopicsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    authStoreState.user = { is_admin: true }
    apiMocks.listTopics.mockResolvedValue({
      items: [
        {
          topic: 'market:quote:RB2510',
          has_value: true,
          updated_at_ms: 123,
          policy: { ttl_ms: 200 },
          subscription_count: 1,
          last_error: null,
        },
      ],
      total: 1,
    })
    apiMocks.refreshTopic.mockResolvedValue({ topic: 'market:quote:RB2510', value: { symbol: 'RB2510', price: 101 } })
    apiMocks.getStats.mockResolvedValue({
      total_topics: 1,
      topics_with_value: 1,
      subscription_count: 1,
      error_count: 0,
      ws_gateway: { connection_count: 1, subscription_count: 1 },
    })
  })

  it('loads topics, stats, and refreshes selected topic', async () => {
    const wrapper = mountWithPlugins(DataTopicsPage)
    expect(wrapper.find('[data-test="data-topics-page"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('数据主题中心')
    expect(wrapper.text()).toContain('订阅控制台')

    await flushPromises()
    await (wrapper.vm as any).refreshSelectedTopic()
    await flushPromises()

    expect(apiMocks.listTopics).toHaveBeenCalled()
    expect(apiMocks.getStats).toHaveBeenCalled()
    expect(apiMocks.refreshTopic).toHaveBeenCalledWith('market:quote:RB2510')
    expect(wrapper.text()).toContain('market:quote:RB2510')
    expect(wrapper.text()).toContain('RB2510')
    expect(wrapper.text()).toContain('最近刷新值')
  })

  it('skips admin stats for non-admin users', async () => {
    authStoreState.user = { is_admin: false }

    mountWithPlugins(DataTopicsPage)
    await flushPromises()

    expect(apiMocks.listTopics).toHaveBeenCalled()
    expect(apiMocks.getStats).not.toHaveBeenCalled()
  })

  it('clears a stale selection when the refreshed topic list is empty', async () => {
    const wrapper = mountWithPlugins(DataTopicsPage)
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.selectedTopic).toBe('market:quote:RB2510')
    apiMocks.listTopics.mockResolvedValueOnce({ items: [], total: 0 })

    await vm.loadData()

    expect(vm.topics).toEqual([])
    expect(vm.selectedTopic).toBe('')
    expect(vm.loading).toBe(false)
    expect(wrapper.find('.topics-empty-state').exists()).toBe(true)
    expect(apiMocks.getStats).toHaveBeenCalledTimes(2)
  })

  it('falls back to the first topic when a selected topic disappears', async () => {
    const wrapper = mountWithPlugins(DataTopicsPage)
    await flushPromises()
    const vm = wrapper.vm as any
    vm.selectTopic('removed-topic')
    apiMocks.listTopics.mockResolvedValueOnce({
      items: [{
        topic: 'market:quote:CU2610',
        has_value: false,
        updated_at_ms: 0,
        policy: null,
        subscription_count: 0,
        last_error: { code: 'stale' },
      }],
      total: 1,
    })

    await vm.loadData()

    expect(vm.selectedTopic).toBe('market:quote:CU2610')
    expect(wrapper.text()).toContain('market:quote:CU2610')
    expect(wrapper.text()).toContain('无刷新策略')
    expect(wrapper.text()).toContain('{"code":"stale"}')
    expect(vm.loading).toBe(false)
  })

  it('reports list failures, keeps prior rows, and clears loading state', async () => {
    const wrapper = mountWithPlugins(DataTopicsPage)
    await flushPromises()
    apiMocks.listTopics.mockRejectedValueOnce(new Error('topics service unavailable'))

    await (wrapper.vm as any).loadData()

    expect((wrapper.vm as any).loading).toBe(false)
    expect((wrapper.vm as any).topics).toHaveLength(1)
    expect(wrapper.text()).toContain('market:quote:RB2510')
    expect(ElMessage.error).toHaveBeenCalledWith(
      '加载主题失败: topics service unavailable'
    )
  })

  it('preserves the previous preview and resets refresh loading after a refresh failure', async () => {
    const wrapper = mountWithPlugins(DataTopicsPage)
    await flushPromises()
    const vm = wrapper.vm as any
    vm.latestValue = { symbol: 'RB2510', price: 101 }
    apiMocks.refreshTopic.mockRejectedValueOnce(new Error('upstream unavailable'))

    await vm.refreshSelectedTopic()

    expect(apiMocks.refreshTopic).toHaveBeenCalledWith('market:quote:RB2510')
    expect(vm.latestValue).toEqual({ symbol: 'RB2510', price: 101 })
    expect(vm.refreshing).toBe(false)
    expect(ElMessage.error).toHaveBeenCalledWith(
      '刷新主题失败: upstream unavailable'
    )
  })

  it('formats refresh policies and duration boundaries', () => {
    const vm = mountWithPlugins(DataTopicsPage).vm as any

    expect(vm.formatDuration()).toBeNull()
    expect(vm.formatDuration(Number.NaN)).toBeNull()
    expect(vm.formatDuration(0)).toBe('0ms')
    expect(vm.formatDuration(999)).toBe('999ms')
    expect(vm.formatDuration(1500)).toBe('2s')
    expect(vm.formatDuration(60_000)).toBe('1min')
    expect(vm.policySummary(null)).toBe('无刷新策略')
    expect(vm.policySummary({})).toBe('无刷新策略')
    expect(vm.policySummary({
      push_only: true,
      ttl_ms: 999,
      min_interval_ms: 60_000,
      coalesce_within_ms: 250,
      drop_on_idle: true,
      pause_when_inactive: true,
    })).toBe('仅推送 · TTL 999ms · 最小间隔 1min')
  })

  it('handles missing websocket credentials and stream lifecycle messages', async () => {
    const originalDescriptor = Object.getOwnPropertyDescriptor(window, 'WebSocket')
    const sockets: Array<{
      url: string
      protocols: string[]
      close: ReturnType<typeof vi.fn>
      onopen: ((event: Event) => void) | null
      onmessage: ((event: MessageEvent) => void) | null
      onclose: ((event: CloseEvent) => void) | null
      onerror: ((event: Event) => void) | null
    }> = []
    class FakeWebSocket {
      close = vi.fn()
      onopen: ((event: Event) => void) | null = null
      onmessage: ((event: MessageEvent) => void) | null = null
      onclose: ((event: CloseEvent) => void) | null = null
      onerror: ((event: Event) => void) | null = null

      constructor(public url: string, public protocols: string[]) {
        sockets.push(this)
      }
    }
    Object.defineProperty(window, 'WebSocket', {
      configurable: true,
      writable: true,
      value: FakeWebSocket,
    })

    const wrapper = mountWithPlugins(DataTopicsPage)
    try {
      await flushPromises()
      const vm = wrapper.vm as any
      apiMocks.getWebSocketProtocols.mockReturnValueOnce([])
      vm.connectStream()
      expect(ElMessage.error).toHaveBeenCalledWith('WebSocket token 不可用')
      expect(sockets).toHaveLength(0)

      vm.connectStream()
      expect(sockets[0].url).toBe('ws://test/market:quote:RB2510')
      expect(sockets[0].protocols).toEqual(['access-token', 'token'])
      sockets[0].onopen?.(new Event('open'))
      expect(vm.wsConnected).toBe(true)

      sockets[0].onmessage?.({
        data: JSON.stringify({ type: 'snapshot', value: { symbol: 'RB2510', price: 102 } }),
      } as MessageEvent)
      expect(vm.latestValue).toEqual({ symbol: 'RB2510', price: 102 })
      expect(vm.liveEvents[0].type).toBe('snapshot')

      sockets[0].onmessage?.({ data: 'not-json' } as MessageEvent)
      expect(vm.liveEvents[0]).toEqual({ type: 'raw', data: 'not-json' })
      expect(vm.liveEventsText).toContain('not-json')

      vm.connectStream()
      expect(sockets[0].close).toHaveBeenCalled()
      sockets[1].onopen?.(new Event('open'))
      sockets[1].onerror?.(new Event('error'))
      expect(vm.wsConnected).toBe(false)
      sockets[1].onclose?.(new CloseEvent('close'))
      expect(vm.wsConnected).toBe(false)
    } finally {
      wrapper.unmount()
      if (originalDescriptor) {
        Object.defineProperty(window, 'WebSocket', originalDescriptor)
      }
    }
  })
})
