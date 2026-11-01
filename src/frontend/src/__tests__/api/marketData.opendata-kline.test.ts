import { beforeEach, describe, expect, it, vi } from 'vitest'

import api from '@/api/index'
import {
  classifyMarketDataRouteSelection,
  marketDataApi,
  parseOpenDataDirectKlineResponse,
  type MarketDataCapabilitiesResponse,
  type MarketDataCapabilityStateResponse,
  type OpenDataDirectKlineRequest,
  type OpenDataDirectKlineResponse,
} from '@/api/marketData'

vi.mock('@/api/index', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

const ROLLOUT_IDS = [
  'market-data.query-v2',
  'market-data.online-fetch',
  'market-data.research-cache-fill',
  'market-data.research-backtest-bridge',
] as const

const OPENDATA_ROUTE = 'opendata-stock-daily-v1'
const LEGACY_KLINE_ROUTE = 'akshare-stock-kline-legacy-v1'
const EFFECTIVE_PREREQUISITE_CASES = ([0, 1, 4] as const).flatMap((stateIndex) => (
  (['declared', 'installed', 'verified', 'authorized'] as const).map((field) => ({
    stateIndex,
    field,
  }))
))

const REQUEST: OpenDataDirectKlineRequest = {
  symbol: '000001',
  start_date: '2026-10-01',
  end_date: '2026-10-02',
  period: 'daily',
}

function lifecycleState(
  capabilityId: string,
  scope: 'rollout' | 'route',
  routeId: string | null,
  effective: boolean,
): MarketDataCapabilityStateResponse {
  return {
    capability_id: capabilityId,
    scope,
    route_id: routeId,
    declared: effective,
    installed: effective,
    verified: effective,
    authorized: effective,
    effective,
    reason_code: effective ? null : 'CAPABILITY_LEDGER_MISSING',
  }
}

function capabilities(
  mode: 'opendata' | 'opendata_ineffective' | 'legacy' = 'opendata',
): MarketDataCapabilitiesResponse & { capability_states: MarketDataCapabilityStateResponse[] } {
  const queryEnabled = mode !== 'legacy'
  const onlineEnabled = mode === 'opendata'
  const rolloutEffective = [queryEnabled, onlineEnabled, false, false]
  const states = ROLLOUT_IDS.map((id, index) => (
    lifecycleState(id, 'rollout', null, rolloutEffective[index] as boolean)
  ))
  const routeId = mode === 'legacy' ? LEGACY_KLINE_ROUTE : OPENDATA_ROUTE
  states.push(lifecycleState(
    `market-data.route:${routeId}`,
    'route',
    routeId,
    mode === 'opendata',
  ))
  return {
    version: 'market-data-capabilities-v1',
    query_v2_enabled: queryEnabled,
    online_fetch_enabled: onlineEnabled,
    research_cache_fill_enabled: false,
    research_backtest_bridge_enabled: false,
    capability_states: states,
  }
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function directResponse(): OpenDataDirectKlineResponse {
  const records = [
    {
      date: '2026-10-01',
      open: 10,
      high: 12,
      low: 9,
      close: 11,
      volume: 1200,
      change: 1.25,
    },
    {
      date: '2026-10-02',
      open: 11,
      high: 13,
      low: 10,
      close: 12,
      volume: 1500,
      change: 9.09,
    },
  ]
  return {
    symbol: REQUEST.symbol,
    count: records.length,
    kline: {
      dates: records.map((record) => record.date),
      ohlc: records.map((record) => [
        record.open,
        record.close,
        record.low,
        record.high,
      ] as const),
      volumes: records.map((record) => record.volume),
    },
    records,
    provenance: {
      provider_id: 'opendata',
      provider_adapter_revision: 'fixture-adapter-v1',
      source_revision: null,
      request_id: 'fixture-request-1',
      retrieved_at: '2026-10-02T16:00:00+08:00',
      raw_payload_sha256: 'a'.repeat(64),
      source_registry_id: 'fixture-source-registry',
      coverage_status: 'unknown',
      source_available_at: 'unknown',
      source_snapshot_id: null,
      observation_revision_ids: null,
      committed_at: null,
      durable_receipt: 'not_created',
    },
  }
}

describe('market-data capability route census', () => {
  it('classifies only the exact complete OpenData census and requires all direct gates', () => {
    expect(classifyMarketDataRouteSelection(capabilities())).toEqual({
      mode: 'opendata_only',
      can_query: true,
      reason: null,
    })

    const ineffective = capabilities('opendata_ineffective')
    const selection = classifyMarketDataRouteSelection(ineffective)
    expect(selection.mode).toBe('opendata_only')
    expect(selection.can_query).toBe(false)
    expect([
      'ONLINE_FETCH_DISABLED',
      'OPENDATA_ROUTE_INEFFECTIVE',
    ]).toContain(selection.reason)
  })

  it('closes a well-formed OpenData selection when the query rollout is disabled', () => {
    const document = capabilities()
    document.query_v2_enabled = false
    document.capability_states[0] = lifecycleState(ROLLOUT_IDS[0], 'rollout', null, false)
    document.capability_states[4] = lifecycleState(
      `market-data.route:${OPENDATA_ROUTE}`,
      'route',
      OPENDATA_ROUTE,
      false,
    )

    expect(classifyMarketDataRouteSelection(document)).toEqual({
      mode: 'opendata_only',
      can_query: false,
      reason: 'QUERY_V2_DISABLED',
    })
  })

  it('recognizes a legacy census from its exact Kline anchor with closed gates', () => {
    const legacy = capabilities('legacy')
    legacy.capability_states.push(lifecycleState(
      'market-data.route:akshare-stock-primary-v1',
      'route',
      'akshare-stock-primary-v1',
      false,
    ))

    expect(classifyMarketDataRouteSelection(legacy)).toEqual({
      mode: 'legacy',
      can_query: false,
      reason: 'LEGACY_POLICY',
    })
  })

  it('keeps an otherwise well-formed OpenData route closed when effective is false', () => {
    const document = capabilities()
    const routeIndex = document.capability_states.findIndex(
      (state) => state.route_id === OPENDATA_ROUTE,
    )
    document.capability_states[routeIndex] = {
      ...document.capability_states[routeIndex]!,
      effective: false,
      reason_code: 'ROUTE_DEPENDENCY_NOT_EFFECTIVE',
    }

    expect(classifyMarketDataRouteSelection(document)).toEqual({
      mode: 'opendata_only',
      can_query: false,
      reason: 'OPENDATA_ROUTE_INEFFECTIVE',
    })
  })

  it.each(EFFECTIVE_PREREQUISITE_CASES)(
    'fails closed when effective state $stateIndex has $field=false',
    ({ stateIndex, field }) => {
      const malformed = clone(capabilities()) as unknown as {
        capability_states: Array<Record<string, unknown>>
      }
      malformed.capability_states[stateIndex] = {
        ...malformed.capability_states[stateIndex],
        [field]: false,
      }

      expect(classifyMarketDataRouteSelection(malformed)).toEqual({
        mode: 'unknown',
        can_query: false,
        reason: 'CAPABILITY_CENSUS_INVALID',
      })
    },
  )

  it.each([
    ['missing capability states', (value: Record<string, unknown>) => {
      delete value.capability_states
    }],
    ['empty census', (value: Record<string, unknown>) => {
      value.capability_states = []
    }],
    ['missing source-policy anchor', (value: Record<string, unknown>) => {
      value.capability_states = (value.capability_states as Array<Record<string, unknown>>)
        .filter((state) => state.route_id !== OPENDATA_ROUTE)
    }],
    ['missing rollout row', (value: Record<string, unknown>) => {
      value.capability_states = (value.capability_states as unknown[]).slice(1)
    }],
    ['duplicate rollout id', (value: Record<string, unknown>) => {
      const states = value.capability_states as unknown[]
      states.push(clone(states[0]))
    }],
    ['top-level gate mismatch', (value: Record<string, unknown>) => {
      value.query_v2_enabled = false
    }],
    ['online top-level gate mismatch', (value: Record<string, unknown>) => {
      value.online_fetch_enabled = false
    }],
    ['cache-fill top-level gate mismatch', (value: Record<string, unknown>) => {
      value.research_cache_fill_enabled = true
    }],
    ['backtest-bridge top-level gate mismatch', (value: Record<string, unknown>) => {
      value.research_backtest_bridge_enabled = true
    }],
    ['wrong rollout capability id', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states[0] = { ...states[0], capability_id: 'market-data.query-v3' }
    }],
    ['duplicate route id', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states.push(clone(states[4]))
    }],
    ['route capability id mismatch', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states[4] = { ...states[4], capability_id: 'market-data.route:other' }
    }],
    ['rollout row with a route id', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states[0] = { ...states[0], route_id: 'unexpected' }
    }],
    ['route row without a route id', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states[4] = { ...states[4], route_id: null }
    }],
    ['route row with the wrong scope', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states[4] = { ...states[4], scope: 'rollout' }
    }],
    ['both source-policy anchors', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      const routeId = LEGACY_KLINE_ROUTE
      states.push({
        ...lifecycleState(
          `market-data.route:${routeId}`,
          'route',
          routeId,
          true,
        ),
      })
    }],
    ['OpenData census with an extra route', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      const routeId = 'akshare-stock-primary-v1'
      states.push({
        ...lifecycleState(
          `market-data.route:${routeId}`,
          'route',
          routeId,
          false,
        ),
      })
    }],
    ['malformed lifecycle field', (value: Record<string, unknown>) => {
      const states = value.capability_states as Array<Record<string, unknown>>
      states[4] = { ...states[4], effective: 'true' }
    }],
  ])('fails closed on %s', (_label, mutate) => {
    const malformed = clone(capabilities()) as unknown as Record<string, unknown>
    mutate(malformed)

    const selection = classifyMarketDataRouteSelection(malformed)
    expect(selection.mode).toBe('unknown')
    expect(selection.can_query).toBe(false)
    expect(selection.reason).toBe('CAPABILITY_CENSUS_INVALID')
  })

  it('distinguishes an unavailable document from a malformed census', () => {
    expect(classifyMarketDataRouteSelection(null)).toEqual({
      mode: 'unknown',
      can_query: false,
      reason: 'CAPABILITIES_UNAVAILABLE',
    })
    expect(classifyMarketDataRouteSelection({
      version: 'market-data-capabilities-v1',
    })).toEqual({
      mode: 'unknown',
      can_query: false,
      reason: 'CAPABILITY_CENSUS_INVALID',
    })
  })
})

describe('OpenData direct Kline response validation', () => {
  it('accepts an aligned, ordered, in-window display-only response', () => {
    expect(parseOpenDataDirectKlineResponse(directResponse(), REQUEST)).toEqual(directResponse())
  })

  it.each([
    ['wrong symbol', (value: Record<string, unknown>) => {
      value.symbol = '600001'
    }],
    ['count mismatch', (value: Record<string, unknown>) => {
      value.count = 1
    }],
    ['misaligned dates', (value: Record<string, unknown>) => {
      const kline = value.kline as Record<string, unknown>
      kline.dates = ['2026-10-02']
    }],
    ['same-length dates that disagree with records', (value: Record<string, unknown>) => {
      const kline = value.kline as Record<string, unknown>
      kline.dates = ['2026-10-01', '2026-10-03']
    }],
    ['unsorted dates', (value: Record<string, unknown>) => {
      const kline = value.kline as Record<string, unknown>
      kline.dates = ['2026-10-02', '2026-10-01']
      const records = value.records as Array<Record<string, unknown>>
      records[0]!.date = '2026-10-02'
      records[1]!.date = '2026-10-01'
    }],
    ['date outside the requested window', (value: Record<string, unknown>) => {
      const kline = value.kline as Record<string, unknown>
      kline.dates = ['2026-09-30', '2026-10-02']
      const records = value.records as Array<Record<string, unknown>>
      records[0]!.date = '2026-09-30'
    }],
    ['non-finite OHLC', (value: Record<string, unknown>) => {
      const kline = value.kline as { ohlc: number[][] }
      kline.ohlc[0]![0] = Number.POSITIVE_INFINITY
      const records = value.records as Array<Record<string, unknown>>
      records[0]!.open = Number.POSITIVE_INFINITY
    }],
    ['unsafe share count', (value: Record<string, unknown>) => {
      const kline = value.kline as { volumes: number[] }
      kline.volumes[0] = Number.MAX_SAFE_INTEGER + 1
      const records = value.records as Array<Record<string, unknown>>
      records[0]!.volume = Number.MAX_SAFE_INTEGER + 1
    }],
    ['negative share count', (value: Record<string, unknown>) => {
      const kline = value.kline as { volumes: number[] }
      kline.volumes[0] = -1
      const records = value.records as Array<Record<string, unknown>>
      records[0]!.volume = -1
    }],
    ['wrong provider provenance', (value: Record<string, unknown>) => {
      const provenance = value.provenance as Record<string, unknown>
      provenance.provider_id = 'akshare'
    }],
    ['durable receipt claim', (value: Record<string, unknown>) => {
      const provenance = value.provenance as Record<string, unknown>
      provenance.durable_receipt = 'created'
    }],
    ['known rather than unknown coverage', (value: Record<string, unknown>) => {
      const provenance = value.provenance as Record<string, unknown>
      provenance.coverage_status = 'complete'
    }],
    ['snapshot provenance', (value: Record<string, unknown>) => {
      const provenance = value.provenance as Record<string, unknown>
      provenance.source_snapshot_id = 'snapshot-1'
    }],
  ])('rejects %s', (_label, mutate) => {
    const malformed = clone(directResponse()) as unknown as Record<string, unknown>
    mutate(malformed)

    expect(parseOpenDataDirectKlineResponse(malformed, REQUEST)).toBeNull()
  })

  it('rejects more than 366 bars', () => {
    const body = directResponse()
    const records = Array.from({ length: 367 }, (_, index) => ({
      ...body.records[0]!,
      date: new Date(Date.UTC(2025, 9, 26 + index)).toISOString().slice(0, 10),
    }))
    const oversized = {
      ...body,
      count: records.length,
      records,
      kline: {
        dates: records.map((record) => record.date),
        ohlc: records.map(() => [10, 11, 9, 12] as const),
        volumes: records.map(() => 100),
      },
    }

    expect(parseOpenDataDirectKlineResponse(oversized, {
      ...REQUEST,
      start_date: '2020-01-01',
      end_date: '2027-12-31',
    })).toBeNull()
  })
})

describe('marketDataApi.getOpenDataDirectKline', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('sends the bounded daily query and forwards cancellation/no-toast controls', async () => {
    const controller = new AbortController()
    const response = directResponse()
    vi.mocked(api.get).mockResolvedValue(response)

    await expect(marketDataApi.getOpenDataDirectKline(REQUEST, {
      signal: controller.signal,
    })).resolves.toEqual(response)

    expect(api.get).toHaveBeenCalledTimes(1)
    expect(api.get).toHaveBeenCalledWith('/data/kline', {
      params: REQUEST,
      signal: controller.signal,
      skipRetry: true,
      suppressErrorToast: true,
    })
  })

  it('throws a fixed validation error for malformed successful responses', async () => {
    const invalid = {
      ...directResponse(),
      symbol: '600001',
      message: 'RAW_UPSTREAM_DETAIL_SENTINEL',
    }
    vi.mocked(api.get).mockResolvedValue(invalid)

    let caught: unknown
    try {
      await marketDataApi.getOpenDataDirectKline(REQUEST)
    } catch (error) {
      caught = error
    }

    expect(caught).toBeInstanceOf(Error)
    expect(String(caught)).not.toContain('RAW_UPSTREAM_DETAIL_SENTINEL')
    expect(api.get).toHaveBeenCalledTimes(1)
  })
})
