import request from '@/api/index'

export type ServiceGatewayOperatorRole = 'account_session_worker' | 'market_hub'
export type ServiceGatewayOperatorAction = 'start' | 'recover' | 'cleanup' | 'stop'

export interface ServiceGatewayOperatorProfile {
  profile_ref: string
  role: ServiceGatewayOperatorRole
  account_ref: string | null
  operations: Array<'status' | ServiceGatewayOperatorAction>
  auto_start: boolean
}

export interface ServiceGatewayOperatorStatus {
  profile_ref: string
  account_ref: string | null
  role: ServiceGatewayOperatorRole
  state: 'new' | 'starting' | 'running' | 'stopping' | 'uncertain' | 'closed' | 'failed' | 'unknown'
  ready: boolean
  error_code: string | null
  operation: {
    name: string | null
    state: 'idle' | 'running' | 'succeeded' | 'failed' | 'outcome_uncertain'
    error_code: string | null
  }
  account_session: {
    state: string
    session_generation: string | null
    ready: boolean
    fresh_for_seconds: number
  } | null
  cleanup: {
    unclaimed_provider_count: number | null
    last_cleanup_code: string | null
  }
}

interface ServiceGatewayOperatorList {
  operators: ServiceGatewayOperatorProfile[]
}

const operatorPath = (profileRef: string) =>
  `/service-gateway/operators/${encodeURIComponent(profileRef)}`

export const serviceGatewayOperatorApi = {
  list(): Promise<ServiceGatewayOperatorList> {
    return request.get('/service-gateway/operators', { suppressErrorToast: true })
  },

  status(profileRef: string): Promise<ServiceGatewayOperatorStatus> {
    return request.get(operatorPath(profileRef), { suppressErrorToast: true })
  },

  act(profileRef: string, action: ServiceGatewayOperatorAction): Promise<ServiceGatewayOperatorStatus> {
    return request.post(`${operatorPath(profileRef)}/${action}`, undefined, { suppressErrorToast: true })
  },
}
