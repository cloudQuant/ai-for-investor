/**
 * The OpenData stock_daily freshness and coverage evidence contract.
 *
 * This module owns the canonical coverage/availability states, the freshness
 * wire DTO with its fail-closed parser, and the display state the data page
 * renders. It is deliberately dependency-free so no API or view module can be
 * pulled into an import cycle through it.
 *
 * The fail-closed rules are the contract and must survive any refactor:
 * a `missing` report never reads as `PROVEN`, a junk `coverage_state` never
 * coerces into a healthy value, `SOURCE_LIMITED` / `NOT_SUPPORTED` stay
 * forward-only until a backend declares them, and a failed read renders as
 * `opendata_unavailable` rather than as a date or a legacy fallback (AC08).
 */

export function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function isIsoCalendarDate(value: unknown): value is string {
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

export function isIsoTimestamp(value: unknown): value is string {
  return typeof value === 'string'
    && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
    && isIsoCalendarDate(value.slice(0, 10))
    && Number.isFinite(Date.parse(value))
}

export type OpenDataStockDailyFreshnessStatus = 'fresh' | 'stale' | 'missing'

/**
 * The canonical OpenData coverage evidence states the data-management page
 * must keep distinct. The project rule is that an unproven state is never
 * rendered as a proven one, so the only value the page may fall back to is
 * `UNKNOWN`.
 *
 * - `PROVEN`: the intermediary measured coverage and issued evidence (a real
 *   latest business date and lag).
 * - `UNKNOWN`: coverage was not measured or the reason is unknown; it does not
 *   mean a stock has no data or that its history is empty.
 * - `SOURCE_LIMITED`: the upstream source retention boundary caps coverage;
 *   the archive cannot establish the full requested range.
 * - `NOT_SUPPORTED`: the dataset/domain/frequency is outside the OpenData
 *   service's supported scope.
 */
export type OpenDataCoverageState = 'PROVEN' | 'UNKNOWN' | 'SOURCE_LIMITED' | 'NOT_SUPPORTED'

/**
 * The page-level availability state combines the four coverage evidence states
 * with `opendata_unavailable`, which reports that the identified OpenData route
 * could not be reached or was disabled rather than any coverage conclusion.
 */
export type OpenDataAvailabilityState = OpenDataCoverageState | 'opendata_unavailable'

const OPEN_DATA_COVERAGE_STATES: readonly OpenDataCoverageState[] = [
  'PROVEN',
  'UNKNOWN',
  'SOURCE_LIMITED',
  'NOT_SUPPORTED',
]

/**
 * Accept only an exact, server-declared coverage state. An unrecognized or
 * malformed value must fail closed to `null` so callers can never coerce an
 * unverified coverage claim into `PROVEN`.
 */
export function parseOpenDataCoverageState(value: unknown): OpenDataCoverageState | null {
  if (typeof value !== 'string') return null
  return (OPEN_DATA_COVERAGE_STATES as readonly string[]).includes(value)
    ? value as OpenDataCoverageState
    : null
}

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
  /**
   * Forward contract only. The fixed stock_daily freshness proxy does not emit
   * this field yet, so a real read leaves it undefined and coverage is derived
   * from `status`. When the deployed OpenData service begins declaring
   * `SOURCE_LIMITED` / `NOT_SUPPORTED` it flows through here rather than being
   * collapsed into a freshness conclusion.
   */
  coverage_state?: OpenDataCoverageState
}

/**
 * Derive the coverage evidence state from one measured freshness report.
 *
 * A `missing` report is `UNKNOWN` (the reason is unknown), never a date. A
 * fresh or stale report has a measured latest business date, so its coverage is
 * `PROVEN` while the separate freshness `status` keeps conveying currency; a
 * stale report must not be relabeled as current. An explicit server-declared
 * `coverage_state` overrides the derived value so `SOURCE_LIMITED` and
 * `NOT_SUPPORTED` are honored once the service emits them.
 */
export function deriveOpenDataFreshnessCoverageState(
  response: OpenDataStockDailyFreshnessResponse,
): OpenDataCoverageState {
  if (response.coverage_state) return response.coverage_state
  return response.status === 'missing' ? 'UNKNOWN' : 'PROVEN'
}

/**
 * Resolve the single availability state the freshness card must present.
 *
 * It keeps `opendata_unavailable` distinct from a coverage conclusion: a failed
 * or disabled OpenData read is not `UNKNOWN` coverage and is never a date. Only
 * a ready report carries a real coverage state, and a `missing` report maps to
 * `UNKNOWN` so an unmeasured domain cannot look healthy. `null` means the card
 * has nothing to assert yet (idle/loading).
 */
export function deriveOpenDataFreshnessAvailability(input: {
  displayStatus: 'idle' | 'loading' | 'ready' | 'unavailable'
  response: OpenDataStockDailyFreshnessResponse | null
}): OpenDataAvailabilityState | null {
  if (input.displayStatus === 'unavailable') return 'opendata_unavailable'
  if (input.displayStatus === 'ready' && input.response) {
    return deriveOpenDataFreshnessCoverageState(input.response)
  }
  return null
}

/**
 * Map the direct-kline snapshot provenance coverage label to a canonical state.
 *
 * The snapshot-only direct read is a non-durable request: its backend always
 * reports `unknown` coverage (no snapshot id, committed_at, or durable receipt),
 * so it renders as `UNKNOWN` and never as a proven range. An unrecognized label
 * also fails closed to `UNKNOWN` rather than to a healthy state.
 */
export function normalizeOpenDataProvenanceCoverage(value: unknown): OpenDataCoverageState {
  if (value === 'unknown') return 'UNKNOWN'
  return parseOpenDataCoverageState(value) ?? 'UNKNOWN'
}

export interface OpenDataStockDailyFreshnessOptions {
  signal?: AbortSignal
}

export type OpenDataStockDailyFreshnessDisplayStatus =
  | 'idle'
  | 'loading'
  | 'ready'
  | 'unavailable'

export interface OpenDataStockDailyFreshnessDisplayState {
  status: OpenDataStockDailyFreshnessDisplayStatus
  response: OpenDataStockDailyFreshnessResponse | null
}

export function emptyOpenDataStockDailyFreshnessDisplay(): OpenDataStockDailyFreshnessDisplayState {
  return { status: 'idle', response: null }
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

  // A declared coverage_state is optional and forward-only. When it is present
  // it must be a canonical OpenData state; anything else fails closed so an
  // unverified coverage claim can never be coerced into a healthy value.
  let coverageState: OpenDataCoverageState | undefined
  if (value.coverage_state !== undefined) {
    const parsedCoverage = parseOpenDataCoverageState(value.coverage_state)
    if (!parsedCoverage) return null
    coverageState = parsedCoverage
  }

  if (value.status === 'missing') {
    if (value.field !== null || value.latest !== null || value.lag_days !== null) return null
    // A missing report has no measured evidence; it must not be labeled PROVEN.
    if (coverageState === 'PROVEN') return null
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
    ...(coverageState === undefined ? {} : { coverage_state: coverageState }),
  }
}
