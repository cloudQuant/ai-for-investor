import { describe, expect, it, vi, beforeEach } from 'vitest'
import request from '@/api/index'
import { portfolioLedgerApi } from '@/api/portfolioLedger'

vi.mock('@/api/index', () => ({
  default: { get: vi.fn(), post: vi.fn() },
}))

describe('portfolioLedgerApi imported source endpoints', () => {
  beforeEach(() => vi.clearAllMocks())

  it('lists paginated import versions without requesting raw material', async () => {
    vi.mocked(request.get).mockResolvedValue({ items: [], total: 0 })
    await portfolioLedgerApi.listImportSources(2, 25)
    expect(request.get).toHaveBeenCalledWith('/portfolio-ledger/imports', {
      params: { page: 2, page_size: 25 },
    })
  })

  it('loads raw source material only through its exact version id endpoint', async () => {
    vi.mocked(request.get).mockResolvedValue({ import_version_id: 'version/one' })
    await portfolioLedgerApi.getImportSource('version/one')
    expect(request.get).toHaveBeenCalledWith('/portfolio-ledger/imports/version%2Fone')
  })

  it('sends explicit source date and currency while keeping them optional', async () => {
    vi.mocked(request.post).mockResolvedValue({ import_version_id: 'version-1' })
    const payload = {
      format: 'json',
      idempotency_key: 'import-key-1',
      transactions: [{ symbol: 'SYNTH' }],
      source_as_of: '2026-10-13',
      source_currency: 'USD',
    }
    await portfolioLedgerApi.importTransactions('ledger-1', payload)
    expect(request.post).toHaveBeenCalledWith('/portfolio-ledger/ledger-1/import', payload)
  })
})
