import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import RiskPolicyPage from '@/views/RiskPolicyPage.vue'
import { elStubs } from '@/test/stubs'

const apiMocks = vi.hoisted(() => ({
  read: vi.fn(),
  draft: vi.fn(),
  approve: vi.fn(),
  publish: vi.fn(),
}))

vi.mock('@/api/riskPolicy', () => ({ riskPolicyApi: apiMocks }))
vi.mock('@/api', () => ({
  getErrorMessage: (_reason: unknown, fallback: string) => fallback,
}))

function policyView(
  accountRef: string,
  policyRef: string,
  policyVersion: string,
  confirmed: boolean,
  state: 'draft' | 'approved' | 'published' = 'published',
) {
  return {
    account_ref: accountRef,
    policy_ref: policyRef,
    policy_version: policyVersion,
    state,
    risk_policy: {
      policy_id: policyRef,
      max_increase_notional: '12.5',
      max_increase_count: 2,
      permit_ttl_seconds: 60,
      require_strategy_allocation: true,
      notional_unit: 'USD',
    },
    owner_confirmed: confirmed,
    owner_confirmed_version: confirmed ? policyVersion : null,
    owner_confirmed_utc: confirmed ? '2026-10-17T00:00:00Z' : null,
    owner_document_available: confirmed,
  }
}

async function track(wrapper: ReturnType<typeof mount>, accountRef: string, policyRef: string) {
  const inputs = wrapper.get('.policy-tracker-form').findAll('input')
  await inputs[0].setValue(accountRef)
  await inputs[1].setValue(policyRef)
  await wrapper.get('.policy-tracker-form').trigger('submit')
  await flushPromises()
  await vi.waitFor(() => {
    const row = wrapper.findAll('.policy-card').find((item) => item.find('h2').text() === accountRef)
    expect(row?.attributes('data-policy-state')).not.toBe('loading')
  })
}

describe('RiskPolicyPage', () => {
  beforeEach(() => vi.clearAllMocks())

  it('keeps publication separate from per-account effect and reports partial activation', async () => {
    apiMocks.read.mockImplementation(async (accountRef: string, policyRef: string) => {
      return accountRef === 'account-a'
        ? policyView(accountRef, policyRef, 'a'.repeat(64), false)
        : policyView(accountRef, policyRef, 'b'.repeat(64), true)
    })
    const wrapper = mount(RiskPolicyPage, { global: { stubs: elStubs } })

    await track(wrapper, 'account-a', 'policy-a-v2')
    await track(wrapper, 'account-b', 'policy-b-v1')

    expect(wrapper.text()).toContain('已发布 · 等待账户确认')
    expect(wrapper.text()).toContain('账户已确认精确版本')
    expect(wrapper.text()).toContain('部分账户已确认')
    expect(wrapper.text()).toContain('这不表示消费者已加载政策')
    expect(wrapper.text()).toContain('b'.repeat(64))
    expect(wrapper.get('[data-policy-state="awaiting"]').text()).toContain('a'.repeat(64))
    expect(wrapper.get('[data-policy-state="confirmed"]').text()).toContain('b'.repeat(64))
    expect(wrapper.text()).toContain('发布不等于账户确认')
    expect(wrapper.text()).toContain('账户确认不证明运行中的策略消费者已加载该版本')
    expect(wrapper.text()).not.toContain('已确认生效')
    expect(wrapper.text()).not.toContain('解除冻结')
    expect(wrapper.text()).not.toContain('手动确认账户')
    expect(apiMocks.read).toHaveBeenNthCalledWith(1, 'account-a', 'policy-a-v2')
    expect(apiMocks.read).toHaveBeenNthCalledWith(2, 'account-b', 'policy-b-v1')
  })

  it('does not label an unreadable account effective and surfaces denied operations', async () => {
    apiMocks.read.mockRejectedValue({ response: { status: 403 } })
    const wrapper = mount(RiskPolicyPage, { global: { stubs: elStubs } })

    await track(wrapper, 'account-private', 'policy-private-v1')

    expect(wrapper.get('[data-policy-state="unavailable"]').text()).toContain('状态不可用')
    expect(wrapper.text()).toContain('需要检查账户状态')
    expect(wrapper.text()).toContain('当前用户无权读取此账户的政策或执行所请求的操作')
    expect(wrapper.text()).not.toContain('账户已确认精确版本')
  })

  it('keeps the maker/checker publication flow distinct from account confirmation', async () => {
    let state: 'draft' | 'approved' | 'published' = 'draft'
    apiMocks.draft.mockResolvedValue({ state: 'draft' })
    apiMocks.approve.mockImplementation(async () => {
      state = 'approved'
      return { state }
    })
    apiMocks.publish.mockImplementation(async () => {
      state = 'published'
      return { state }
    })
    apiMocks.read.mockImplementation(async (accountRef: string, policyRef: string) => {
      return policyView(accountRef, policyRef, 'c'.repeat(64), false, state)
    })

    const wrapper = mount(RiskPolicyPage, { global: { stubs: elStubs } })
    const inputs = wrapper.get('.policy-draft-form').findAll('input')
    await inputs[0].setValue('account-maker-checker')
    await inputs[1].setValue('policy-maker-checker-v1')
    await inputs[2].setValue('25')
    await wrapper.get('.policy-draft-form').trigger('submit')
    await flushPromises()
    await vi.waitFor(() => {
      const row = wrapper.findAll('.policy-card').find((item) => item.find('h2').text() === 'account-maker-checker')
      expect(row?.attributes('data-policy-state')).toBe('draft')
    })
    expect(wrapper.get('.activation-summary').attributes('data-state')).toBe('not-confirmed')
    expect(wrapper.get('.activation-summary').text()).toContain('尚无账户确认版本')

    expect(apiMocks.draft).toHaveBeenCalledWith('account-maker-checker', {
      policy_ref: 'policy-maker-checker-v1',
      max_increase_notional: '25',
      max_increase_count: 1,
      permit_ttl_seconds: 60,
      require_strategy_allocation: true,
      notional_unit: null,
    })
    expect(wrapper.get('[data-policy-state="draft"]')).toBeTruthy()

    const approveButton = wrapper.findAll('button').find((button) => button.text().includes('checker 权限'))
    expect(approveButton).toBeTruthy()
    await approveButton!.trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-policy-state="approved"]').exists()).toBe(true))
    expect(apiMocks.approve).toHaveBeenCalledWith('account-maker-checker', 'policy-maker-checker-v1')
    expect(wrapper.get('[data-policy-state="approved"]').text()).toContain('待发布')

    const publishButton = wrapper.findAll('button').find((button) => button.text().includes('maker 权限'))
    expect(publishButton).toBeTruthy()
    await publishButton!.trigger('click')
    await flushPromises()
    await vi.waitFor(() => expect(wrapper.find('[data-policy-state="awaiting"]').exists()).toBe(true))
    expect(apiMocks.publish).toHaveBeenCalledWith('account-maker-checker', 'policy-maker-checker-v1')
    expect(wrapper.get('[data-policy-state="awaiting"]').text()).toContain('等待账户确认')
    expect(wrapper.text()).not.toContain('账户已确认精确版本')
  })
})
