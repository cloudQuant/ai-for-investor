import type {
  createMarketDataQueryFromContract,
  MarketAssetType,
  MarketDataQueryBundle,
  MarketDataQueryBundleFamily,
  MarketDataQueryContract,
  MarketDataQueryFrequency,
  MarketDataQueryObservation,
  MarketDataQueryResponse,
  MarketDataRouteSelection,
  MarketHistoryRow,
  MarketInstrumentLookupResponse,
  MarketInstrumentOption,
} from '@/api/marketData'
import { CANDLE_DOWN_COLOR, CANDLE_UP_COLOR } from '@/constants/chartColors'
import {
  GENERIC_OBSERVATION_MAX_WINDOW_DAYS,
  type GenericObservationColumn,
  type GenericObservationResult,
  type HistoryTableColumn,
  type MarketDataPlatformStatus,
  type OpenDataDirectKlineDisplayReason,
} from './marketDataTypes'

export function hasValue(value: unknown) {
  return value !== null && value !== undefined && value !== ''
}

export function capitalize(value: string) {
  return value.charAt(0).toUpperCase() + value.slice(1)
}

export function isFiniteNumber(value: number | null): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

export function numericValue<T extends number | null>(value: unknown, fallback: T): number | T {
  if (!hasValue(value)) return fallback
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

export function numericSeries(rows: MarketHistoryRow[], field: string) {
  return rows.map((row) => numericValue(row[field], null)).filter(isFiniteNumber)
}

export function sumNumbers(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0)
}

export function averageNumbers(values: number[]) {
  if (!values.length) return null
  return sumNumbers(values) / values.length
}

export function periodReturnPct(values: number[]) {
  if (values.length < 2 || !values[0]) return null
  return ((values[values.length - 1] / values[0]) - 1) * 100
}

export function closeVolatilityPct(values: number[]) {
  if (values.length < 3) return null
  const returns = values.slice(1)
    .map((value, index) => values[index] ? ((value / values[index]) - 1) * 100 : null)
    .filter(isFiniteNumber)
  if (!returns.length) return null
  const mean = averageNumbers(returns) || 0
  const variance = returns.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / returns.length
  return Math.sqrt(variance)
}

export function cumulativeReturns(values: number[]) {
  if (!values.length || !values[0]) return []
  const first = values[0]
  return values.map((value) => Number((((value / first) - 1) * 100).toFixed(2)))
}

export function drawdownSeries(values: number[]) {
  let peak = values[0] || 0
  return values.map((value) => {
    peak = Math.max(peak, value)
    if (!peak) return 0
    return Number((((value / peak) - 1) * 100).toFixed(2))
  })
}

export function formatNumber(value: unknown) {
  if (!hasValue(value)) return '-'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return new Intl.NumberFormat(undefined, {
    maximumFractionDigits: Math.abs(numeric) >= 1000 ? 0 : 4,
  }).format(numeric)
}

export function formatPercent(value: unknown) {
  if (!hasValue(value)) return '-'
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${numeric >= 0 ? '+' : ''}${numeric.toFixed(2)}%`
}

export function formatPair(firstValue: unknown, secondValue: unknown) {
  if (!hasValue(firstValue) && !hasValue(secondValue)) return '-'
  return `${formatNumber(firstValue)} / ${formatNumber(secondValue)}`
}

export function formatText(value: unknown) {
  if (!hasValue(value)) return '-'
  return String(value)
}

export function formatReferenceSeriesField(field: string, value: unknown): string {
  return field === 'daily_growth_rate' ? formatPercent(value) : formatNumber(value)
}

export function toneClass(value: unknown) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric === 0) return ''
  return numeric > 0 ? 'is-positive' : 'is-negative'
}

export function referenceSeriesFieldTone(field: string, value: unknown): string {
  return field === 'daily_growth_rate' ? toneClass(value) : ''
}

export function formatHistoryCell(row: MarketHistoryRow, column: HistoryTableColumn) {
  const value = row[column.key]
  if (column.format === 'percent') {
    return formatPercent(value)
  }
  if ((column.format as string) === 'text') {
    return formatText(value)
  }
  return formatNumber(value)
}

export function formatCoverageRatio(value: unknown) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${(numeric * 100).toFixed(2)}%`
}

export function coverageStatusTagType(status: string) {
  if (status === 'pass') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'warning') return 'warning'
  return 'info'
}

export function publicMarketDataProvenanceValue(value: unknown): string | null {
  if (typeof value !== 'string') return null
  const normalized = value.trim()
  if (!normalized || normalized.length > 512) return null
  const containsControlCharacter = Array.from(normalized).some((character) => {
    const codePoint = character.codePointAt(0) || 0
    return codePoint <= 31 || codePoint === 127
  })
  return containsControlCharacter ? null : normalized
}

export function formatGenericObservationValue(value: unknown): string {
  if (!hasValue(value)) return '-'
  if (typeof value === 'number') return Number.isFinite(value) ? formatNumber(value) : '-'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string') return publicMarketDataProvenanceValue(value) || '-'
  try {
    const serialized = JSON.stringify(value)
    return typeof serialized === 'string' ? publicMarketDataProvenanceValue(serialized) || '-' : '-'
  } catch {
    return '-'
  }
}

export function formatGenericObservationCell(
  observation: MarketDataQueryObservation,
  column: GenericObservationColumn,
): string {
  if (column.source === 'field') {
    return formatGenericObservationValue(observation.fields[column.key])
  }
  const metadata: Record<string, unknown> = {
    event_at: observation.event_at,
    quality: observation.quality,
    source_snapshot_id: observation.source_snapshot_id,
    revision_id: observation.revision_id,
    available_at: observation.available_at,
    committed_at: observation.committed_at,
    revision_number: observation.revision_number,
  }
  return formatGenericObservationValue(metadata[column.key])
}

export function ohlcTuple(row: MarketHistoryRow) {
  const open = numericValue(row.open, null)
  const close = numericValue(row.close, null)
  const low = numericValue(row.low, null)
  const high = numericValue(row.high, null)
  if (
    !isFiniteNumber(open)
    || !isFiniteNumber(close)
    || !isFiniteNumber(low)
    || !isFiniteNumber(high)
  ) {
    throw new Error('MARKET_DATA_OHLC_INVALID')
  }
  return [open, close, low, high]
}

export function candleColor(row: MarketHistoryRow) {
  const open = numericValue(row.open, null)
  const close = numericValue(row.close, null)
  if (!isFiniteNumber(open) || !isFiniteNumber(close)) {
    throw new Error('MARKET_DATA_OHLC_INVALID')
  }
  return close >= open ? CANDLE_UP_COLOR : CANDLE_DOWN_COLOR
}

export function historyRowTimestamp(row: MarketHistoryRow): number {
  const timestamp = Date.parse(String(row.date ?? ''))
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY
}

export function toDateInput(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export function parseDateInputAsUtc(value: string | undefined): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null
  const parsed = new Date(`${value}T00:00:00.000Z`)
  if (Number.isNaN(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== value) return null
  return parsed
}

export function utcDateInput(value: Date): string {
  return value.toISOString().slice(0, 10)
}

export function boundedGenericObservationDateRange(
  requestedDateRange: readonly [string | undefined, string | undefined],
): [string, string] {
  const end = parseDateInputAsUtc(requestedDateRange[1]) || new Date()
  end.setUTCHours(0, 0, 0, 0)
  let start = parseDateInputAsUtc(requestedDateRange[0])
  if (!start || start > end) start = new Date(end)

  const earliestAllowedStart = new Date(end)
  earliestAllowedStart.setUTCDate(
    earliestAllowedStart.getUTCDate() - (GENERIC_OBSERVATION_MAX_WINDOW_DAYS - 1),
  )
  if (start < earliestAllowedStart) start = earliestAllowedStart

  return [utcDateInput(start), utcDateInput(end)]
}

export function v2FrequencyForLegacyPeriod(period: string): MarketDataQueryFrequency {
  if (period === 'weekly') return '1w'
  if (period === 'monthly') return '1mo'
  if (['5min', '30min', '1h', '1d', '1w', '1mo', 'snapshot'].includes(period)) {
    return period as MarketDataQueryFrequency
  }
  return '1d'
}

export function legacyPeriodForV2Frequency(frequency: string): string | null {
  if (frequency === '1d') return 'daily'
  if (frequency === '1w') return 'weekly'
  if (frequency === '1mo') return 'monthly'
  if (frequency === '5min' || frequency === '30min' || frequency === '1h' || frequency === 'snapshot') {
    return frequency
  }
  return null
}

export function marketPagePeriodForV2Frequency(frequency: MarketDataQueryFrequency): string {
  return legacyPeriodForV2Frequency(frequency) || frequency
}

export function periodLabelKey(period: string): string {
  const keys: Record<string, string> = {
    daily: 'dataMgmt.periodDaily',
    weekly: 'dataMgmt.periodWeekly',
    monthly: 'dataMgmt.periodMonthly',
    '5min': 'dataMgmt.periodFiveMinutes',
    '30min': 'dataMgmt.periodThirtyMinutes',
    '1h': 'dataMgmt.periodHourly',
    '1d': 'dataMgmt.periodDaily',
    '1w': 'dataMgmt.periodWeekly',
    '1mo': 'dataMgmt.periodMonthly',
    snapshot: 'dataMgmt.periodSnapshot',
  }
  return keys[period] || period
}

export function resetToDeclaredPeriod(family: MarketDataQueryBundleFamily): string | null {
  for (const frequency of family.frequencies) {
    const period = legacyPeriodForV2Frequency(frequency)
    if (period) return period
  }
  return null
}

export function queryWindowFromDateRange(
  requestedDateRange: readonly [string | undefined, string | undefined],
): { start: string; end: string } | null {
  const [startDate, endDate] = requestedDateRange
  if (!startDate || !endDate) return null
  const start = new Date(`${startDate}T00:00:00.000Z`)
  const endInclusive = new Date(`${endDate}T00:00:00.000Z`)
  if (Number.isNaN(start.getTime()) || Number.isNaN(endInclusive.getTime()) || start > endInclusive) {
    return null
  }
  endInclusive.setUTCDate(endInclusive.getUTCDate() + 1)
  return { start: start.toISOString(), end: endInclusive.toISOString() }
}

export function isGenericObservationFamily(
  family: Pick<MarketDataQueryBundleFamily, 'data_kind'> | null | undefined,
): boolean {
  return family != null
    && family.data_kind !== 'bars'
    && family.data_kind !== 'reference_series'
}

export function sameDeclaredFields(left: readonly string[], right: readonly string[]): boolean {
  return left.length === right.length && left.every((field, index) => field === right[index])
}

export function isUsableReferenceSeriesValue(value: unknown): boolean {
  if (!hasValue(value)) return false
  if (typeof value === 'number') return Number.isFinite(value)
  return typeof value !== 'string' || value.trim() !== '--'
}

export function assertResponseRequiredFields(
  response: MarketDataQueryResponse,
  requiredFields: readonly string[],
): void {
  for (const observation of response.observations) {
    if (observation.quality !== 'pass') continue
    const valid = requiredFields.every((field) => (
      response.data_kind === 'bars'
        ? isFiniteNumber(numericValue(observation.fields[field], null))
        : isUsableReferenceSeriesValue(observation.fields[field])
    ))
    if (!valid) throw new Error('MARKET_DATA_QUERY_REQUIRED_FIELDS_INVALID')
  }
}

export function v2EventTimeLabel(value: string, frequency: string): string {
  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return value
  const iso = timestamp.toISOString()
  return ['1d', '1w', '1mo'].includes(frequency) ? iso.slice(0, 10) : iso
}

export function v2HistoryRows(
  response: MarketDataQueryResponse,
  requiredFields: readonly string[] = ['close'],
): MarketHistoryRow[] {
  return response.observations
    .filter((observation) => (
      observation.quality === 'pass'
      && requiredFields.every((field) => (
        isFiniteNumber(numericValue(observation.fields[field], null))
      ))
    ))
    .map((observation) => ({
      ...observation.fields,
      date: v2EventTimeLabel(observation.event_at, response.frequency),
    }))
    .sort((left, right) => historyRowTimestamp(left) - historyRowTimestamp(right))
}

export function referenceSeriesRowsFromV2Response(
  response: MarketDataQueryResponse,
  requiredFields: readonly string[],
): MarketHistoryRow[] {
  if (response.data_kind !== 'reference_series') {
    throw new Error('MARKET_DATA_REFERENCE_SERIES_KIND_INVALID')
  }
  return response.observations
    .filter((observation) => (
      observation.quality === 'pass'
      && requiredFields.every((field) => isUsableReferenceSeriesValue(observation.fields[field]))
    ))
    .map((observation) => ({
      date: v2EventTimeLabel(observation.event_at, response.frequency),
      ...Object.fromEntries(requiredFields.map((field) => [field, observation.fields[field]])),
    }))
    .sort((left, right) => historyRowTimestamp(left) - historyRowTimestamp(right))
}

export function genericObservationResultFromV2Response(
  response: MarketDataQueryResponse,
  family: MarketDataQueryBundleFamily,
): GenericObservationResult {
  if (response.data_kind === 'bars' || response.data_kind === 'reference_series') {
    throw new Error('MARKET_DATA_GENERIC_PRESENTATION_KIND_INVALID')
  }
  if (
    !isGenericObservationFamily(family)
    || family.status !== 'ready'
    || family.source_policy_id === null
    || family.reason_code !== null
    || response.family_id !== family.family_id
    || response.data_kind !== family.data_kind
    || response.dataset_code !== family.dataset_code
    || response.source_policy_id !== family.source_policy_id
  ) {
    throw new Error('MARKET_DATA_GENERIC_FAMILY_BINDING_INVALID')
  }
  const allowedFields = [...family.dimension_fields, ...family.required_fields]
  if (new Set(allowedFields).size !== allowedFields.length) {
    throw new Error('MARKET_DATA_GENERIC_FIELD_DECLARATION_INVALID')
  }
  const observations = response.observations.map((observation) => ({
    ...observation,
    fields: Object.fromEntries(
      allowedFields
        .filter((field) => Object.prototype.hasOwnProperty.call(observation.fields, field))
        .map((field) => [field, observation.fields[field]]),
    ),
  }))
  for (const observation of observations) {
    if (observation.quality !== 'pass') continue
    if (!allowedFields.every((field) => isUsableReferenceSeriesValue(observation.fields[field]))) {
      throw new Error('MARKET_DATA_GENERIC_DECLARED_FIELDS_INVALID')
    }
  }
  return {
    familyId: response.family_id,
    dataKind: response.data_kind,
    requiredFields: [...family.required_fields],
    dimensionFields: [...family.dimension_fields],
    observations,
  }
}

export function hasIncompleteCoverageStatus(path: MarketDataPlatformStatus['path']): boolean {
  return path === 'local_coverage_incomplete' || path === 'provider_persisted_incomplete'
}

export function assertMarketDataResponseEcho(
  response: MarketDataQueryResponse,
  request: ReturnType<typeof createMarketDataQueryFromContract>,
  expectedAssetType: MarketAssetType,
): void {
  if (
    response.family_id !== request.family_id
    || response.family_contract_version !== request.family_contract_version
    || response.canonical_id !== request.identity.canonical_id
    || response.dataset_code !== request.dataset_code
    || response.source_policy_id !== request.source_policy_id
    || response.asset_type !== expectedAssetType
    || response.data_kind !== request.data_kind
    || response.frequency !== request.frequency
  ) {
    throw new Error('MARKET_DATA_QUERY_RESPONSE_MISMATCH')
  }
}

export function routeSelectionFailureReason(
  selection: MarketDataRouteSelection,
): OpenDataDirectKlineDisplayReason {
  switch (selection.reason) {
    case 'CAPABILITIES_UNAVAILABLE':
    case 'CAPABILITY_CENSUS_INVALID':
    case 'QUERY_V2_DISABLED':
    case 'ONLINE_FETCH_DISABLED':
    case 'OPENDATA_ROUTE_INEFFECTIVE':
      return selection.reason
    default:
      return 'CAPABILITY_CENSUS_INVALID'
  }
}

export function lookupShellForV2Query(
  assetType: MarketAssetType,
  symbol: string,
  market: string,
  contract: MarketDataQueryContract | null,
  period: string,
): MarketInstrumentLookupResponse {
  return {
    asset_type: assetType,
    symbol,
    name: symbol,
    market: market || null,
    provider: contract ? 'local_market_data' : null,
    query_contract: contract,
    query_contract_symbol: contract ? symbol : null,
    query_contract_canonical_id: contract ? contract.request.identity.canonical_id : null,
    snapshot: {},
    history: {
      period,
      rows: [],
      total: 0,
    },
    indicators: {},
    warnings: [],
  }
}

export function instrumentOptionLabel(option: MarketInstrumentOption) {
  const name = option.name && option.name !== option.symbol ? ` ${option.name}` : ''
  const market = option.market ? ` · ${option.market}` : ''
  return `${option.symbol}${name}${market}`
}

export function instrumentOptionStatusTagType(option: MarketInstrumentOption) {
  if (
    option.data_availability === 'unknown'
    || option.has_history == null
    || option.history_rows == null
  ) {
    return 'info'
  }
  return option.has_history ? 'success' : 'warning'
}

export function buildRelatedTableKeywordsForAsset(
  assetType: MarketAssetType,
  symbol: string,
  assetTableSearchKeywords: Record<MarketAssetType, string[]>,
  familyTableKeywords: string[][],
): string[] {
  const keywords = new Set<string>(assetTableSearchKeywords[assetType])
  const plainSymbol = String(symbol || '').trim()
  if (plainSymbol) {
    keywords.add(plainSymbol)
    keywords.add(plainSymbol.toLowerCase())
    keywords.add(plainSymbol.replace(/^[a-z]+/i, ''))
    keywords.add(plainSymbol.replace(/[^A-Za-z0-9]+/g, '_').toLowerCase())
  }
  familyTableKeywords.forEach((group) => {
    group.forEach((keyword) => keywords.add(keyword))
  })
  return Array.from(keywords).filter(Boolean).slice(0, 10)
}

export function defaultFamilyIdForAsset(assetType: MarketAssetType): string {
  return `${assetType}.realtime`
}

export function isMarketPageSelectableFamilyForBundle(
  bundle: MarketDataQueryBundle | null,
  family: MarketDataQueryBundleFamily,
  assetType: MarketAssetType,
): boolean {
  return Boolean(
    bundle
    && bundle.requested_asset_type === assetType
    && family.asset_type === assetType
    && family.status === 'ready',
  )
}
