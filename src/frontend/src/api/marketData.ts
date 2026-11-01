import request from './index'
import type {
  AssetSpecResponse,
  DataPrecheckRequest,
  DataPrecheckResponse,
  ExecutionModelResponse,
  MarketDataCoverageMatrixResponse,
} from '@/types/trust'

export type MarketAssetType = 'stock' | 'futures' | 'bond' | 'fund' | 'option' | 'fx' | 'crypto'
/**
 * Keep this wire union aligned with the v2 public DTO. A family can declare a
 * bar cadence, reporting period, or point-in-time snapshot; executable state
 * remains server-owned by the reviewed family control plane.
 */
export type MarketDataQueryFrequency = '5min' | '30min' | '1h' | '1d' | '1w' | '1mo' | 'snapshot'
export type MarketDataQueryDataKind = (
  | 'bars'
  | 'quote_snapshot'
  | 'valuation_snapshot'
  | 'option_chain'
  | 'position_report'
  | 'reference_series'
  | 'inventory_report'
  | 'option_risk_surface'
)
export type MarketDataQueryMode = 'local_first' | 'local_only' | 'refresh'
export type MarketDataQueryConsistency = 'display' | 'strict'
export type MarketDataQueryPurpose = (
  | 'display'
  | 'research'
  | 'research_cache_fill'
  | 'backtest'
  | 'export'
)
export const MARKET_DATA_FAMILY_CONTRACT_VERSION = 'market-data-family-v1' as const
export type MarketDataFamilyContractVersion = typeof MARKET_DATA_FAMILY_CONTRACT_VERSION

/**
 * Server-owned effective rollout state for the normalized data platform.
 *
 * These fields intentionally describe enabled capabilities only; they never
 * expose source credentials, provider configuration, or raw deployment flags.
 */
export interface MarketDataCapabilitiesResponse {
  version: 'market-data-capabilities-v1'
  query_v2_enabled: boolean
  online_fetch_enabled: boolean
  research_cache_fill_enabled: boolean
  research_backtest_bridge_enabled: boolean
}

export function hasMarketDataCapabilities(value: unknown): value is MarketDataCapabilitiesResponse {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<MarketDataCapabilitiesResponse>
  return candidate.version === 'market-data-capabilities-v1'
    && typeof candidate.query_v2_enabled === 'boolean'
    && typeof candidate.online_fetch_enabled === 'boolean'
    && typeof candidate.research_cache_fill_enabled === 'boolean'
    && typeof candidate.research_backtest_bridge_enabled === 'boolean'
}

export interface MarketDataCapabilityStateResponse {
  capability_id: string
  scope: 'rollout' | 'route'
  route_id: string | null
  declared: boolean
  installed: boolean
  verified: boolean
  authorized: boolean
  effective: boolean
  reason_code: string | null
}

export interface MarketDataCapabilitiesWithStates extends MarketDataCapabilitiesResponse {
  capability_states: MarketDataCapabilityStateResponse[]
}

export type MarketDataRouteMode = 'legacy' | 'opendata_only' | 'unknown'

export type MarketDataRouteSelectionReason =
  | 'LEGACY_POLICY'
  | 'CAPABILITIES_UNAVAILABLE'
  | 'CAPABILITY_CENSUS_INVALID'
  | 'QUERY_V2_DISABLED'
  | 'ONLINE_FETCH_DISABLED'
  | 'OPENDATA_ROUTE_INEFFECTIVE'

export interface MarketDataRouteSelection {
  mode: MarketDataRouteMode
  can_query: boolean
  reason: MarketDataRouteSelectionReason | null
}

const MARKET_DATA_ROLLOUT_CAPABILITY_IDS = [
  'market-data.query-v2',
  'market-data.online-fetch',
  'market-data.research-cache-fill',
  'market-data.research-backtest-bridge',
] as const

const OPENDATA_STOCK_DAILY_ROUTE_ID = 'opendata-stock-daily-v1'
const AKSHARE_STOCK_KLINE_LEGACY_ROUTE_ID = 'akshare-stock-kline-legacy-v1'

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isMarketDataCapabilityState(value: unknown): value is MarketDataCapabilityStateResponse {
  if (!isPlainRecord(value)) return false
  const { capability_id, scope, route_id, declared, installed, verified, authorized, effective, reason_code } = value
  if (typeof capability_id !== 'string' || capability_id.length < 1 || capability_id.length > 192) return false
  if (scope !== 'rollout' && scope !== 'route') return false
  if (route_id !== null && (typeof route_id !== 'string' || route_id.length < 1 || route_id.length > 128)) {
    return false
  }
  if (
    typeof declared !== 'boolean'
    || typeof installed !== 'boolean'
    || typeof verified !== 'boolean'
    || typeof authorized !== 'boolean'
    || typeof effective !== 'boolean'
  ) return false
  if (effective && (!declared || !installed || !verified || !authorized)) return false
  if (reason_code !== null && (typeof reason_code !== 'string' || reason_code.length > 128)) return false
  if (effective ? reason_code !== null : typeof reason_code !== 'string' || reason_code.trim().length === 0) {
    return false
  }
  if (scope === 'rollout') return route_id === null
  return typeof route_id === 'string' && capability_id === `market-data.route:${route_id}`
}

function marketDataCapabilitiesWithStates(value: unknown): MarketDataCapabilitiesWithStates | null {
  if (!hasMarketDataCapabilities(value) || !isPlainRecord(value)) return null
  const states = value.capability_states
  if (!Array.isArray(states) || !states.every(isMarketDataCapabilityState)) return null

  const capabilityIds = new Set<string>()
  const routeIds = new Set<string>()
  const rolloutIds = new Set<string>()
  for (const state of states) {
    if (capabilityIds.has(state.capability_id)) return null
    capabilityIds.add(state.capability_id)

    if (state.scope === 'rollout') {
      if ((MARKET_DATA_ROLLOUT_CAPABILITY_IDS as readonly string[]).includes(state.capability_id)) {
        if (rolloutIds.has(state.capability_id)) return null
        rolloutIds.add(state.capability_id)
      } else {
        return null
      }
    } else if (state.route_id !== null) {
      if (routeIds.has(state.route_id)) return null
      routeIds.add(state.route_id)
    }
  }

  if (rolloutIds.size !== MARKET_DATA_ROLLOUT_CAPABILITY_IDS.length) return null
  const rolloutById = new Map(
    states
      .filter((state) => state.scope === 'rollout')
      .map((state) => [state.capability_id, state]),
  )
  if (
    value.query_v2_enabled !== rolloutById.get('market-data.query-v2')?.effective
    || value.online_fetch_enabled !== rolloutById.get('market-data.online-fetch')?.effective
    || value.research_cache_fill_enabled !== rolloutById.get('market-data.research-cache-fill')?.effective
    || value.research_backtest_bridge_enabled !== rolloutById.get('market-data.research-backtest-bridge')?.effective
  ) return null

  return value as unknown as MarketDataCapabilitiesWithStates
}

export function classifyMarketDataRouteSelection(value: unknown): MarketDataRouteSelection {
  const capabilities = marketDataCapabilitiesWithStates(value)
  if (!capabilities) {
    return {
      mode: 'unknown',
      can_query: false,
      reason: value === null || value === undefined
        ? 'CAPABILITIES_UNAVAILABLE'
        : 'CAPABILITY_CENSUS_INVALID',
    }
  }

  const routeStates = capabilities.capability_states.filter((state) => state.scope === 'route')
  const opendataState = routeStates.find((state) => state.route_id === OPENDATA_STOCK_DAILY_ROUTE_ID)
  const legacyState = routeStates.find((state) => state.route_id === AKSHARE_STOCK_KLINE_LEGACY_ROUTE_ID)

  if (opendataState && !legacyState) {
    if (routeStates.length !== 1) {
      return { mode: 'unknown', can_query: false, reason: 'CAPABILITY_CENSUS_INVALID' }
    }
    if (!capabilities.query_v2_enabled) {
      return { mode: 'opendata_only', can_query: false, reason: 'QUERY_V2_DISABLED' }
    }
    if (!capabilities.online_fetch_enabled) {
      return { mode: 'opendata_only', can_query: false, reason: 'ONLINE_FETCH_DISABLED' }
    }
    if (!opendataState.effective) {
      return { mode: 'opendata_only', can_query: false, reason: 'OPENDATA_ROUTE_INEFFECTIVE' }
    }
    return { mode: 'opendata_only', can_query: true, reason: null }
  }

  if (legacyState && !opendataState) {
    return { mode: 'legacy', can_query: false, reason: 'LEGACY_POLICY' }
  }

  return { mode: 'unknown', can_query: false, reason: 'CAPABILITY_CENSUS_INVALID' }
}

export interface OpenDataDirectKlineRequest {
  symbol: string
  start_date: string
  end_date: string
  period: 'daily'
}

export interface OpenDataDirectKlineOptions {
  signal?: AbortSignal
}

export interface OpenDataDirectKlineRecord {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
  change: number
}

export interface OpenDataDirectKlineProvenance {
  provider_id: 'opendata'
  provider_adapter_revision: string
  source_revision: null
  request_id: string
  retrieved_at: string
  raw_payload_sha256: string
  source_registry_id: string
  coverage_status: 'unknown'
  source_available_at: 'unknown'
  source_snapshot_id: null
  observation_revision_ids: null
  committed_at: null
  durable_receipt: 'not_created'
}

export interface OpenDataDirectKlineResponse {
  symbol: string
  count: number
  kline: {
    dates: string[]
    ohlc: Array<readonly [open: number, close: number, low: number, high: number]>
    volumes: number[]
  }
  records: OpenDataDirectKlineRecord[]
  provenance: OpenDataDirectKlineProvenance
}

export type OpenDataStockDailyFreshnessStatus = 'fresh' | 'stale' | 'missing'

export interface OpenDataStockDailyFreshnessResponse {
  provider: 'opendata'
  domain: 'stock_daily'
  source: null
  field: string | null
  latest: string | null
  lag_days: number | null
  status: OpenDataStockDailyFreshnessStatus
  expected_data_date: string
  checked_at: string
}

export interface OpenDataStockDailyFreshnessOptions {
  signal?: AbortSignal
}

function isIsoCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const year = Number(value.slice(0, 4))
  const month = Number(value.slice(5, 7))
  const day = Number(value.slice(8, 10))
  if (year < 1 || month < 1 || month > 12) return false
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const daysInMonth = [31, leapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
  return day >= 1 && day <= daysInMonth[month - 1]
}

function isoCalendarDayOrdinal(value: string): number {
  const year = Number(value.slice(0, 4))
  const month = Number(value.slice(5, 7))
  const day = Number(value.slice(8, 10))
  const completedYears = year - 1
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)
  const daysBeforeMonth = [
    0,
    31,
    leapYear ? 60 : 59,
    leapYear ? 91 : 90,
    121,
    152,
    182,
    213,
    244,
    274,
    305,
    335,
  ]
  return completedYears * 365
    + Math.floor(completedYears / 4)
    - Math.floor(completedYears / 100)
    + Math.floor(completedYears / 400)
    + daysBeforeMonth[month - 1]
    + day
}

function calendarDayDifference(laterDate: string, earlierDate: string): number {
  return isoCalendarDayOrdinal(laterDate) - isoCalendarDayOrdinal(earlierDate)
}

function isIsoTimestamp(value: unknown): value is string {
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && isIsoCalendarDate(value.slice(0, 10))
    && Number.isFinite(Date.parse(value))
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isOpenDataDirectKlineProvenance(value: unknown): value is OpenDataDirectKlineProvenance {
  if (!isPlainRecord(value)) return false
  return value.provider_id === 'opendata'
    && typeof value.provider_adapter_revision === 'string'
    && value.provider_adapter_revision.length > 0
    && value.source_revision === null
    && typeof value.request_id === 'string'
    && value.request_id.length > 0
    && isIsoTimestamp(value.retrieved_at)
    && typeof value.raw_payload_sha256 === 'string'
    && /^[a-f0-9]{64}$/.test(value.raw_payload_sha256)
    && typeof value.source_registry_id === 'string'
    && value.source_registry_id.length > 0
    && value.coverage_status === 'unknown'
    && value.source_available_at === 'unknown'
    && value.source_snapshot_id === null
    && value.observation_revision_ids === null
    && value.committed_at === null
    && value.durable_receipt === 'not_created'
}

export function parseOpenDataDirectKlineResponse(
  value: unknown,
  expected: OpenDataDirectKlineRequest,
): OpenDataDirectKlineResponse | null {
  if (
    !expected
    || typeof expected.symbol !== 'string'
    || expected.symbol.length === 0
    || expected.period !== 'daily'
    || !isIsoCalendarDate(expected.start_date)
    || !isIsoCalendarDate(expected.end_date)
    || expected.start_date > expected.end_date
    || Date.parse(`${expected.end_date}T00:00:00Z`)
      - Date.parse(`${expected.start_date}T00:00:00Z`) > 365 * 24 * 60 * 60 * 1000
    || !isPlainRecord(value)
    || value.symbol !== expected.symbol
    || typeof value.count !== 'number'
    || !Number.isSafeInteger(value.count)
    || value.count < 0
    || value.count > 366
    || !Array.isArray(value.records)
    || !isPlainRecord(value.kline)
    || !Array.isArray(value.kline.dates)
    || !Array.isArray(value.kline.ohlc)
    || !Array.isArray(value.kline.volumes)
    || !isOpenDataDirectKlineProvenance(value.provenance)
  ) return null

  const count = value.count
  if (
    value.records.length !== count
    || value.kline.dates.length !== count
    || value.kline.ohlc.length !== count
    || value.kline.volumes.length !== count
  ) return null

  const records: OpenDataDirectKlineRecord[] = []
  const dates: string[] = []
  const ohlc: Array<readonly [number, number, number, number]> = []
  const volumes: number[] = []
  let previousDate = ''

  for (let index = 0; index < count; index += 1) {
    const row = value.records[index]
    const date = value.kline.dates[index]
    const candle = value.kline.ohlc[index]
    const volume = value.kline.volumes[index]
    if (!isPlainRecord(row)) return null

    const recordDate = row.date
    const open = row.open
    const high = row.high
    const low = row.low
    const close = row.close
    const recordVolume = row.volume
    const change = row.change
    if (
      !isIsoCalendarDate(recordDate)
      || recordDate < expected.start_date
      || recordDate > expected.end_date
      || (previousDate !== '' && recordDate <= previousDate)
      || date !== recordDate
      || !Array.isArray(candle)
      || candle.length !== 4
      || !isFiniteNumber(open)
      || !isFiniteNumber(high)
      || !isFiniteNumber(low)
      || !isFiniteNumber(close)
      || typeof recordVolume !== 'number'
      || !Number.isSafeInteger(recordVolume)
      || recordVolume < 0
      || !isFiniteNumber(change)
      || !candle.every(isFiniteNumber)
      || candle[0] !== open
      || candle[1] !== close
      || candle[2] !== low
      || candle[3] !== high
      || volume !== recordVolume
    ) return null

    const record: OpenDataDirectKlineRecord = {
      date: recordDate,
      open,
      high,
      low,
      close,
      volume: recordVolume,
      change,
    }
    records.push(record)
    dates.push(recordDate)
    ohlc.push([open, close, low, high])
    volumes.push(recordVolume)
    previousDate = recordDate
  }

  return {
    symbol: expected.symbol,
    count,
    kline: { dates, ohlc, volumes },
    records,
    provenance: {
      provider_id: 'opendata',
      provider_adapter_revision: value.provenance.provider_adapter_revision,
      source_revision: null,
      request_id: value.provenance.request_id,
      retrieved_at: value.provenance.retrieved_at,
      raw_payload_sha256: value.provenance.raw_payload_sha256,
      source_registry_id: value.provenance.source_registry_id,
      coverage_status: 'unknown',
      source_available_at: 'unknown',
      source_snapshot_id: null,
      observation_revision_ids: null,
      committed_at: null,
      durable_receipt: 'not_created',
    },
  }
}

export function parseOpenDataStockDailyFreshnessResponse(
  value: unknown,
): OpenDataStockDailyFreshnessResponse | null {
  if (
    !isPlainRecord(value)
    || value.provider !== 'opendata'
    || value.domain !== 'stock_daily'
    || value.source !== null
    || (
      value.field !== null
      && (typeof value.field !== 'string' || !/^[a-z][a-z0-9_]{0,127}$/.test(value.field))
    )
    || (
      value.latest !== null
      && !isIsoCalendarDate(value.latest)
    )
    || (
      value.lag_days !== null
      && !Number.isSafeInteger(value.lag_days)
    )
    || (value.status !== 'fresh' && value.status !== 'stale' && value.status !== 'missing')
    || !isIsoCalendarDate(value.expected_data_date)
    || !isIsoTimestamp(value.checked_at)
  ) return null

  if (value.status === 'missing') {
    if (value.field !== null || value.latest !== null || value.lag_days !== null) return null
  } else if (value.latest === null || value.field === null || value.lag_days === null) {
    return null
  } else if (
    calendarDayDifference(
      value.expected_data_date as string,
      value.latest as string,
    ) !== (value.lag_days as number)
    || (value.status === 'fresh' && (value.lag_days as number) > 0)
    || (value.status === 'stale' && (value.lag_days as number) <= 0)
  ) {
    return null
  }

  return {
    provider: 'opendata',
    domain: 'stock_daily',
    source: null,
    field: value.field as string | null,
    latest: value.latest as string | null,
    lag_days: value.lag_days as number | null,
    status: value.status as OpenDataStockDailyFreshnessStatus,
    expected_data_date: value.expected_data_date as string,
    checked_at: value.checked_at as string,
  }
}

/**
 * Server-proven v2 request facts attached to a legacy lookup when, and only
 * when, the API can resolve an exact canonical instrument and active dataset.
 *
 * The frontend deliberately does not derive a canonical ID or dataset code
 * from a symbol.  This keeps the progressive rollout safe while the catalog
 * and master-data bootstrap are incomplete.
 */
/** Every executable v2 query carries both immutable server-issued family axes. */
export interface MarketDataFamilyBinding {
  family_id: string
  family_contract_version: MarketDataFamilyContractVersion
}

export interface MarketDataQueryContractRequestBase {
  identity: {
    canonical_id: string
  }
  dataset_code: string
  data_kind: MarketDataQueryDataKind
  frequency: MarketDataQueryFrequency
  required_fields: string[]
  adjustment?: string | null
  price_basis?: string | null
  currency?: string | null
  unit?: string | null
  source_policy_id: string
  mode: 'local_first'
}

export type MarketDataQueryContractRequest = MarketDataQueryContractRequestBase & MarketDataFamilyBinding

export interface MarketDataQueryContract {
  version: 'market-data-v2'
  request: MarketDataQueryContractRequest
}

export type MarketDataQueryBundleFamilyStatus = 'ready' | 'unconfigured' | 'not_applicable'
export type MarketDataQueryBundleFrequency = MarketDataQueryFrequency
export type MarketDataQueryBundleFrequencySemantics = 'calendar_grid' | 'snapshot' | 'reporting_period'
export type MarketDataQueryBundleCoverageModel = (
  | 'calendar_grid'
  | 'snapshot_freshness'
  | 'slice_completeness'
  | 'report_completeness'
)
export type MarketDataQueryBundleDataKind = MarketDataQueryDataKind

/**
 * A read-only, server-owned declaration of one market-page data family.
 *
 * This is deliberately not executable query input. The data platform still
 * issues a symbol-specific v2 query contract before a client can read bars.
 * Keeping the static bundle separate means an unconfigured family cannot be
 * reconstructed from a legacy page payload.
 */
export interface MarketDataQueryBundleFamily {
  family_id: string
  family_contract_version: MarketDataFamilyContractVersion
  asset_type: MarketAssetType
  status: MarketDataQueryBundleFamilyStatus
  dataset_code: string
  data_kind: MarketDataQueryBundleDataKind
  frequency_semantics: MarketDataQueryBundleFrequencySemantics
  frequencies: MarketDataQueryBundleFrequency[]
  field_profile_id: string
  required_fields: string[]
  optional_fields: string[]
  dimension_fields: string[]
  coverage_model: MarketDataQueryBundleCoverageModel
  source_policy_id: string | null
  reason_code: string | null
}

/**
 * The bundle describes an observation shape only.  It is intentionally not a
 * permission to query facts: callers still need a server-issued, exact query
 * contract before a page can render a specialized or generic observation view.
 */
export type MarketDataFamilyObservationShape = 'single_record' | 'dimensioned_records'

export function marketDataFamilyObservationShape(
  family: Pick<MarketDataQueryBundleFamily, 'data_kind' | 'dimension_fields'>,
): MarketDataFamilyObservationShape {
  if (
    family.dimension_fields.length > 0
    || family.data_kind === 'option_chain'
    || family.data_kind === 'position_report'
    || family.data_kind === 'inventory_report'
    || family.data_kind === 'option_risk_surface'
  ) {
    return 'dimensioned_records'
  }
  return 'single_record'
}

/**
 * Static control-plane response for all data families displayed by one asset
 * tab.  It has no symbol, date range, provider call, or database side effect.
 */
export interface MarketDataQueryBundle {
  version: 'market-data-family-bundle-v1'
  requested_asset_type: MarketAssetType
  families: MarketDataQueryBundleFamily[]
}

export type MarketDataQueryRequest = Omit<MarketDataQueryContractRequestBase, 'mode'> & MarketDataFamilyBinding & {
  start: string
  end: string
  mode: MarketDataQueryMode
  consistency?: MarketDataQueryConsistency
  purpose?: MarketDataQueryPurpose
  knowledge_cutoff?: string
  page_size?: number
  cursor?: string
}

export interface MarketDataQueryOptions {
  signal?: AbortSignal
  suppressErrorMessage?: boolean
}

export interface MarketDataQueryObservation {
  revision_id: string
  source_snapshot_id: string
  event_at: string
  available_at: string
  committed_at: string
  revision_number: number
  quality: string
  fields: Record<string, unknown>
}

export interface MarketDataQueryCoverageGap {
  position: string
  event_at: string[]
  fetch_start: string
  fetch_end: string
}

export interface MarketDataQueryCoverage {
  status: string
  expected_event_count: number
  accepted_event_count: number
  missing_event_count: number
  coverage_ratio: number | null
  gaps: MarketDataQueryCoverageGap[]
  rejection_counts: Record<string, number>
  calendar_reason: string | null
}

export interface MarketDataQueryFetch {
  route_id: string
  provider_id: string
  source_snapshot_id: string
  observation_revision_ids: string[]
  passing_observation_count: number
  failed_observation_count: number
}

export interface MarketDataQueryWarning {
  code: string
  route_id?: string | null
  provider_id?: string | null
}

export interface MarketDataQueryResponse {
  query_id: string
  canonical_id: string
  dataset_code: string
  asset_type: MarketAssetType
  instrument_metadata_version: string
  data_kind: MarketDataQueryDataKind
  frequency: MarketDataQueryFrequency
  source_policy_id: string
  /** Immutable echo of the required public query family binding. */
  family_id: string
  family_contract_version: MarketDataFamilyContractVersion
  knowledge_cutoff: string
  identity_knowledge_cutoff: string
  observations: MarketDataQueryObservation[]
  next_cursor: string | null
  coverage: MarketDataQueryCoverage
  fetches: MarketDataQueryFetch[]
  warnings: MarketDataQueryWarning[]
  refresh_status: 'fresh_complete' | 'fresh_incomplete' | 'fresh_unknown_calendar' | null
  historical_status: 'unknown_calendar' | 'HISTORICAL_COVERAGE_UNAVAILABLE' | null
}

export interface MarketInstrumentLookupParams {
  asset_type: MarketAssetType
  symbol: string
  start_date?: string
  end_date?: string
  period?: string
  market?: string
  refresh_online?: boolean
}

export interface MarketInstrumentOption {
  asset_type: MarketAssetType
  symbol: string
  name: string
  market?: string | null
  exchange?: string | null
  instrument_id?: string | null
  catalog_verified?: boolean
  data_availability?: string | null
  lifecycle?: string | null
  status?: string | null
  lifecycle_status?: string | null
  status_as_of?: string | null
  matched_alias?: {
    alias: string
    alias_version: string
    evidence_ref: string
    valid_from: string | null
    valid_through: string | null
  } | null
  source_table?: string | null
  latest_date?: string | null
  has_snapshot: boolean | null
  has_history: boolean | null
  history_rows: number | null
}

export interface MarketInstrumentOptionsParams {
  asset_type: MarketAssetType
  search?: string
  limit?: number
  /** Only supplied after an explicit user selection for historical aliases. */
  effective_on?: string
}

export interface MarketDataQueryContractParams {
  asset_type: MarketAssetType
  symbol: string
  /**
   * The legacy bridge currently exposes daily/weekly/monthly labels, while a
   * v2 family may declare an intraday cadence or a snapshot.  Keep the wire
   * type representable so a reviewed server-side bridge can introduce those
   * families without the browser rejecting its own signed contract first.
   */
  period: 'daily' | 'weekly' | 'monthly' | MarketDataQueryFrequency
  family_id?: string
}

export interface MarketDataQueryBundleParams {
  asset_type: MarketAssetType
  family_id?: string
}

export interface MarketInstrumentOptionsResponse {
  asset_type: MarketAssetType
  /** Absent on the legacy response; OpenData mode is an explicit server assertion. */
  catalog_mode?: 'opendata' | 'legacy'
  complete?: boolean
  has_more?: boolean
  data_availability?: string
  items: MarketInstrumentOption[]
  total: number
  provenance?: {
    source: string
    dataset_id: string
    source_id: string
    publication_id: string
    snapshot_id: string
    sequence: number
    schema_version: string
    semantic_version: string
    contract_sha256: string
    content_sha256: string
    selection_sha256: string
    as_of: string
    expires_at: string
    registry_version: string
    profile_version: string
    coverage: string
  }
}

export interface MarketSnapshot {
  symbol?: string
  name?: string
  price?: number | null
  change?: number | null
  change_pct?: number | null
  open?: number | null
  high?: number | null
  low?: number | null
  previous_close?: number | null
  settle?: number | null
  previous_settle?: number | null
  bid?: number | null
  ask?: number | null
  volume?: number | null
  turnover?: number | null
  turnover_rate?: number | null
  open_interest?: number | null
  strike?: number | null
  days_to_expiry?: number | null
  market_cap?: number | null
  float_market_cap?: number | null
  pe?: number | null
  pb?: number | null
  update_time?: string | null
  data_source_table?: string | null
  history_currency?: string | null
  [key: string]: unknown
}

export interface MarketHistoryRow {
  date: string
  name?: string | null
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  price?: number | null
  volume?: number | null
  turnover?: number | null
  change?: number | null
  change_pct?: number | null
  turnover_rate?: number | null
  open_interest?: number | null
  settle?: number | null
  strike?: number | null
  days_to_expiry?: number | null
  [key: string]: unknown
}

export interface MarketInstrumentIndicators {
  latest_close?: number | null
  return_pct?: number | null
  highest_close?: number | null
  lowest_close?: number | null
  avg_volume?: number | null
  observation_count?: number
}

export interface MarketInstrumentLookupResponse {
  asset_type: MarketAssetType
  symbol: string
  name: string
  market?: string | null
  provider?: string | null
  /**
   * Present only after the backend has proven an exact v2 identity and
   * dataset binding. Its absence is a normal rollout state and callers must
   * continue through the legacy local lookup path.
   */
  query_contract?: MarketDataQueryContract | null
  /**
   * Legacy lookup compatibility proof for an attached v2 contract.  A client
   * may use that contract only when these server-issued values exactly match
   * both the current symbol and the contract identity.
   */
  query_contract_symbol?: string | null
  query_contract_canonical_id?: string | null
  snapshot: MarketSnapshot
  history: {
    period: string
    rows: MarketHistoryRow[]
    total: number
  }
  indicators: MarketInstrumentIndicators
  warnings: string[]
}

export interface MarketDataCoverageQuery {
  asset_type?: MarketAssetType | string | null
  symbol?: string | null
  timeframe?: string | null
  provider?: string | null
  refresh_if_empty?: boolean
  limit?: number
}

export interface MarketDataCoverageRefreshQuery {
  asset_type?: MarketAssetType | string | null
  symbol?: string | null
  timeframe?: string | null
  limit?: number
}

function nonEmptyText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

const MARKET_ASSET_TYPES: readonly MarketAssetType[] = [
  'stock',
  'futures',
  'bond',
  'fund',
  'option',
  'fx',
  'crypto',
]

function isMarketAssetType(value: unknown): value is MarketAssetType {
  return typeof value === 'string' && MARKET_ASSET_TYPES.includes(value as MarketAssetType)
}

const MARKET_DATA_QUERY_DATA_KINDS: readonly MarketDataQueryDataKind[] = [
  'bars',
  'quote_snapshot',
  'valuation_snapshot',
  'option_chain',
  'position_report',
  'reference_series',
  'inventory_report',
  'option_risk_surface',
]
const MARKET_DATA_QUERY_FREQUENCIES: readonly MarketDataQueryFrequency[] = [
  '5min',
  '30min',
  '1h',
  '1d',
  '1w',
  '1mo',
  'snapshot',
]
const MARKET_DATA_QUERY_BUNDLE_DATA_KINDS: readonly MarketDataQueryBundleDataKind[] = (
  MARKET_DATA_QUERY_DATA_KINDS
)
const MARKET_DATA_QUERY_BUNDLE_FREQUENCIES: readonly MarketDataQueryBundleFrequency[] = (
  MARKET_DATA_QUERY_FREQUENCIES
)
const MARKET_DATA_QUERY_BUNDLE_FREQUENCY_SEMANTICS: readonly MarketDataQueryBundleFrequencySemantics[] = [
  'calendar_grid',
  'snapshot',
  'reporting_period',
]
const MARKET_DATA_QUERY_BUNDLE_COVERAGE_MODELS: readonly MarketDataQueryBundleCoverageModel[] = [
  'calendar_grid',
  'snapshot_freshness',
  'slice_completeness',
  'report_completeness',
]

function hasDistinctTextArray(value: unknown, minLength = 0): value is string[] {
  return Array.isArray(value)
    && value.length >= minLength
    && value.every(nonEmptyText)
    && new Set(value).size === value.length
}

function hasRequiredMarketDataFamilyBinding(value: Record<string, unknown>): boolean {
  return nonEmptyText(value.family_id)
    && value.family_contract_version === MARKET_DATA_FAMILY_CONTRACT_VERSION
}

function hasCoherentMarketDataQueryBundleFamilyShape(family: Record<string, unknown>): boolean {
  const dataKind = family.data_kind as MarketDataQueryBundleDataKind
  const frequencySemantics = family.frequency_semantics as MarketDataQueryBundleFrequencySemantics
  const frequencies = family.frequencies as MarketDataQueryBundleFrequency[]
  const coverageModel = family.coverage_model as MarketDataQueryBundleCoverageModel
  const dimensionFields = family.dimension_fields as string[]
  const hasOnlySnapshotFrequency = frequencies.length === 1 && frequencies[0] === 'snapshot'
  const hasNoSnapshotFrequency = !frequencies.includes('snapshot')

  // A bundle is an authenticated control-plane document.  Validate each
  // product shape as a matrix rather than accepting a broadly plausible
  // cadence.  In particular, a chain/report must not become executable when
  // a malformed response labels it as a single-record calendar series.
  if (dataKind === 'bars' || dataKind === 'reference_series') {
    return frequencySemantics === 'calendar_grid'
      && coverageModel === 'calendar_grid'
      && hasNoSnapshotFrequency
      && dimensionFields.length === 0
  }
  if (dataKind === 'quote_snapshot' || dataKind === 'valuation_snapshot') {
    return frequencySemantics === 'snapshot'
      && coverageModel === 'snapshot_freshness'
      && hasOnlySnapshotFrequency
      && dimensionFields.length === 0
  }
  if (dataKind === 'option_chain' || dataKind === 'option_risk_surface') {
    return frequencySemantics === 'snapshot'
      && coverageModel === 'slice_completeness'
      && hasOnlySnapshotFrequency
      && dimensionFields.length > 0
  }
  if (dataKind === 'position_report' || dataKind === 'inventory_report') {
    return frequencySemantics === 'reporting_period'
      && coverageModel === 'report_completeness'
      && hasNoSnapshotFrequency
      && dimensionFields.length > 0
  }
  return false
}

/**
 * Return whether a family can be selected by the current market-data page.
 *
 * The public wire DTO intentionally describes several non-executable
 * multi-record product classes so the page can render their explicit NO-GO
 * state.  It must not, however, treat a malformed or prematurely promoted
 * ``ready`` status as permission to issue a chain/surface/report query.  The
 * page currently has reviewed renderers only for single-record bars,
 * reference series, and quote snapshots.  Keep this allowlist beside the
 * wire-shape validator so an unsupported data kind cannot become selectable
 * merely by carrying a source-policy ID.
 */
export function isMarketDataQueryBundleFamilyExecutable(
  value: unknown,
): value is MarketDataQueryBundleFamily {
  if (!value || typeof value !== 'object') return false
  const family = value as Record<string, unknown>
  if (
    family.status !== 'ready'
    || !nonEmptyText(family.source_policy_id)
    || family.reason_code !== null
    || !hasCoherentMarketDataQueryBundleFamilyShape(family)
  ) {
    return false
  }
  return (
    family.data_kind === 'bars'
    || family.data_kind === 'reference_series'
    || family.data_kind === 'quote_snapshot'
  )
}

function hasCoherentMarketDataQueryContractShape(request: Record<string, unknown>): boolean {
  const dataKind = request.data_kind as MarketDataQueryDataKind
  const frequency = request.frequency as MarketDataQueryFrequency
  if (dataKind === 'bars' || dataKind === 'reference_series') return frequency !== 'snapshot'
  if (dataKind === 'quote_snapshot' || dataKind === 'valuation_snapshot') return frequency === 'snapshot'
  if (dataKind === 'option_chain' || dataKind === 'option_risk_surface') return frequency === 'snapshot'
  if (dataKind === 'position_report' || dataKind === 'inventory_report') return frequency !== 'snapshot'
  return false
}

/**
 * Return whether a static family-control bundle is safe to use as an
 * authoritative page capability declaration.
 *
 * A malformed 2xx payload must not activate the compatibility route: callers
 * treat it as a v2 failure.  Ready entries require their descriptive
 * read-only contract, while unavailable entries may only expose a stable
 * reason code.
 */
export function hasMarketDataQueryBundle(value: unknown): value is MarketDataQueryBundle {
  if (!value || typeof value !== 'object') return false
  const bundle = value as Record<string, unknown>
  if (
    bundle.version !== 'market-data-family-bundle-v1'
    || !isMarketAssetType(bundle.requested_asset_type)
    || !Array.isArray(bundle.families)
  ) {
    return false
  }

  const requestedAssetType = bundle.requested_asset_type
  const familyIds = new Set<string>()
  return bundle.families.length > 0 && bundle.families.every((entry) => {
    if (!entry || typeof entry !== 'object') return false
    const family = entry as Record<string, unknown>
    if (!nonEmptyText(family.family_id) || familyIds.has(family.family_id)) return false
    familyIds.add(family.family_id)
    if (family.family_contract_version !== MARKET_DATA_FAMILY_CONTRACT_VERSION) return false
    if (!isMarketAssetType(family.asset_type) || !family.family_id.startsWith(`${family.asset_type}.`)) {
      return false
    }
    if (
      family.status !== 'ready'
      && family.status !== 'unconfigured'
      && family.status !== 'not_applicable'
    ) {
      return false
    }
    // The optional server-side family filter can explicitly return a family
    // from another asset as not_applicable. The page requests the full bundle
    // and performs the stricter same-asset check before consuming it.
    if (family.asset_type !== requestedAssetType && family.status !== 'not_applicable') return false
    if (
      !nonEmptyText(family.dataset_code)
      || !MARKET_DATA_QUERY_BUNDLE_DATA_KINDS.includes(family.data_kind as MarketDataQueryBundleDataKind)
      || !MARKET_DATA_QUERY_BUNDLE_FREQUENCY_SEMANTICS.includes(
        family.frequency_semantics as MarketDataQueryBundleFrequencySemantics,
      )
      || !hasDistinctTextArray(family.frequencies, 1)
      || !family.frequencies.every((frequency) => (
        MARKET_DATA_QUERY_BUNDLE_FREQUENCIES.includes(frequency as MarketDataQueryBundleFrequency)
      ))
      || !nonEmptyText(family.field_profile_id)
      || !hasDistinctTextArray(family.required_fields, 1)
      || !hasDistinctTextArray(family.optional_fields)
      || !hasDistinctTextArray(family.dimension_fields)
      || !MARKET_DATA_QUERY_BUNDLE_COVERAGE_MODELS.includes(
        family.coverage_model as MarketDataQueryBundleCoverageModel,
      )
    ) {
      return false
    }
    const fieldNames = [
      ...family.required_fields,
      ...family.optional_fields,
      ...family.dimension_fields,
    ]
    if (
      new Set(fieldNames).size !== fieldNames.length
      || !hasCoherentMarketDataQueryBundleFamilyShape(family)
    ) {
      return false
    }
    if (family.status === 'ready') return isMarketDataQueryBundleFamilyExecutable(family)
    return family.source_policy_id === null && nonEmptyText(family.reason_code)
  })
}

/** Return whether a server payload is a complete, safe v2 query contract. */
export function hasMarketDataQueryContract(value: unknown): value is MarketDataQueryContract {
  if (!value || typeof value !== 'object') return false
  const contract = value as Record<string, unknown>
  if (contract.version !== 'market-data-v2' || !contract.request || typeof contract.request !== 'object') {
    return false
  }
  const request = contract.request as Record<string, unknown>
  const identity = request.identity
  const canonicalId = identity && typeof identity === 'object'
    ? (identity as Record<string, unknown>).canonical_id
    : undefined
  return Boolean(
    nonEmptyText(canonicalId)
      && nonEmptyText(request.dataset_code)
      && MARKET_DATA_QUERY_DATA_KINDS.includes(request.data_kind as MarketDataQueryDataKind)
      && MARKET_DATA_QUERY_FREQUENCIES.includes(request.frequency as MarketDataQueryFrequency)
      && hasDistinctTextArray(request.required_fields, 1)
      && nonEmptyText(request.source_policy_id)
      && hasRequiredMarketDataFamilyBinding(request)
      && hasCoherentMarketDataQueryContractShape(request)
      && request.mode === 'local_first',
  )
}

/**
 * Materialize one v2 request from a server-issued contract.
 *
 * The caller can only supply transport/window settings and the explicitly
 * supported rollout mode. Identity, dataset, fields, and semantic axes are
 * copied from the server contract rather than inferred from UI text.
 */
export function createMarketDataQueryFromContract(
  contract: MarketDataQueryContract,
  options: {
    start: string
    end: string
    mode?: MarketDataQueryMode
    consistency?: MarketDataQueryConsistency
    purpose?: MarketDataQueryPurpose
    knowledge_cutoff?: string
    page_size?: number
  },
): MarketDataQueryRequest {
  if (!hasMarketDataQueryContract(contract)) {
    throw new Error('MARKET_DATA_QUERY_CONTRACT_INVALID')
  }
  const request = contract.request
  const requestBase = {
    identity: { canonical_id: request.identity.canonical_id },
    dataset_code: request.dataset_code,
    data_kind: request.data_kind,
    frequency: request.frequency,
    required_fields: [...request.required_fields],
    // Preserve an explicit `null` from the server contract. For a reviewed
    // undeclared axis (such as an FX pair's currency/unit), `undefined` would
    // disappear during JSON serialization and turn an exact signed request
    // into an omitted/generic semantic axis at the API boundary.
    adjustment: request.adjustment,
    price_basis: request.price_basis,
    currency: request.currency,
    unit: request.unit,
    source_policy_id: request.source_policy_id,
    mode: options.mode || request.mode,
    start: options.start,
    end: options.end,
    consistency: options.consistency,
    purpose: options.purpose,
    knowledge_cutoff: options.knowledge_cutoff,
    page_size: options.page_size,
  }
  return {
    ...requestBase,
    family_id: request.family_id,
    family_contract_version: request.family_contract_version,
  }
}

function marketDataQueryErrorCode(error: unknown): string | undefined {
  if (!error || typeof error !== 'object') return undefined
  const response = (error as { response?: { data?: unknown } }).response
  const data = response?.data
  if (!data || typeof data !== 'object') return undefined
  const record = data as Record<string, unknown>
  const detail = record.detail as Record<string, unknown> | undefined
  const details = record.details as Record<string, unknown> | undefined
  for (const candidate of [record.code, detail?.code, details?.code]) {
    if (typeof candidate === 'string' && candidate.trim()) return candidate
  }
  return undefined
}

/**
 * Identify only an unavailable v2 control-plane endpoint during progressive
 * rollout. Callers may use this before they have a valid family bundle or
 * symbol-specific contract. Once either one has been issued, a v2 execution
 * failure is authoritative and must remain visible: falling through to the
 * legacy endpoint could bypass the receipt-backed persistence protocol.
 */
export function isMarketDataQueryV2FallbackError(error: unknown): boolean {
  const response = error && typeof error === 'object'
    ? (error as { response?: { status?: unknown } }).response
    : undefined
  const status = typeof response?.status === 'number' ? response.status : undefined
  const code = marketDataQueryErrorCode(error)
  if (code) {
    return code === 'MARKET_DATA_QUERY_V2_DISABLED'
      || code === 'MARKET_DATA_QUERY_CONTRACT_UNAVAILABLE'
      || code === 'MARKET_DATA_QUERY_BUNDLE_UNAVAILABLE'
  }
  // Generic route absence is a deployment state.  Do not treat a generic
  // 5xx, transport failure, or a typed business rejection as compatibility.
  return status === 404 || status === 405 || status === 501
}

export const marketDataApi = {
  getCapabilities() {
    return request.get<unknown>('/data/market-data/capabilities', {
      suppressErrorMessage: true,
      skipRetry: true,
      validateStatus: (status) => status >= 200 && status < 300,
    })
  },
  async getOpenDataDirectKline(
    params: OpenDataDirectKlineRequest,
    options?: OpenDataDirectKlineOptions,
  ): Promise<OpenDataDirectKlineResponse> {
    const response = await request.get<unknown>('/data/kline', {
      params,
      signal: options?.signal,
      skipRetry: true,
      suppressErrorToast: true,
    })
    const parsed = parseOpenDataDirectKlineResponse(response, params)
    if (!parsed) throw new Error('OPENDATA_DIRECT_RESPONSE_INVALID')
    return parsed
  },
  async getOpenDataStockDailyFreshness(
    options?: OpenDataStockDailyFreshnessOptions,
  ): Promise<OpenDataStockDailyFreshnessResponse> {
    const response = await request.get<unknown>(
      '/data/trust/opendata/stock-daily/freshness',
      {
        signal: options?.signal,
        skipRetry: true,
        suppressErrorToast: true,
      },
    )
    const parsed = parseOpenDataStockDailyFreshnessResponse(response)
    if (!parsed) throw new Error('OPENDATA_STOCK_DAILY_FRESHNESS_RESPONSE_INVALID')
    return parsed
  },
  listInstrumentOptions(params: MarketInstrumentOptionsParams) {
    const requestOptions = params.asset_type === 'stock'
      ? { params, skipRetry: true, suppressErrorToast: true }
      : { params }
    return request.get<MarketInstrumentOptionsResponse>(
      '/data/market-instruments/options',
      requestOptions,
    )
  },
  lookupInstrument(params: MarketInstrumentLookupParams) {
    return request.get<MarketInstrumentLookupResponse>('/data/market-instruments/lookup', {
      params,
    })
  },
  getQueryContract(params: MarketDataQueryContractParams) {
    // The caller classifies an expected unavailable contract from the rejected
    // response.  All other non-2xx responses remain failures, so a transient
    // server problem cannot silently activate the legacy online path.
    return request.get<unknown>('/data/market-instruments/query-contract', {
      params,
      suppressErrorMessage: true,
      skipRetry: true,
      validateStatus: (status) => status >= 200 && status < 300,
    })
  },
  getQueryBundle(params: MarketDataQueryBundleParams) {
    // This endpoint is a static, read-only control-plane declaration. The
    // caller validates the response before letting it suppress legacy data.
    return request.get<unknown>('/data/market-instruments/query-bundle', {
      params,
      suppressErrorMessage: true,
      skipRetry: true,
      validateStatus: (status) => status >= 200 && status < 300,
    })
  },
  queryLocalFirst(data: MarketDataQueryRequest, options?: MarketDataQueryOptions) {
    if (options?.signal || options?.suppressErrorMessage) {
      return request.post<MarketDataQueryResponse, MarketDataQueryRequest>('/data/queries', data, options)
    }
    return request.post<MarketDataQueryResponse, MarketDataQueryRequest>('/data/queries', data)
  },
  getAssetSpec(symbol: string, params?: { asset_type?: MarketAssetType | string | null }) {
    return request.get<AssetSpecResponse>(`/data/trust/asset-specs/${encodeURIComponent(symbol)}`, {
      params,
    })
  },
  getExecutionModel(symbol: string, params?: { asset_type?: MarketAssetType | string | null }) {
    return request.get<ExecutionModelResponse>(
      `/data/trust/asset-specs/${encodeURIComponent(symbol)}/execution-model`,
      { params },
    )
  },
  listCoverage(params: MarketDataCoverageQuery = {}) {
    return request.get<MarketDataCoverageMatrixResponse>('/data/trust/coverage', {
      params,
    })
  },
  refreshLocalCoverage(params: MarketDataCoverageRefreshQuery = {}) {
    return request.post<MarketDataCoverageMatrixResponse>('/data/trust/coverage/refresh-local', undefined, {
      params,
    })
  },
  refreshWarehouseCoverage(params: MarketDataCoverageRefreshQuery = {}) {
    return request.post<MarketDataCoverageMatrixResponse>(
      '/data/trust/coverage/refresh-warehouse',
      undefined,
      { params },
    )
  },
  runPrecheck(data: DataPrecheckRequest, options?: { signal?: AbortSignal }) {
    if (options?.signal) {
      return request.post<DataPrecheckResponse, DataPrecheckRequest>('/data/trust/precheck', data, options)
    }
    return request.post<DataPrecheckResponse, DataPrecheckRequest>('/data/trust/precheck', data)
  },
}
