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
    await serviceGatewayOperatorApi.status('account-owner-r1')
    await serviceGatewayOperatorApi.act('account-owner-r1', 'start')

    expect(requestMocks.get).toHaveBeenNthCalledWith(1, '/service-gateway/operators', {
      suppressErrorToast: true,
    })
    expect(requestMocks.get).toHaveBeenNthCalledWith(2, '/service-gateway/operators/account-owner-r1', {
      suppressErrorToast: true,
    })
    expect(requestMocks.post).toHaveBeenCalledOnce()
    expect(requestMocks.post).toHaveBeenCalledWith(
      '/service-gateway/operators/account-owner-r1/start',
      undefined,
      { suppressErrorToast: true },
    )
  })
})
