import { beforeEach, describe, expect, it, vi } from 'vitest'

import api from '@/api/index'
import {
  marketDataApi,
  parseOpenDataStockDailyFreshnessResponse,
  type OpenDataStockDailyFreshnessResponse,
} from '@/api/marketData'

const apiMocks = vi.hoisted(() => ({ get: vi.fn() }))

vi.mock('@/api/index', () => ({
  default: { get: apiMocks.get },
}))

function freshnessResponse(): OpenDataStockDailyFreshnessResponse {
  return {
    provider: 'opendata',
    domain: 'stock_daily',
    source: null,
    field: 'business_date',
    latest: '2026-10-26',
    lag_days: 0,
    status: 'fresh',
    expected_data_date: '2026-10-26',
    checked_at: '2026-10-27T01:00:00Z',
  }
}

describe('OpenData stock_daily domain freshness', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('accepts only the fixed domain DTO and calendar-date semantics', () => {
    expect(parseOpenDataStockDailyFreshnessResponse(freshnessResponse()))
      .toEqual(freshnessResponse())

    const missing = {
      ...freshnessResponse(),
      field: null,
      latest: null,
      lag_days: null,
      status: 'missing',
    }
    expect(parseOpenDataStockDailyFreshnessResponse(missing)).toMatchObject(missing)

    const latestAfterExpected = {
      ...freshnessResponse(),
      latest: '2026-10-27',
      lag_days: -1,
    }
    expect(parseOpenDataStockDailyFreshnessResponse(latestAfterExpected))
      .toEqual(latestAfterExpected)

    const stale = {
      ...freshnessResponse(),
      latest: '2026-10-25',
      lag_days: 1,
      status: 'stale' as const,
    }
    expect(parseOpenDataStockDailyFreshnessResponse(stale)).toEqual(stale)

    const monthBoundaryStale = {
      ...freshnessResponse(),
      expected_data_date: '2026-03-01',
      latest: '2026-02-28',
      lag_days: 1,
      status: 'stale' as const,
    }
    expect(parseOpenDataStockDailyFreshnessResponse(monthBoundaryStale))
      .toEqual(monthBoundaryStale)

    for (const invalid of [
      { ...freshnessResponse(), provider: 'other' },
      { ...freshnessResponse(), domain: 'instrument_reference' },
      { ...freshnessResponse(), source: 'upstream-source' },
      { ...freshnessResponse(), status: 'unknown' },
      { ...freshnessResponse(), latest: '2026-02-30' },
      { ...freshnessResponse(), expected_data_date: '2026-13-01' },
      { ...freshnessResponse(), checked_at: '2026-10-27 01:00:00' },
      { ...freshnessResponse(), lag_days: 1 },
      { ...monthBoundaryStale, lag_days: 2 },
      { ...latestAfterExpected, lag_days: -2 },
      { ...freshnessResponse(), status: 'stale', lag_days: 0 },
      { ...freshnessResponse(), status: 'missing', latest: '2026-10-26' },
      { ...freshnessResponse(), status: 'missing', field: 'business_date' },
      { ...freshnessResponse(), status: 'stale', field: null },
    ]) {
      expect(parseOpenDataStockDailyFreshnessResponse(invalid)).toBeNull()
    }
  })

  it('uses one bounded, abortable request and maps malformed success to a safe error', async () => {
    const signal = new AbortController().signal
    apiMocks.get.mockResolvedValueOnce(freshnessResponse())

    await expect(marketDataApi.getOpenDataStockDailyFreshness({ signal }))
      .resolves.toEqual(freshnessResponse())
    expect(api.get).toHaveBeenCalledWith(
      '/data/trust/opendata/stock-daily/freshness',
      { signal, skipRetry: true, suppressErrorToast: true },
    )

    apiMocks.get.mockResolvedValueOnce({ ...freshnessResponse(), domain: 'other' })
    await expect(marketDataApi.getOpenDataStockDailyFreshness())
      .rejects.toThrow('OPENDATA_STOCK_DAILY_FRESHNESS_RESPONSE_INVALID')
  })
})
