import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/api/index', () => ({ default: requestMocks }))

import { riskPolicyApi } from '@/api/riskPolicy'

describe('riskPolicyApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses the authenticated account-policy routes without a caller-supplied role', async () => {
    const draft = {
      policy_ref: 'ordinary-account-v2',
      max_increase_notional: '12.5',
      max_increase_count: 2,
      permit_ttl_seconds: 60,
      require_strategy_allocation: true,
      notional_unit: 'USD',
    }

    await riskPolicyApi.draft('account/a', draft)
    await riskPolicyApi.approve('account/a', 'ordinary-account-v2')
    await riskPolicyApi.publish('account/a', 'ordinary-account-v2')
    await riskPolicyApi.read('account/a', 'ordinary-account-v2')

    expect(requestMocks.post).toHaveBeenNthCalledWith(
      1,
      '/risk-policies/accounts/account%2Fa/policies',
      draft,
    )
    expect(requestMocks.post).toHaveBeenNthCalledWith(
      2,
      '/risk-policies/accounts/account%2Fa/policies/ordinary-account-v2/approve',
    )
    expect(requestMocks.post).toHaveBeenNthCalledWith(
      3,
      '/risk-policies/accounts/account%2Fa/policies/ordinary-account-v2/publish',
    )
    expect(requestMocks.get).toHaveBeenCalledWith(
      '/risk-policies/accounts/account%2Fa/policies/ordinary-account-v2',
    )
    expect(requestMocks.post.mock.calls[0]?.[1]).not.toHaveProperty('actor_role')
    expect(requestMocks.post.mock.calls[0]?.[1]).not.toHaveProperty('principal_ref')
    expect(requestMocks.post.mock.calls[1]).toHaveLength(1)
    expect(requestMocks.post.mock.calls[2]).toHaveLength(1)
  })
})
