import { beforeEach, describe, expect, it, vi } from 'vitest'
import request from '@/api/index'
import { serviceGatewayApi } from '@/api/serviceGateway'

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('serviceGatewayApi', () => {
  beforeEach(() => vi.clearAllMocks())

  it('uses only the authorized health GET and safely encodes the account selector', async () => {
    vi.mocked(request.get).mockResolvedValue({ account_ref: 'paper/account' })

    await serviceGatewayApi.readAccountHealth('paper/account')

    expect(request.get).toHaveBeenCalledWith('/service-gateway/accounts/paper%2Faccount/health')
    expect(request.post).not.toHaveBeenCalled()
  })
})
