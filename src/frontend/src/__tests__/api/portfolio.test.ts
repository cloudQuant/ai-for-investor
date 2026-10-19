import { describe, it, expect, vi, beforeEach } from 'vitest'
import { portfolioApi } from '@/api/portfolio'
import request from '@/api/index'

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('portfolioApi', () => {
  beforeEach(() => { vi.clearAllMocks() })

  it('getOverview', async () => {
    vi.mocked(request.get).mockResolvedValue({ total_assets: 100000 })
    const r = await portfolioApi.getOverview()
    expect(request.get).toHaveBeenCalledWith('/portfolio/overview')
    expect(r).toEqual({ total_assets: 100000 })
  })

  it('getOverview requests the compact first-screen summary', async () => {
    vi.mocked(request.get).mockResolvedValue({ total_assets: 100000 })
    await portfolioApi.getOverview(true)
    expect(request.get).toHaveBeenCalledWith('/portfolio/overview/summary')
  })

  it('lists composition selector versions with bounded pagination parameters', async () => {
    vi.mocked(request.get).mockResolvedValue({ items: [], total: 0 })
    await portfolioApi.listCompositionVersions(2, 25)
    expect(request.get).toHaveBeenCalledWith('/portfolio/compositions', {
      params: { page: 2, page_size: 25 },
    })
  })

  it('requests the exact owner-listed composition through the overview projection route', async () => {
    vi.mocked(request.get).mockResolvedValue({ portfolio_ref: 'primary', membership_version: 3 })
    await portfolioApi.getCompositionProjection('primary', 3)
    expect(request.get).toHaveBeenCalledWith('/portfolio/overview', {
      params: { portfolio_ref: 'primary', membership_version: 3 },
    })
  })

  it('creates a display-only imported composition with an exact version reference', async () => {
    vi.mocked(request.post).mockResolvedValue({ portfolio_ref: 'import-view', membership_version: 1 })
    const payload = {
      portfolio_ref: 'import-view',
      source_type: 'imported' as const,
      base_currency: 'USD',
      members: [{ kind: 'imported_ledger' as const, ref: 'import-version-1' }],
    }
    await portfolioApi.createCompositionVersion(payload)
    expect(request.post).toHaveBeenCalledWith('/portfolio/compositions', payload)
  })

  it('getPositions', async () => {
    vi.mocked(request.get).mockResolvedValue({ total: 0, positions: [] })
    await portfolioApi.getPositions()
    expect(request.get).toHaveBeenCalledWith('/portfolio/positions')
  })

  it('getTrades with default limit', async () => {
    vi.mocked(request.get).mockResolvedValue({ total: 0, trades: [] })
    await portfolioApi.getTrades()
    expect(request.get).toHaveBeenCalledWith('/portfolio/trades', { params: { limit: 200 } })
  })

  it('getTrades with custom limit', async () => {
    vi.mocked(request.get).mockResolvedValue({ total: 0, trades: [] })
    await portfolioApi.getTrades(50)
    expect(request.get).toHaveBeenCalledWith('/portfolio/trades', { params: { limit: 50 } })
  })

  it('getTrades with workspace ids', async () => {
    vi.mocked(request.get).mockResolvedValue({ total: 0, trades: [] })
    await portfolioApi.getTrades(50, ['ws-a', 'ws-b'])
    expect(request.get).toHaveBeenCalledWith(
      '/portfolio/trades',
      { params: { limit: 50, workspace_ids: 'ws-a,ws-b' } },
    )
  })

  it('getEquity', async () => {
    vi.mocked(request.get).mockResolvedValue({ dates: [], total_equity: [] })
    await portfolioApi.getEquity()
    expect(request.get).toHaveBeenCalledWith('/portfolio/equity', { params: {} })
  })

  it('getEquity filters by workspace IDs', async () => {
    vi.mocked(request.get).mockResolvedValue({ dates: [], total_equity: [] })
    await portfolioApi.getEquity(['ws-running', 'ws-history'])
    expect(request.get).toHaveBeenCalledWith('/portfolio/equity', {
      params: { workspace_ids: 'ws-running,ws-history' },
    })
  })

  it('getAllocation', async () => {
    vi.mocked(request.get).mockResolvedValue({ total: 0, items: [] })
    await portfolioApi.getAllocation()
    expect(request.get).toHaveBeenCalledWith('/portfolio/allocation', { params: {} })
  })

  it('getAllocation with workspace ids', async () => {
    vi.mocked(request.get).mockResolvedValue({ total: 0, items: [] })
    await portfolioApi.getAllocation(['ws-a', 'ws-b'])
    expect(request.get).toHaveBeenCalledWith(
      '/portfolio/allocation',
      { params: { workspace_ids: 'ws-a,ws-b' } },
    )
  })
})
