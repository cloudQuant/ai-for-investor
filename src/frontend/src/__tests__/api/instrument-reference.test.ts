import { beforeEach, describe, expect, it, vi } from 'vitest'

import api from '@/api/index'
import {
  marketDataApi,
  type MarketInstrumentOptionsResponse,
} from '@/api/marketData'
import instrumentReferenceFixture from '../fixtures/instrument_reference_v1.json'

vi.mock('@/api/index', () => ({
  default: {
    get: vi.fn(),
  },
}))

const frozenOptionsResponse = instrumentReferenceFixture.options_response as MarketInstrumentOptionsResponse

describe('instrument reference options API', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.get).mockResolvedValue(frozenOptionsResponse)
  })

  it('preserves the frozen OpenData catalog fields, verified identity, and unknown availability', async () => {
    const response = await marketDataApi.listInstrumentOptions({
      asset_type: 'stock',
      search: '600001',
      limit: 80,
    })

    expect(response).toEqual(frozenOptionsResponse)
    expect(response.catalog_mode).toBe('opendata')
    expect(response.items.every((item) => item.catalog_verified === true)).toBe(true)
    expect(response.items[0]).toEqual(expect.objectContaining({
      instrument_id: expect.any(String),
      data_availability: 'unknown',
      has_snapshot: null,
      has_history: null,
      history_rows: null,
      lifecycle_status: expect.any(String),
    }))
    expect(api.get).toHaveBeenCalledWith('/data/market-instruments/options', {
      params: { asset_type: 'stock', search: '600001', limit: 80 },
    })
  })

  it('sends an explicitly selected effective_on date and omits it when not selected', async () => {
    await marketDataApi.listInstrumentOptions({
      asset_type: 'stock',
      search: 'HIST',
      limit: 80,
      effective_on: '2018-06-01',
    })
    await marketDataApi.listInstrumentOptions({
      asset_type: 'stock',
      search: '600001',
      limit: 80,
    })

    expect(api.get).toHaveBeenNthCalledWith(1, '/data/market-instruments/options', {
      params: {
        asset_type: 'stock',
        search: 'HIST',
        limit: 80,
        effective_on: '2018-06-01',
      },
    })
    expect(api.get).toHaveBeenNthCalledWith(2, '/data/market-instruments/options', {
      params: { asset_type: 'stock', search: '600001', limit: 80 },
    })
  })
})
