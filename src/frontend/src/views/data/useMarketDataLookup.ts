import type { ComputedRef, Ref } from 'vue'
import { ElMessage } from 'element-plus'
import { TrendCharts } from '@element-plus/icons-vue'
import {
  classifyMarketDataRouteSelection,
  hasMarketDataCapabilities,
  marketDataApi,
  type MarketAssetType,
  type MarketDataCapabilitiesResponse,
  type MarketDataQueryBundle,
  type MarketDataQueryBundleFamily,
  type MarketDataQueryContract,
  type MarketDataQueryFrequency,
  type MarketDataQueryMode,
  type MarketDataRouteSelection,
  type MarketInstrumentLookupResponse,
  type MarketInstrumentOption,
} from '@/api/marketData'
import type { DataTable } from '@/types'
import type { MarketDataCoverageResponse } from '@/types/trust'
import { assetTabs, routeTabMap } from './marketDataCatalogSpecs'
import {
  defaultFamilyIdForAsset,
  hasIncompleteCoverageStatus,
  isGenericObservationFamily,
  resetToDeclaredPeriod,
  v2FrequencyForLegacyPeriod,
} from './marketDataFormatters'
import {
  isMarketDataQueryBundleFeatureEnabled,
  isMarketDataQueryV2FeatureEnabled,
  MARKET_ASSET_SELECTIONS_STORAGE_KEY,
  type AssetTab,
  type DataPageDisplayMode,
  type GenericObservationResult,
  type MarketAssetSelections,
  type MarketDataPlatformStatus,
  type MarketLookupIntent,
  type MarketLookupRequestSnapshot,
  type ReferenceSeriesResult,
  type V2LookupResult,
} from './marketDataTypes'

export interface MarketDataLookupRequestState {
  instrumentOptionsRequestId: number
  coverageRequestId: number
  lookupRequestId: number
  activeMarketDataQueryAbortController: AbortController | null
  activeMarketDataQuerySelectionKey: string | null
  marketDataCapabilitiesRequest: Promise<MarketDataCapabilitiesResponse | null> | null
}

export interface MarketDataLookupDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  form: {
    asset_type: MarketAssetType
    symbol: string
    period: string
    market: string
  }
  dateRange: Ref<[string, string]>
  loading: Ref<boolean>
  result: Ref<MarketInstrumentLookupResponse | null>
  dataPageDisplayMode: Ref<DataPageDisplayMode>
  selectedFamilyId: Ref<string>
  selectedMarketPageFamily: ComputedRef<MarketDataQueryBundleFamily | null>
  isReferenceSeriesSelected: ComputedRef<boolean>
  isGenericObservationSelected: ComputedRef<boolean>
  instrumentOptions: Ref<MarketInstrumentOption[]>
  instrumentOptionsCatalogMode: Ref<'legacy' | 'opendata' | null>
  instrumentOptionsError: Ref<string>
  instrumentAliasEffectiveOn: Ref<string | null>
  instrumentOptionsSearchTerm: Ref<string>
  relatedTables: Ref<DataTable[]>
  coverageRows: Ref<MarketDataCoverageResponse[]>
  coverageLoading: Ref<boolean>
  coverageRefreshing: Ref<boolean>
  coverageError: Ref<string>
  marketDataPlatformStatus: Ref<MarketDataPlatformStatus>
  marketDataQueryBundle: Ref<MarketDataQueryBundle | null>
  marketDataCapabilities: Ref<MarketDataCapabilitiesResponse | null>
  marketDataCapabilitiesResolved: Ref<boolean>
  marketDataRouteSelection: Ref<MarketDataRouteSelection>
  referenceSeriesResult: Ref<ReferenceSeriesResult | null>
  genericObservationResult: Ref<GenericObservationResult | null>
  requestState: MarketDataLookupRequestState
  formSymbolText: () => string
  formMarketText: () => string
  invalidateOpenDataDirectRequest: () => void
  routeOpenDataDirectQuery: () => Promise<boolean>
  clearMarketDataQueryResults: () => void
  invalidateOpenDataStockDailyFreshnessRequest: () => void
  clearMarketDataFamilyScopedState: (familyId: string | null) => void
  setMarketDataPlatformErrorStatus: () => void
  setLegacyMarketDataPlatformStatus: (fallbackReason?: string | null) => void
  setMarketDataBundleUnconfiguredStatus: (familyId?: string | null) => void
  setMarketDataBundlePeriodUnsupportedStatus: (
    family: MarketDataQueryBundleFamily,
    requestedFrequency: MarketDataQueryFrequency,
    resetPeriod: string | null,
  ) => void
  setV2MarketDataPlatformStatus: (
    response: V2LookupResult['response'],
    queryMode: MarketDataQueryMode,
    capabilities: MarketDataCapabilitiesResponse | null,
  ) => void
  constrainDateRangeForFamily: (
    family: Pick<MarketDataQueryBundleFamily, 'data_kind'> | null | undefined,
    requestedDateRange?: readonly [string | undefined, string | undefined],
  ) => readonly [string | undefined, string | undefined]
  queryContractForCurrentLookup: (
    lookupResult: MarketInstrumentLookupResponse | null,
    assetType: MarketAssetType,
    symbol: string,
    period?: string,
  ) => MarketDataQueryContract | null
  resolveV2QueryBundle: (
    assetType: MarketAssetType,
    bundleFeatureEnabled: boolean,
  ) => Promise<{ bundle: MarketDataQueryBundle | null; fellBack: boolean }>
  resolveV2QueryContract: (
    assetType: MarketAssetType,
    symbol: string,
    period: string,
    declaredFamily: MarketDataQueryBundleFamily | null,
  ) => Promise<{ contract: MarketDataQueryContract | null; fellBack: boolean }>
  selectedMarketPageFamilyFromQueryBundle: (
    bundle: MarketDataQueryBundle,
    assetType: MarketAssetType,
    familyId: string,
  ) => MarketDataQueryBundleFamily | null
  lookupShellForV2Query: (
    assetType: MarketAssetType,
    symbol: string,
    market: string,
    contract: MarketDataQueryContract | null,
    period?: string,
  ) => MarketInstrumentLookupResponse
  queryV2FromLookupContract: (
    contract: MarketDataQueryContract,
    legacyLookup: MarketInstrumentLookupResponse,
    queryMode: MarketDataQueryMode,
    requestedDateRange: readonly [string | undefined, string | undefined],
    declaredFamily: MarketDataQueryBundleFamily | null,
    signal?: AbortSignal,
  ) => Promise<V2LookupResult>
  loadInstrumentOptions: (search?: string, adoptFirstOnMiss?: boolean) => Promise<void>
  loadRelatedTables: (lookupResult?: MarketInstrumentLookupResponse | null) => Promise<void>
  loadInstrumentsThenLookup: () => void
}

export function useMarketDataLookup(deps: MarketDataLookupDeps) {
  function currentAssetTab(): AssetTab {
    return assetTabs.find((asset) => asset.key === deps.form.asset_type) || {
      key: 'stock',
      labelKey: 'dataMgmt.tabStock',
      placeholderKey: 'dataMgmt.stockSymbolPlaceholder',
      defaultSymbol: '000001',
      icon: TrendCharts,
    }
  }

  function marketDataQuerySelectionKey(): string {
    const currentDateRange = Array.isArray(deps.dateRange.value) ? deps.dateRange.value : []
    return JSON.stringify([
      deps.form.asset_type,
      deps.formSymbolText(),
      deps.formMarketText(),
      deps.form.period,
      currentDateRange[0] || '',
      currentDateRange[1] || '',
      deps.selectedFamilyId.value,
    ])
  }

  function releaseMarketDataQueryLifecycle(controller: AbortController): void {
    if (deps.requestState.activeMarketDataQueryAbortController !== controller) return
    deps.requestState.activeMarketDataQueryAbortController = null
    deps.requestState.activeMarketDataQuerySelectionKey = null
  }

  function abortActiveMarketDataQueryLifecycle(): void {
    const controller = deps.requestState.activeMarketDataQueryAbortController
    if (!controller) return
    if (!controller.signal.aborted) controller.abort()
    releaseMarketDataQueryLifecycle(controller)
  }

  function invalidateMarketDataQueryLifecycle(): void {
    abortActiveMarketDataQueryLifecycle()
    deps.requestState.lookupRequestId += 1
    deps.loading.value = false
  }

  function beginMarketDataQueryLifecycle(): {
    controller: AbortController
    requestId: number
    selectionKey: string
  } {
    abortActiveMarketDataQueryLifecycle()
    const controller = new AbortController()
    const selectionKey = marketDataQuerySelectionKey()
    deps.requestState.activeMarketDataQueryAbortController = controller
    deps.requestState.activeMarketDataQuerySelectionKey = selectionKey
    return {
      controller,
      requestId: ++deps.requestState.lookupRequestId,
      selectionKey,
    }
  }

  async function resolveMarketDataCapabilities(): Promise<MarketDataCapabilitiesResponse | null> {
    if (deps.marketDataCapabilitiesResolved.value) return deps.marketDataCapabilities.value
    if (deps.requestState.marketDataCapabilitiesRequest) return deps.requestState.marketDataCapabilitiesRequest

    deps.requestState.marketDataCapabilitiesRequest = marketDataApi.getCapabilities()
      .then((response) => {
        deps.marketDataRouteSelection.value = classifyMarketDataRouteSelection(response)
        deps.marketDataCapabilities.value = hasMarketDataCapabilities(response) ? response : null
        return deps.marketDataCapabilities.value
      })
      .catch(() => {
        deps.marketDataCapabilities.value = null
        deps.marketDataRouteSelection.value = classifyMarketDataRouteSelection(null)
        return null
      })
      .finally(() => {
        deps.marketDataCapabilitiesResolved.value = true
        deps.requestState.marketDataCapabilitiesRequest = null
      })
    return deps.requestState.marketDataCapabilitiesRequest
  }

  function isLocalCoverageMatrixAllowed(): boolean {
    return deps.form.asset_type !== 'stock'
      || (
        deps.marketDataCapabilitiesResolved.value
        && deps.marketDataRouteSelection.value.mode === 'legacy'
      )
  }

  function clearLocalCoverageMatrix(): void {
    deps.requestState.coverageRequestId += 1
    deps.coverageRows.value = []
    deps.coverageLoading.value = false
    deps.coverageRefreshing.value = false
    deps.coverageError.value = ''
  }

  function assetLabel(assetType: MarketAssetType) {
    return deps.t(assetTabs.find((asset) => asset.key === assetType)?.labelKey || 'dataMgmt.assetStock')
  }

  function setAssetType(assetType: MarketAssetType) {
    if (applyAssetType(assetType)) deps.loadInstrumentsThenLookup()
  }

  function applyRouteTab(tabValue: unknown, resetResult: boolean) {
    const assetType = routeTabMap[String(tabValue || '').toLowerCase()]
    if (!assetType) return false
    return applyAssetType(assetType, resetResult)
  }

  function applyAssetType(assetType: MarketAssetType, resetResult = true) {
    const changed = deps.form.asset_type !== assetType
    if (changed) {
      invalidateMarketDataQueryLifecycle()
      deps.invalidateOpenDataStockDailyFreshnessRequest()
    }
    deps.form.asset_type = assetType
    restoreAssetSelection(assetType)
    if (changed) {
      deps.requestState.instrumentOptionsRequestId += 1
      deps.instrumentOptionsCatalogMode.value = null
      deps.instrumentOptionsError.value = ''
      deps.instrumentAliasEffectiveOn.value = null
      deps.instrumentOptionsSearchTerm.value = ''
      deps.instrumentOptions.value = []
      deps.selectedFamilyId.value = defaultFamilyIdForAsset(assetType)
      deps.referenceSeriesResult.value = null
      deps.genericObservationResult.value = null
      deps.clearMarketDataFamilyScopedState(deps.selectedFamilyId.value)
      if (resetResult) deps.result.value = null
    }
    return changed
  }

  function restoreAssetSelection(assetType: MarketAssetType): void {
    const selection = readMarketAssetSelections()[assetType]
    const defaultSymbol = assetTabs.find((tab) => tab.key === assetType)?.defaultSymbol || ''
    deps.form.symbol = selection?.symbol || defaultSymbol
    deps.form.market = assetType === 'futures' ? selection?.market || 'CF' : 'CF'
  }

  function readMarketAssetSelections(): MarketAssetSelections {
    try {
      const raw = localStorage.getItem(MARKET_ASSET_SELECTIONS_STORAGE_KEY)
      if (!raw) return {}
      const parsed = JSON.parse(raw) as Record<string, { symbol?: unknown; market?: unknown }>
      const selections: MarketAssetSelections = {}
      for (const tab of assetTabs) {
        const candidate = parsed[tab.key]
        const symbol = typeof candidate?.symbol === 'string' ? candidate.symbol.trim() : ''
        if (!symbol) continue
        selections[tab.key] = {
          symbol,
          market: typeof candidate?.market === 'string' ? candidate.market.trim() : undefined,
        }
      }
      return selections
    } catch {
      return {}
    }
  }

  function rememberMarketAssetSelection(assetType: MarketAssetType, symbol: string, market?: string): void {
    try {
      const selections = readMarketAssetSelections()
      selections[assetType] = {
        symbol,
        ...(assetType === 'futures' && market ? { market } : {}),
      }
      localStorage.setItem(MARKET_ASSET_SELECTIONS_STORAGE_KEY, JSON.stringify(selections))
    } catch {
      // Persistence may be unavailable in private browsing; the query still succeeds.
    }
  }

  async function lookupInstrument(intent: MarketLookupIntent = 'local_first') {
    const queryMode: MarketDataQueryMode = intent === true
      ? 'refresh'
      : intent === false ? 'local_first' : intent
    const refreshOnline = queryMode === 'refresh'
    const requestedAssetType = deps.form.asset_type
    const requestedSymbol = deps.formSymbolText()
    if (!requestedSymbol) {
      ElMessage.error(deps.t('dataMgmt.msgSymbolRequired'))
      return
    }
    if (queryMode === 'local_only' && requestedAssetType === 'stock') {
      if (!deps.marketDataCapabilitiesResolved.value) await resolveMarketDataCapabilities()
      if (
        deps.form.asset_type !== requestedAssetType
        || deps.formSymbolText() !== requestedSymbol
        || deps.marketDataRouteSelection.value.mode !== 'legacy'
      ) return
    }
    if (queryMode === 'local_first') {
      if (await deps.routeOpenDataDirectQuery()) return
    } else {
      deps.invalidateOpenDataDirectRequest()
      deps.dataPageDisplayMode.value = 'legacy'
    }
    if (deps.form.asset_type === 'stock' && deps.instrumentOptionsCatalogMode.value === null) {
      if (!deps.instrumentOptionsError.value) {
        await deps.loadInstrumentOptions(requestedSymbol)
        if (deps.form.asset_type !== requestedAssetType || deps.formSymbolText() !== requestedSymbol) return
      }
      if (deps.instrumentOptionsCatalogMode.value === null) {
        deps.clearMarketDataQueryResults()
        if (!deps.instrumentOptionsError.value) {
          deps.instrumentOptionsError.value = deps.t('dataMgmt.marketDataSourceError')
        }
        deps.setMarketDataPlatformErrorStatus()
        return
      }
    }
    if (
      deps.form.asset_type === 'stock'
      && deps.instrumentOptionsCatalogMode.value === 'opendata'
      && !deps.instrumentOptions.value.some(
        (option) => option.catalog_verified === true && option.symbol === requestedSymbol,
      )
    ) {
      deps.clearMarketDataQueryResults()
      if (!deps.instrumentOptionsError.value) {
        deps.instrumentOptionsError.value = '请先从已验证的 OpenData 标的目录中选择标的。'
      }
      deps.setMarketDataPlatformErrorStatus()
      return
    }
    if (deps.form.asset_type === 'stock' && deps.instrumentOptionsCatalogMode.value === 'opendata') {
      deps.instrumentOptionsError.value = ''
    }

    deps.constrainDateRangeForFamily(deps.selectedMarketPageFamily.value)
    const {
      controller: lifecycleController,
      requestId,
      selectionKey,
    } = beginMarketDataQueryLifecycle()
    const { signal } = lifecycleController
    const currentDateRange = Array.isArray(deps.dateRange.value) ? deps.dateRange.value : []
    const requestSnapshot: MarketLookupRequestSnapshot = {
      assetType: deps.form.asset_type,
      symbol: requestedSymbol,
      market: deps.form.asset_type === 'futures' ? deps.formMarketText() : '',
      period: deps.form.period,
      dateRange: [currentDateRange[0], currentDateRange[1]],
      familyId: deps.selectedFamilyId.value,
    }
    const {
      assetType: queryAssetType,
      symbol,
      market: queryMarket,
      period: queryPeriod,
      familyId: requestedFamilyId,
    } = requestSnapshot
    let queryStartDate = requestSnapshot.dateRange[0]
    let queryEndDate = requestSnapshot.dateRange[1]
    const requestedNonDefaultFamily = requestedFamilyId !== defaultFamilyIdForAsset(queryAssetType)

    const isCurrentFamilyLookup = () => (
      requestId === deps.requestState.lookupRequestId
      && deps.requestState.activeMarketDataQueryAbortController === lifecycleController
      && deps.requestState.activeMarketDataQuerySelectionKey === selectionKey
      && !signal.aborted
      && deps.form.asset_type === queryAssetType
      && deps.formSymbolText() === symbol
      && (queryAssetType !== 'futures' || deps.formMarketText() === queryMarket)
      && deps.form.period === queryPeriod
      && deps.dateRange.value?.[0] === queryStartDate
      && deps.dateRange.value?.[1] === queryEndDate
      && deps.selectedFamilyId.value === requestedFamilyId
    )

    const capabilities = await resolveMarketDataCapabilities()
    if (!isCurrentFamilyLookup()) {
      if (!signal.aborted) lifecycleController.abort()
      releaseMarketDataQueryLifecycle(lifecycleController)
      return
    }
    const v2FeatureEnabled = isMarketDataQueryV2FeatureEnabled(capabilities)
    if (deps.isReferenceSeriesSelected.value || deps.isGenericObservationSelected.value) {
      deps.result.value = null
      deps.referenceSeriesResult.value = null
      deps.genericObservationResult.value = null
    }
    const existingContract = v2FeatureEnabled
      ? deps.queryContractForCurrentLookup(deps.result.value, queryAssetType, symbol, queryPeriod)
      : null
    const bundleFeatureEnabled = isMarketDataQueryBundleFeatureEnabled(capabilities)
    if (bundleFeatureEnabled) deps.marketDataQueryBundle.value = null
    deps.loading.value = true
    try {
      let directContract = existingContract
      let directLookup = existingContract && deps.result.value ? deps.result.value : null
      let v2Fallback = false
      let bundleIssued = false
      let declaredFamily: MarketDataQueryBundleFamily | null = null

      if (bundleFeatureEnabled) {
        const bundleResolution = await deps.resolveV2QueryBundle(queryAssetType, bundleFeatureEnabled)
        if (!isCurrentFamilyLookup()) return
        v2Fallback = bundleResolution.fellBack
        if (!bundleResolution.bundle && requestedNonDefaultFamily) {
          throw new Error('MARKET_DATA_QUERY_BUNDLE_UNAVAILABLE_AFTER_FAMILY_SELECTION')
        }
        if (bundleResolution.bundle) {
          bundleIssued = true
          deps.marketDataQueryBundle.value = bundleResolution.bundle
          declaredFamily = deps.selectedMarketPageFamilyFromQueryBundle(
            bundleResolution.bundle,
            queryAssetType,
            requestedFamilyId,
          )
          if (!declaredFamily) {
            deps.result.value = deps.lookupShellForV2Query(
              queryAssetType,
              symbol,
              queryMarket,
              null,
              queryPeriod,
            )
            deps.relatedTables.value = []
            deps.setMarketDataBundleUnconfiguredStatus(requestedFamilyId)
            rememberMarketAssetSelection(queryAssetType, symbol, queryMarket)
            return
          }
          if (isGenericObservationFamily(declaredFamily)) {
            const boundedRange = deps.constrainDateRangeForFamily(
              declaredFamily,
              requestSnapshot.dateRange,
            )
            requestSnapshot.dateRange = [boundedRange[0], boundedRange[1]]
            queryStartDate = boundedRange[0]
            queryEndDate = boundedRange[1]
          }
          const requestedFrequency = v2FrequencyForLegacyPeriod(queryPeriod)
          if (!declaredFamily.frequencies.includes(requestedFrequency)) {
            const resetPeriod = resetToDeclaredPeriod(declaredFamily)
            if (resetPeriod) deps.form.period = resetPeriod
            deps.setMarketDataBundlePeriodUnsupportedStatus(
              declaredFamily,
              requestedFrequency,
              resetPeriod,
            )
            rememberMarketAssetSelection(queryAssetType, symbol, queryMarket)
            return
          }
          directContract = null
          directLookup = null
        }
      }

      if (v2FeatureEnabled && !directContract) {
        const resolution = await deps.resolveV2QueryContract(
          queryAssetType,
          symbol,
          queryPeriod,
          declaredFamily,
        )
        if (!isCurrentFamilyLookup()) return
        directContract = resolution.contract
        v2Fallback = v2Fallback || resolution.fellBack
        if (directContract) {
          directLookup = deps.lookupShellForV2Query(
            queryAssetType,
            symbol,
            queryMarket,
            directContract,
            queryPeriod,
          )
        }
      }

      if (v2FeatureEnabled && directContract && directLookup) {
        const v2Result = await deps.queryV2FromLookupContract(
          directContract,
          directLookup,
          queryMode,
          requestSnapshot.dateRange,
          declaredFamily,
          signal,
        )
        if (!isCurrentFamilyLookup()) return
        if (queryMode === 'local_only' && v2Result.response.fetches.length > 0) {
          throw new Error('MARKET_DATA_LOCAL_ONLY_FETCH_EVIDENCE')
        }
        deps.setV2MarketDataPlatformStatus(v2Result.response, queryMode, capabilities)
        deps.referenceSeriesResult.value = v2Result.referenceSeries
        deps.genericObservationResult.value = v2Result.genericObservations
        deps.result.value = v2Result.lookup
        rememberMarketAssetSelection(queryAssetType, symbol, queryMarket)
        void deps.loadRelatedTables(v2Result.lookup)
        if (!hasIncompleteCoverageStatus(deps.marketDataPlatformStatus.value.path)) {
          ElMessage.success(deps.t('dataMgmt.msgQueriedCount', {
            count: v2Result.genericObservations?.observations.length ?? v2Result.lookup.history.total,
          }))
        }
        return
      }

      if (bundleIssued) {
        throw new Error('MARKET_DATA_QUERY_CONTRACT_UNAVAILABLE_AFTER_BUNDLE')
      }

      if (refreshOnline) {
        deps.setMarketDataPlatformErrorStatus()
        ElMessage.error(deps.t('dataMgmt.msgQueryFail'))
        return
      }

      const legacyResponse = await marketDataApi.lookupInstrument({
        asset_type: queryAssetType,
        symbol,
        period: queryPeriod,
        start_date: queryStartDate,
        end_date: queryEndDate,
        market: queryMarket || undefined,
        refresh_online: false,
      })
      if (!isCurrentFamilyLookup()) return

      let response = legacyResponse
      const bootstrapContract = v2FeatureEnabled && !directContract && !refreshOnline
        ? deps.queryContractForCurrentLookup(legacyResponse, queryAssetType, symbol, queryPeriod)
        : null
      if (
        v2FeatureEnabled
        && !directContract
        && !refreshOnline
        && legacyResponse.query_contract != null
        && !bootstrapContract
      ) {
        throw new Error('MARKET_DATA_LEGACY_QUERY_CONTRACT_INVALID')
      }
      if (bootstrapContract) {
        const v2Result = await deps.queryV2FromLookupContract(
          bootstrapContract,
          legacyResponse,
          queryMode,
          requestSnapshot.dateRange,
          declaredFamily,
          signal,
        )
        if (!isCurrentFamilyLookup()) return
        if (queryMode === 'local_only' && v2Result.response.fetches.length > 0) {
          throw new Error('MARKET_DATA_LOCAL_ONLY_FETCH_EVIDENCE')
        }
        deps.setV2MarketDataPlatformStatus(v2Result.response, queryMode, capabilities)
        deps.referenceSeriesResult.value = v2Result.referenceSeries
        deps.genericObservationResult.value = v2Result.genericObservations
        response = v2Result.lookup
      }
      if (!bootstrapContract && !directContract) {
        deps.setLegacyMarketDataPlatformStatus(v2Fallback ? 'MARKET_DATA_QUERY_V2_UNAVAILABLE' : null)
      }

      deps.result.value = response
      rememberMarketAssetSelection(queryAssetType, symbol, queryMarket)
      void deps.loadRelatedTables(response)
      if (!hasIncompleteCoverageStatus(deps.marketDataPlatformStatus.value.path)) {
        ElMessage.success(deps.t('dataMgmt.msgQueriedCount', { count: response.history.total }))
      }
    } catch {
      if (signal.aborted) return
      if (!isCurrentFamilyLookup()) return
      deps.result.value = null
      deps.referenceSeriesResult.value = null
      deps.genericObservationResult.value = null
      deps.relatedTables.value = []
      deps.setMarketDataPlatformErrorStatus()
      ElMessage.error(deps.t('dataMgmt.msgQueryFail'))
    } finally {
      if (requestId === deps.requestState.lookupRequestId) deps.loading.value = false
      releaseMarketDataQueryLifecycle(lifecycleController)
    }
  }

  return {
    currentAssetTab,
    marketDataQuerySelectionKey,
    releaseMarketDataQueryLifecycle,
    abortActiveMarketDataQueryLifecycle,
    invalidateMarketDataQueryLifecycle,
    beginMarketDataQueryLifecycle,
    resolveMarketDataCapabilities,
    isLocalCoverageMatrixAllowed,
    clearLocalCoverageMatrix,
    assetLabel,
    setAssetType,
    applyRouteTab,
    applyAssetType,
    restoreAssetSelection,
    lookupInstrument,
  }
}
