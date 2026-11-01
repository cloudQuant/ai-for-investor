import { beforeEach, describe, expect, it, vi } from 'vitest'

const requestMocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}))

vi.mock('@/api/index', () => ({ default: requestMocks }))

import { serviceGatewayOperatorApi } from '@/api/serviceGatewayOperator'

describe('serviceGatewayOperatorApi', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    requestMocks.get.mockResolvedValue({ operators: [] })
    requestMocks.post.mockResolvedValue({ state: 'running' })
  })

  it('uses only the server-listed profile path and sends no browser credentials or scopes', async () => {
    await serviceGatewayOperatorApi.list()
    await serviceGatewayOperatorApi.legacyGateways()
    await serviceGatewayOperatorApi.status('account-owner-r1')
    await serviceGatewayOperatorApi.act('account-owner-r1', 'start')

    expect(requestMocks.get).toHaveBeenNthCalledWith(1, '/service-gateway/operators', {
      suppressErrorToast: true,
    })
    expect(requestMocks.get).toHaveBeenNthCalledWith(2, '/service-gateway/legacy-gateways', {
      suppressErrorToast: true,
    })
    expect(requestMocks.get).toHaveBeenNthCalledWith(3, '/service-gateway/operators/account-owner-r1', {
      suppressErrorToast: true,
    })
    expect(requestMocks.post).toHaveBeenCalledOnce()
    expect(requestMocks.post).toHaveBeenCalledWith(
      '/service-gateway/operators/account-owner-r1/start',
      undefined,
      { suppressErrorToast: true },
    )
  })

  it('loads the owner-authorized migration projection without credentials or action parameters', async () => {
    requestMocks.get.mockResolvedValueOnce({
      gateways: [{
        gateway_key: 'manual:OKX:account-1',
        migration_status: 'profile_available',
        profile_ref: 'account-owner-r1',
      }],
    })

    const result = await serviceGatewayOperatorApi.legacyGateways()

    expect(result.gateways[0].profile_ref).toBe('account-owner-r1')
    expect(requestMocks.get).toHaveBeenCalledWith('/service-gateway/legacy-gateways', {
      suppressErrorToast: true,
    })
    expect(requestMocks.get.mock.calls[0]).toEqual([
      '/service-gateway/legacy-gateways',
      { suppressErrorToast: true },
    ])
  })
})
