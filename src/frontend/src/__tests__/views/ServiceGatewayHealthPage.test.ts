import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import i18n from '@/i18n'
import ServiceGatewayHealthPage from '@/views/ServiceGatewayHealthPage.vue'

const mocks = vi.hoisted(() => ({ readAccountHealth: vi.fn() }))

vi.mock('@/api/serviceGateway', () => ({
  serviceGatewayApi: { readAccountHealth: mocks.readAccountHealth },
}))

describe('ServiceGatewayHealthPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.readAccountHealth.mockResolvedValue({
      account_ref: 'acct-a',
      service_connection: { rpc_status: 'reachable' },
      gateway_session: {
        status: 'ready',
        session_generation: 'generation-a',
        fresh_for_seconds: 10,
      },
      account_observation: {
        status: 'observed',
        quality: 'fresh',
        observed_at_utc: '2026-10-16T00:00:00Z',
        received_age_seconds: 1,
        fresh_for_seconds: 5,
        session_generation: 'generation-a',
        cursor: 12,
        same_session_generation: true,
      },
      market_data_feed: { status: 'unobserved' },
      authority: 'authorized SDK Gateway owner status and account observation',
    })
  })

  it('opens without connecting, fetching credentials, or starting any gateway', async () => {
    const wrapper = mount(ServiceGatewayHealthPage, { global: { plugins: [i18n] } })
    await flushPromises()

    expect(wrapper.find('h1').exists()).toBe(true)
    expect(mocks.readAccountHealth).not.toHaveBeenCalled()
    expect(wrapper.find('input').attributes('autocomplete')).toBe('off')
    expect(wrapper.text()).not.toMatch(/connect gateway|saved credentials|credential value/i)
  })

  it('reads and renders distinct owner, account, and feed facts only after submit', async () => {
    const wrapper = mount(ServiceGatewayHealthPage, { global: { plugins: [i18n] } })
    await wrapper.get('input').setValue('acct-a')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(mocks.readAccountHealth).toHaveBeenCalledOnce()
    expect(mocks.readAccountHealth).toHaveBeenCalledWith('acct-a')
    expect(wrapper.get('[data-testid="service-connection-status"]').attributes('data-status')).toBe('reachable')
    expect(wrapper.get('[data-testid="gateway-session-status"]').attributes('data-status')).toBe('ready')
    expect(wrapper.get('[data-testid="account-observation-status"]').attributes('data-status')).toBe('observed')
    expect(wrapper.get('[data-testid="market-feed-status"]').attributes('data-status')).toBe('unobserved')
    expect(wrapper.text()).not.toContain('secret')
  })
})
