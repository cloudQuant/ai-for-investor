import type { Ref } from 'vue'
import {
  marketDataApi,
  normalizeOpenDataProvenanceCoverage,
  type MarketAssetType,
  type MarketDataCapabilitiesResponse,
  type MarketDataQueryBundleFamily,
  type MarketDataRouteSelection,
  type MarketInstrumentLookupResponse,
  type MarketInstrumentOption,
  type OpenDataDirectKlineRequest,
  type OpenDataDirectKlineResponse,
} from '@/api/marketData'
import type { DataTable } from '@/types'
import {
  boundedGenericObservationDateRange,
  defaultFamilyIdForAsset,
  isGenericObservationFamily,
  routeSelectionFailureReason,
} from './marketDataFormatters'
import {
  emptyOpenDataDirectKlineDisplay,
  isValidDirectBusinessDateRange,
  type DataPageDisplayMode,
  type GenericObservationResult,
  type OpenDataDirectKlineDisplayReason,
  type OpenDataDirectKlineDisplayState,
  type ReferenceSeriesResult,
} from './marketDataTypes'

export interface MarketDirectKlineRequestState {
  relatedTableRequestId: number
  openDataDirectRequestEpoch: number
  activeOpenDataDirectAbortController: AbortController | null
}

export interface MarketDataDirectKlineDeps {
  form: {
    asset_type: MarketAssetType
    symbol: string
    period: string
    market: string
  }
  dateRange: Ref<[string, string]>
  selectedFamilyId: Ref<string>
  result: Ref<MarketInstrumentLookupResponse | null>
  referenceSeriesResult: Ref<ReferenceSeriesResult | null>
  genericObservationResult: Ref<GenericObservationResult | null>
  relatedTables: Ref<DataTable[]>
  relatedTablesLoading: Ref<boolean>
  relatedTablesError: Ref<string>
  dataPageDisplayMode: Ref<DataPageDisplayMode>
  openDataDirectKlineDisplay: Ref<OpenDataDirectKlineDisplayState>
  instrumentAliasEffectiveOn: Ref<string | null>
  instrumentOptions: Ref<MarketInstrumentOption[]>
  instrumentOptionsLoading: Ref<boolean>
  instrumentOptionsCatalogMode: Ref<'legacy' | 'opendata' | null>
  marketDataCapabilitiesResolved: Ref<boolean>
  marketDataRouteSelection: Ref<MarketDataRouteSelection>
  requestState: MarketDirectKlineRequestState
  formSymbolText: () => string
  invalidateMarketDataQueryLifecycle: () => void
  resolveMarketDataCapabilities: () => Promise<MarketDataCapabilitiesResponse | null>
}

export function useMarketDataDirectKline(deps: MarketDataDirectKlineDeps) {
  function throwIfMarketDataQueryAborted(signal?: AbortSignal): void {
    if (signal?.aborted) throw new Error('MARKET_DATA_QUERY_ABORTED')
  }

  function constrainDateRangeForFamily(
    family: Pick<MarketDataQueryBundleFamily, 'data_kind'> | null | undefined,
    requestedDateRange: readonly [string | undefined, string | undefined] = deps.dateRange.value,
  ): readonly [string | undefined, string | undefined] {
    if (!isGenericObservationFamily(family)) return requestedDateRange
    const bounded = boundedGenericObservationDateRange(requestedDateRange)
    if (deps.dateRange.value?.[0] !== bounded[0] || deps.dateRange.value?.[1] !== bounded[1]) {
      deps.dateRange.value = bounded
    }
    return bounded
  }

  function clearMarketDataQueryResults() {
    deps.invalidateMarketDataQueryLifecycle()
    deps.result.value = null
    deps.referenceSeriesResult.value = null
    deps.genericObservationResult.value = null
    deps.requestState.relatedTableRequestId += 1
    deps.relatedTables.value = []
    deps.relatedTablesLoading.value = false
    deps.relatedTablesError.value = ''
  }

  function invalidateOpenDataDirectRequest(): void {
    deps.requestState.openDataDirectRequestEpoch += 1
    const controller = deps.requestState.activeOpenDataDirectAbortController
    deps.requestState.activeOpenDataDirectAbortController = null
    if (controller && !controller.signal.aborted) controller.abort()
    if (deps.dataPageDisplayMode.value === 'opendata_direct') {
      deps.openDataDirectKlineDisplay.value = emptyOpenDataDirectKlineDisplay()
    }
  }

  function finishOpenDataDirectRequest(controller: AbortController): void {
    if (deps.requestState.activeOpenDataDirectAbortController === controller) {
      deps.requestState.activeOpenDataDirectAbortController = null
    }
  }

  function isCurrentOpenDataDirectIntent(
    requestId: number,
    controller: AbortController,
    snapshot: {
      assetType: MarketAssetType
      symbol: string
      period: string
      familyId: string
      startDate: string
      endDate: string
      aliasEffectiveOn: string | null
    },
  ): boolean {
    return requestId === deps.requestState.openDataDirectRequestEpoch
      && deps.requestState.activeOpenDataDirectAbortController === controller
      && !controller.signal.aborted
      && deps.form.asset_type === snapshot.assetType
      && deps.formSymbolText() === snapshot.symbol
      && deps.form.period === snapshot.period
      && deps.selectedFamilyId.value === snapshot.familyId
      && deps.dateRange.value?.[0] === snapshot.startDate
      && deps.dateRange.value?.[1] === snapshot.endDate
      && deps.instrumentAliasEffectiveOn.value === snapshot.aliasEffectiveOn
  }

  function openDataDirectUnavailable(reason: OpenDataDirectKlineDisplayReason): void {
    deps.openDataDirectKlineDisplay.value = {
      ...deps.openDataDirectKlineDisplay.value,
      status: 'unavailable',
      rows: [],
      returnedBarCount: null,
      retrievedAt: null,
      coverageStatus: null,
      sourceAvailableAt: null,
      durableReceipt: null,
      reason,
    }
  }

  async function routeOpenDataDirectQuery(): Promise<boolean> {
    deps.invalidateMarketDataQueryLifecycle()
    if (deps.marketDataCapabilitiesResolved.value && deps.marketDataRouteSelection.value.mode === 'legacy') {
      invalidateOpenDataDirectRequest()
      deps.dataPageDisplayMode.value = 'legacy'
      return false
    }
    const controller = new AbortController()
    deps.requestState.activeOpenDataDirectAbortController?.abort()
    deps.requestState.activeOpenDataDirectAbortController = controller
    const requestId = ++deps.requestState.openDataDirectRequestEpoch
    const rawDates = Array.isArray(deps.dateRange.value) ? deps.dateRange.value : []
    const snapshot = {
      assetType: deps.form.asset_type,
      symbol: deps.formSymbolText(),
      period: deps.form.period,
      familyId: deps.selectedFamilyId.value,
      startDate: rawDates[0] || '',
      endDate: rawDates[1] || '',
      aliasEffectiveOn: deps.instrumentAliasEffectiveOn.value,
    }
    const rangeLabel = snapshot.startDate && snapshot.endDate
      ? `${snapshot.startDate} – ${snapshot.endDate}`
      : null
    const candidateRequest: OpenDataDirectKlineRequest | null = (
      snapshot.period === 'daily' && snapshot.startDate && snapshot.endDate
    ) ? {
        symbol: snapshot.symbol,
        start_date: snapshot.startDate,
        end_date: snapshot.endDate,
        period: 'daily',
      } : null
    deps.dataPageDisplayMode.value = 'opendata_direct'
    deps.openDataDirectKlineDisplay.value = {
      ...emptyOpenDataDirectKlineDisplay(),
      status: 'loading',
      request: candidateRequest,
      symbolLabel: snapshot.symbol || null,
      rangeLabel,
    }

    const isCurrent = () => isCurrentOpenDataDirectIntent(requestId, controller, snapshot)
    const release = () => finishOpenDataDirectRequest(controller)
    try {
      await deps.resolveMarketDataCapabilities()
      if (!isCurrent()) return true

      const selection = deps.marketDataRouteSelection.value
      if (selection.mode === 'legacy') {
        deps.dataPageDisplayMode.value = 'legacy'
        deps.openDataDirectKlineDisplay.value = emptyOpenDataDirectKlineDisplay()
        return false
      }
      if (selection.mode === 'unknown' || !selection.can_query) {
        openDataDirectUnavailable(routeSelectionFailureReason(selection))
        return true
      }
      if (snapshot.assetType !== 'stock') {
        openDataDirectUnavailable('UNSUPPORTED_ASSET')
        return true
      }
      if (snapshot.period !== 'daily') {
        openDataDirectUnavailable('UNSUPPORTED_PERIOD')
        return true
      }
      if (snapshot.familyId !== defaultFamilyIdForAsset('stock')) {
        openDataDirectUnavailable('UNSUPPORTED_ASSET')
        return true
      }
      if (!isValidDirectBusinessDateRange(snapshot.startDate, snapshot.endDate)) {
        openDataDirectUnavailable('INVALID_DATE_RANGE')
        return true
      }
      if (
        deps.instrumentOptionsLoading.value
        || deps.instrumentOptionsCatalogMode.value !== 'opendata'
        || !deps.instrumentOptions.value.some((option) => (
          option.asset_type === 'stock'
          && option.catalog_verified === true
          && option.symbol === snapshot.symbol
        ))
      ) {
        openDataDirectUnavailable('UNSUPPORTED_ASSET')
        return true
      }
      if (!candidateRequest) {
        openDataDirectUnavailable('INVALID_DATE_RANGE')
        return true
      }

      const response: OpenDataDirectKlineResponse = await marketDataApi.getOpenDataDirectKline(
        candidateRequest,
        { signal: controller.signal },
      )
      if (!isCurrent()) return true
      deps.openDataDirectKlineDisplay.value = {
        status: 'ready',
        request: candidateRequest,
        symbolLabel: snapshot.symbol,
        rangeLabel,
        rows: response.records,
        returnedBarCount: response.count,
        retrievedAt: response.provenance.retrieved_at,
        coverageStatus: normalizeOpenDataProvenanceCoverage(response.provenance.coverage_status),
        sourceAvailableAt: response.provenance.source_available_at,
        durableReceipt: response.provenance.durable_receipt,
        reason: null,
      }
      return true
    } catch (error) {
      if (!isCurrent()) return true
      const reason = error instanceof Error && error.message === 'OPENDATA_DIRECT_RESPONSE_INVALID'
        ? 'DIRECT_RESPONSE_INVALID'
        : 'DIRECT_REQUEST_FAILED'
      openDataDirectUnavailable(reason)
      return true
    } finally {
      release()
    }
  }

  return {
    throwIfMarketDataQueryAborted,
    constrainDateRangeForFamily,
    clearMarketDataQueryResults,
    invalidateOpenDataDirectRequest,
    finishOpenDataDirectRequest,
    isCurrentOpenDataDirectIntent,
    openDataDirectUnavailable,
    routeOpenDataDirectQuery,
  }
}
