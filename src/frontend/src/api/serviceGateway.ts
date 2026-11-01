import request from '@/api/index'

export interface ServiceGatewayHealth {
  account_ref: string
  service_connection: { rpc_status: 'reachable' | 'unobserved' }
  gateway_session: {
    status: 'ready' | 'not_ready' | 'unobserved'
    session_generation: string | null
    fresh_for_seconds: number | null
  }
  account_observation: {
    status: 'observed' | 'unobserved' | 'unavailable'
    quality: 'fresh' | 'stale' | 'unavailable' | 'unobserved'
    observed_at_utc: string | null
    received_age_seconds: number | null
    fresh_for_seconds: number | null
    session_generation: string | null
    cursor: number | null
    same_session_generation: boolean | null
  }
  market_data_feed: { status: 'unobserved' | 'ready' | 'not_ready' | 'unavailable' }
  authority: string
}

export const serviceGatewayApi = {
  readAccountHealth(accountRef: string): Promise<ServiceGatewayHealth> {
    return request.get(`/service-gateway/accounts/${encodeURIComponent(accountRef)}/health`)
  },
}
