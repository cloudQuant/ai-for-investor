import type { Component } from 'vue'
import type * as echarts from 'echarts'
import type {
  MarketAssetType,
  MarketDataCapabilitiesResponse,
  MarketDataFamilyObservationShape,
  MarketDataQueryBundleFamily,
  MarketDataQueryDataKind,
  MarketDataQueryMode,
  MarketDataQueryObservation,
  MarketDataQueryResponse,
  MarketHistoryRow,
  MarketInstrumentLookupResponse,
  OpenDataCoverageState,
  OpenDataDirectKlineRecord,
  OpenDataDirectKlineRequest,
} from '@/api/marketData'

export type DataPageDisplayMode = 'legacy' | 'opendata_direct'

export type OpenDataDirectKlineDisplayStatus = 'idle' | 'loading' | 'ready' | 'unavailable'

export type OpenDataDirectKlineDisplayReason =
  | 'CAPABILITIES_UNAVAILABLE'
  | 'CAPABILITY_CENSUS_INVALID'
  | 'QUERY_V2_DISABLED'
  | 'ONLINE_FETCH_DISABLED'
  | 'OPENDATA_ROUTE_INEFFECTIVE'
  | 'UNSUPPORTED_ASSET'
  | 'UNSUPPORTED_PERIOD'
  | 'INVALID_DATE_RANGE'
  | 'DIRECT_REQUEST_FAILED'
  | 'DIRECT_RESPONSE_INVALID'

export interface OpenDataDirectKlineDisplayState {
  status: OpenDataDirectKlineDisplayStatus
  request: OpenDataDirectKlineRequest | null
  symbolLabel: string | null
  rangeLabel: string | null
  rows: readonly OpenDataDirectKlineRecord[]
  returnedBarCount: number | null
  retrievedAt: string | null
  coverageStatus: OpenDataCoverageState | null
  sourceAvailableAt: 'unknown' | null
  durableReceipt: 'not_created' | null
  reason: OpenDataDirectKlineDisplayReason | null
}

export type SavedMarketAssetSelection = {
  symbol: string
  market?: string
}

export type MarketAssetSelections = Partial<Record<MarketAssetType, SavedMarketAssetSelection>>

export type AssetTab = {
  key: MarketAssetType
  labelKey: string
  placeholderKey: string
  defaultSymbol: string
  icon: Component
}

export type FieldFormat = 'number' | 'percent' | 'text' | 'pair' | 'bidAsk' | 'valuation'

export type DetailFieldSpec = {
  labelKey: string
  fields: string[]
  format?: FieldFormat
  tone?: boolean
}

export type HistoryColumnSpec = {
  key: string
  labelKey: string
  width?: number
  minWidth?: number
  align?: 'left' | 'center' | 'right'
  fixed?: 'left' | 'right'
  format?: 'number' | 'percent' | 'text'
  tone?: boolean
}

export type AssetDisplayConfig = {
  titleKey: string
  descKey: string
  detailTitleKey: string
  detailNoteKey: string
  detailFields: DetailFieldSpec[]
  historyColumns: HistoryColumnSpec[]
}

export type DetailRow = {
  label: string
  value: string
  tone: string
}

export type KpiCard = {
  label: string
  value: string
  tone: string
}

export type SnapshotMetric = {
  key: string
  label: string
  value: string
  tone?: string
}

export type HistoryTableColumn = Omit<HistoryColumnSpec, 'labelKey'> & {
  label: string
}

export type ReferenceSeriesResult = {
  familyId: string
  requiredFields: string[]
  rows: MarketHistoryRow[]
}

export type GenericObservationResult = {
  familyId: string
  dataKind: MarketDataQueryDataKind
  requiredFields: string[]
  dimensionFields: string[]
  observations: MarketDataQueryObservation[]
}

export type GenericObservationColumn = {
  key: string
  label: string
  source: 'metadata' | 'field'
}

export type V2LookupResult = {
  lookup: MarketInstrumentLookupResponse
  response: MarketDataQueryResponse
  referenceSeries: ReferenceSeriesResult | null
  genericObservations: GenericObservationResult | null
}

export type MarketLookupRequestSnapshot = {
  assetType: MarketAssetType
  symbol: string
  market: string
  period: string
  dateRange: readonly [string | undefined, string | undefined]
  familyId: string
}

export type MarketLookupIntent = MarketDataQueryMode | boolean

export type DataFamilyOption = {
  value: string
  label: string
}

export type ChartMode = 'price' | 'return' | 'liquidity' | 'structure'

export type ChartModeOption = {
  value: ChartMode
  label: string
}

export type RangeStat = {
  label: string
  value: string
  tone: string
}

export type CoverageRow = {
  label: string
  value: string
  coverage: number
}

export type MarketDataPlatformStatus = {
  path: (
    | 'legacy'
    | 'local_only'
    | 'local_first'
    | 'local_coverage_incomplete'
    | 'provider_persisted'
    | 'provider_persisted_incomplete'
    | 'legacy_fallback'
    | 'family_selection_pending'
    | 'bundle_unconfigured'
    | 'bundle_period_unsupported'
    | 'error'
  )
  provider: string | null
  coverageStatus: string | null
  coverageRatio: number | null
  fetchedProviderCount: number
  fallbackReason: string | null
  queryId: string | null
  canonicalId: string | null
  datasetCode: string | null
  sourcePolicyId: string | null
  instrumentMetadataVersion: string | null
  familyId: string | null
  periodConstraint: {
    familyId: string
    requestedFrequency: string
    declaredFrequencies: string[]
    resetPeriod: string | null
  } | null
}

export type DataFamilySpec = {
  familyId: string
  labelKey: string
  descKey: string
  fields: string[]
  historyFields?: string[]
  tableKeywords: string[]
}

export type DataFamilyReadState = (
  | 'facts_loaded'
  | 'bars_query_available'
  | 'reference_series_query_available'
  | 'generic_query_available'
  | 'control_plane_only'
  | 'unconfigured'
  | 'not_applicable'
)

export type DataFamilyView = {
  familyId: string
  label: string
  description: string
  statusLabel: string
  tagType: 'success' | 'warning' | 'info'
  contract: {
    dataKind: MarketDataQueryBundleFamily['data_kind']
    frequencySemantics: MarketDataQueryBundleFamily['frequency_semantics']
    coverageModel: MarketDataQueryBundleFamily['coverage_model']
    observationShape: MarketDataFamilyObservationShape
  } | null
  readState: DataFamilyReadState | null
  readStatusLabel: string | null
  fields: Array<{
    name: string
    label: string
    present: boolean
  }>
}

export type MarketDataPlatformProvenance = {
  label: string
  value: string
}

export type MarketChartOptionDraft = Omit<echarts.EChartsOption, 'legend'> & {
  legend: string[]
}

export const MARKET_ASSET_SELECTIONS_STORAGE_KEY = 'ai_for_investor:market:asset_selections'
export const V2_MARKET_DATA_PAGE_SIZE = 2000
export const GENERIC_OBSERVATION_MAX_WINDOW_DAYS = 7

export function emptyOpenDataDirectKlineDisplay(): OpenDataDirectKlineDisplayState {
  return {
    status: 'idle',
    request: null,
    symbolLabel: null,
    rangeLabel: null,
    rows: [],
    returnedBarCount: null,
    retrievedAt: null,
    coverageStatus: null,
    sourceAvailableAt: null,
    durableReceipt: null,
    reason: null,
  }
}

export function isValidDirectBusinessDateRange(start: string, end: string): boolean {
  const parseDate = (value: string): number | null => {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
    const timestamp = Date.parse(`${value}T00:00:00.000Z`)
    if (!Number.isFinite(timestamp)) return null
    return new Date(timestamp).toISOString().slice(0, 10) === value ? timestamp : null
  }

  const startTimestamp = parseDate(start)
  const endTimestamp = parseDate(end)
  if (startTimestamp === null || endTimestamp === null || endTimestamp < startTimestamp) return false
  const inclusiveCalendarDays = Math.floor((endTimestamp - startTimestamp) / 86_400_000) + 1
  return inclusiveCalendarDays <= 366
}

/** The authenticated server capability is the rollout authority for v2 reads. */
export function isMarketDataQueryV2FeatureEnabled(
  capabilities: MarketDataCapabilitiesResponse | null,
): boolean {
  return capabilities?.query_v2_enabled === true
}

/** A family bundle is part of the authenticated server control plane. */
export function isMarketDataQueryBundleFeatureEnabled(
  capabilities: MarketDataCapabilitiesResponse | null,
): boolean {
  return isMarketDataQueryV2FeatureEnabled(capabilities)
}
