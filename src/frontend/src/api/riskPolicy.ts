import request from './index'

export type AccountRiskPolicyState = 'draft' | 'approved' | 'published'

export interface AccountRiskPolicyDraft {
  policy_ref: string
  max_increase_notional: string
  max_increase_count: number
  permit_ttl_seconds: number
  require_strategy_allocation: boolean
  notional_unit: string | null
}

export interface AccountRiskPolicyMutation {
  account_ref: string
  policy_ref: string
  policy_version: string
  state: AccountRiskPolicyState
}

export interface AccountRiskPolicyPublication extends AccountRiskPolicyMutation {
  state: 'published'
  published_utc: string
}

export interface AccountRiskPolicyView extends AccountRiskPolicyMutation {
  risk_policy: {
    policy_id: string
    max_increase_notional: string
    max_increase_count: number
    permit_ttl_seconds: number
    require_strategy_allocation: boolean
    notional_unit: string | null
  }
  owner_confirmed: boolean
  owner_confirmed_version: string | null
  owner_confirmed_utc: string | null
  owner_document_available: boolean
}

const accountPolicyPath = (accountRef: string, policyRef?: string): string => {
  const base = `/risk-policies/accounts/${encodeURIComponent(accountRef)}/policies`
  return policyRef ? `${base}/${encodeURIComponent(policyRef)}` : base
}

/**
 * Ordinary account risk-policy API. Role and account scope are inferred by the
 * backend from the authenticated session; callers cannot submit an actor role.
 */
export const riskPolicyApi = {
  draft(accountRef: string, body: AccountRiskPolicyDraft): Promise<AccountRiskPolicyMutation> {
    return request.post(accountPolicyPath(accountRef), body)
  },

  approve(accountRef: string, policyRef: string): Promise<AccountRiskPolicyMutation> {
    return request.post(`${accountPolicyPath(accountRef, policyRef)}/approve`)
  },

  publish(accountRef: string, policyRef: string): Promise<AccountRiskPolicyPublication> {
    return request.post(`${accountPolicyPath(accountRef, policyRef)}/publish`)
  },

  read(accountRef: string, policyRef: string): Promise<AccountRiskPolicyView> {
    return request.get(accountPolicyPath(accountRef, policyRef))
  },
}
