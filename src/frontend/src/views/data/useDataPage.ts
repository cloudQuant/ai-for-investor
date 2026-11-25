/** State, data loading, and chart orchestration for the historical data page. */

import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import {
  type MarketAssetType,
  type MarketDataCapabilitiesResponse,
  type MarketDataQueryBundle,
  type MarketDataQueryBundleFamily,
  type MarketDataRouteSelection,
  type MarketInstrumentLookupResponse,
  type MarketInstrumentOption,
} from '@/api/marketData'
import type { DataTable } from '@/types'
import type { MarketDataCoverageResponse } from '@/types/trust'
import {
  assetDataFamilySpecs,
  assetDisplayConfigs,
  assetTableSearchKeywords,
  assetTabs,
  fieldLabelKeys,
  routeTabMap,
} from './marketDataCatalogSpecs'
import {
  averageNumbers,
  candleColor,
  capitalize,
  closeVolatilityPct,
  coverageStatusTagType,
  cumulativeReturns,
  drawdownSeries,
  formatCoverageRatio,
  formatGenericObservationCell,
  formatGenericObservationValue,
  formatHistoryCell,
  formatNumber,
  formatPair,
  formatPercent,
  formatReferenceSeriesField,
  formatText,
  genericObservationResultFromV2Response,
  hasValue,
  instrumentOptionLabel,
  instrumentOptionStatusTagType,
  isFiniteNumber,
  numericSeries,
  numericValue,
  ohlcTuple,
  periodReturnPct,
  queryWindowFromDateRange,
  referenceSeriesFieldTone,
  referenceSeriesRowsFromV2Response,
  sumNumbers,
  toDateInput,
  toneClass,
  v2EventTimeLabel,
  v2FrequencyForLegacyPeriod,
  v2HistoryRows,
} from './marketDataFormatters'
import {
  emptyOpenDataDirectKlineDisplay,
  type ChartMode,
  type DataPageDisplayMode,
  type GenericObservationResult,
  type MarketDataPlatformStatus,
  type OpenDataDirectKlineDisplayReason,
  type OpenDataDirectKlineDisplayState,
  type OpenDataDirectKlineDisplayStatus,
  type ReferenceSeriesResult,
} from './marketDataTypes'
import { useMarketDataCatalog } from './useMarketDataCatalog'
import { createMarketDataChartManager } from './useMarketDataChart'
import { useMarketDataDirectKline } from './useMarketDataDirectKline'
import { useMarketDataLookup } from './useMarketDataLookup'
import { useMarketDataPresentation } from './useMarketDataPresentation'
import { useMarketDataV2Query } from './useMarketDataV2Query'
import { useOpenDataStockDailyFreshness } from './useOpenDataStockDailyFreshness'

export type {
  DataPageDisplayMode,
  OpenDataDirectKlineDisplayReason,
  OpenDataDirectKlineDisplayState,
  OpenDataDirectKlineDisplayStatus,
}

export function useDataPage() {
  const { t } = useI18n()
  const route = useRoute()
  const router = useRouter()

  const today = new Date()
  const ninetyDaysAgo = new Date(today)
  ninetyDaysAgo.setDate(today.getDate() - 90)

  const selectedFamilyId = ref('stock.realtime')
  const form = reactive({
    asset_type: 'stock' as MarketAssetType,
    symbol: '000001',
    period: 'daily',
    market: 'CF',
  })
  const dateRange = ref<[string, string]>([toDateInput(ninetyDaysAgo), toDateInput(today)])
  const loading = ref(false)
  const result = ref<MarketInstrumentLookupResponse | null>(null)
  const dataPageDisplayMode = ref<DataPageDisplayMode>('legacy')
  const openDataDirectKlineDisplay = ref<OpenDataDirectKlineDisplayState>(
    emptyOpenDataDirectKlineDisplay(),
  )
  const chartMode = ref<ChartMode>('price')
  const marketChartRef = ref<HTMLDivElement>()
  const instrumentOptions = ref<MarketInstrumentOption[]>([])
  const instrumentOptionsLoading = ref(false)
  const instrumentOptionsCatalogMode = ref<'legacy' | 'opendata' | null>(null)
  const instrumentOptionsError = ref('')
  const instrumentAliasEffectiveOn = ref<string | null>(null)
  const instrumentOptionsSearchTerm = ref('')
  const relatedTablesLoading = ref(false)
  const relatedTables = ref<DataTable[]>([])
  const relatedTablesError = ref('')
  const coverageRows = ref<MarketDataCoverageResponse[]>([])
  const coverageLoading = ref(false)
  const coverageRefreshing = ref(false)
  const coverageError = ref('')
  const coverageTimeframe = ref('1d')
  const coverageProvider = ref('akshare_data')
  const marketDataPlatformStatus = ref<MarketDataPlatformStatus>({
    path: 'legacy',
    provider: null,
    coverageStatus: null,
    coverageRatio: null,
    fetchedProviderCount: 0,
    fallbackReason: null,
    queryId: null,
    canonicalId: null,
    datasetCode: null,
    sourcePolicyId: null,
    instrumentMetadataVersion: null,
    familyId: null,
    periodConstraint: null,
  })
  const marketDataQueryBundle = ref<MarketDataQueryBundle | null>(null)
  const marketDataCapabilities = ref<MarketDataCapabilitiesResponse | null>(null)
  const referenceSeriesResult = ref<ReferenceSeriesResult | null>(null)
  const genericObservationResult = ref<GenericObservationResult | null>(null)
  const viewportWidth = ref(window.innerWidth)
  const marketDataCapabilitiesResolved = ref(false)
  const marketDataRouteSelection = ref<MarketDataRouteSelection>({
    mode: 'unknown',
    can_query: false,
    reason: 'CAPABILITIES_UNAVAILABLE',
  })

  const requestState = {
    instrumentOptionsRequestId: 0,
    relatedTableRequestId: 0,
    coverageRequestId: 0,
    lookupRequestId: 0,
    openDataDirectRequestEpoch: 0,
    marketPageBootstrapEpoch: 0,
    activeOpenDataDirectAbortController: null as AbortController | null,
    activeMarketDataQueryAbortController: null as AbortController | null,
    activeMarketDataQuerySelectionKey: null as string | null,
    marketDataCapabilitiesRequest: null as Promise<MarketDataCapabilitiesResponse | null> | null,
  }

  const snapshot = computed<Record<string, unknown>>(() => result.value?.snapshot || {})
  const historyRows = computed(() => result.value?.history.rows || [])
  const isOpenDataOnlyStockRoute = computed(() => (
    form.asset_type === 'stock'
    && marketDataCapabilitiesResolved.value
    && marketDataRouteSelection.value.mode === 'opendata_only'
  ))
  const canReadOpenDataStockDailyFreshness = computed(() => (
    isOpenDataOnlyStockRoute.value
    && marketDataRouteSelection.value.can_query
  ))
  const {
    openDataStockDailyFreshnessDisplay,
    openDataStockDailyFreshnessAvailability,
    invalidateOpenDataStockDailyFreshnessRequest,
    refreshOpenDataStockDailyFreshness,
  } = useOpenDataStockDailyFreshness(canReadOpenDataStockDailyFreshness)

  const showLocalCoverageMatrix = computed(() => (
    form.asset_type !== 'stock'
    || (
      marketDataCapabilitiesResolved.value
      && marketDataRouteSelection.value.mode === 'legacy'
    )
  ))
  const stockDataRouteNotice = computed(() => {
    if (form.asset_type !== 'stock') return null
    if (!marketDataCapabilitiesResolved.value) return 'resolving'
    if (marketDataRouteSelection.value.mode === 'unknown') return 'unknown'
    if (
      marketDataRouteSelection.value.mode === 'opendata_only'
      && !marketDataRouteSelection.value.can_query
    ) return 'opendata_unavailable'
    return null
  })

  const directKline = useMarketDataDirectKline({
    form,
    dateRange,
    selectedFamilyId,
    result,
    referenceSeriesResult,
    genericObservationResult,
    relatedTables,
    relatedTablesLoading,
    relatedTablesError,
    dataPageDisplayMode,
    openDataDirectKlineDisplay,
    instrumentAliasEffectiveOn,
    instrumentOptions,
    instrumentOptionsLoading,
    instrumentOptionsCatalogMode,
    marketDataCapabilitiesResolved,
    marketDataRouteSelection,
    requestState,
    formSymbolText: () => String(form.symbol || '').trim(),
    invalidateMarketDataQueryLifecycle: () => lookup.invalidateMarketDataQueryLifecycle(),
    resolveMarketDataCapabilities: () => lookup.resolveMarketDataCapabilities(),
  })

  const v2Query = useMarketDataV2Query({
    t,
    form,
    dateRange,
    selectedFamilyId,
    result,
    referenceSeriesResult,
    genericObservationResult,
    marketDataQueryBundle,
    marketDataPlatformStatus,
    invalidateMarketDataQueryLifecycle: () => lookup.invalidateMarketDataQueryLifecycle(),
    constrainDateRangeForFamily: (family, requestedDateRange) => (
      directKline.constrainDateRangeForFamily(family, requestedDateRange)
    ),
    throwIfMarketDataQueryAborted: (signal) => directKline.throwIfMarketDataQueryAborted(signal),
  })

  const presentation = useMarketDataPresentation({
    t,
    form,
    selectedFamilyId,
    result,
    snapshot,
    historyRows,
    referenceSeriesResult,
    genericObservationResult,
    marketDataQueryBundle,
    marketDataPlatformStatus,
    viewportWidth,
    coverageRows,
    coverageTimeframe,
    coverageProvider,
    relatedTables,
    relatedTablesError,
    currentAssetTab: () => lookup.currentAssetTab(),
    assetLabel: (assetType) => lookup.assetLabel(assetType),
    fieldLabel: (field) => catalog.fieldLabel(field),
    formatDetailValue: (field) => catalog.formatDetailValue(field),
    formatValuation: () => catalog.formatValuation(),
    shouldShowHistoryColumn: (field) => catalog.shouldShowHistoryColumn(field),
    metricCard: (labelKey, value, tone) => catalog.metricCard(labelKey, value, tone),
    buildAssetKpiCards: () => catalog.buildAssetKpiCards(),
    buildRangeStats: () => catalog.buildRangeStats(),
    buildCoverageRows: () => catalog.buildCoverageRows(),
    buildAssetDataFamilies: () => catalog.buildAssetDataFamilies(),
    selectedMarketPageFamilyFromQueryBundle: (bundle, assetType, familyId) => (
      v2Query.selectedMarketPageFamilyFromQueryBundle(bundle, assetType, familyId)
    ),
    isMarketPageSelectableFamily: (family, assetType) => (
      v2Query.isMarketPageSelectableFamily(family, assetType)
    ),
    marketPageFamilyLabel: (family) => v2Query.marketPageFamilyLabel(family),
  })

  const catalog = useMarketDataCatalog({
    t,
    router,
    form,
    requestState,
    result,
    snapshot,
    historyRows,
    coverageRows,
    coverageLoading,
    coverageRefreshing,
    coverageError,
    coverageTimeframe,
    coverageProvider,
    instrumentOptions,
    instrumentOptionsLoading,
    instrumentOptionsCatalogMode,
    instrumentOptionsError,
    instrumentAliasEffectiveOn,
    instrumentOptionsSearchTerm,
    relatedTables,
    relatedTablesLoading,
    relatedTablesError,
    selectedFamilyId,
    marketDataQueryBundle,
    marketDataPlatformStatus,
    marketDataRouteSelection,
    referenceSeriesResult,
    genericObservationResult,
    canReadOpenDataStockDailyFreshness,
    isFundNavReferenceSeries: presentation.isFundNavReferenceSeries,
    fundNavReferenceFields: presentation.fundNavReferenceFields,
    isLocalCoverageMatrixAllowed: () => lookup.isLocalCoverageMatrixAllowed(),
    clearLocalCoverageMatrix: () => lookup.clearLocalCoverageMatrix(),
    clearMarketDataQueryResults: () => directKline.clearMarketDataQueryResults(),
    setMarketDataPlatformErrorStatus: () => v2Query.setMarketDataPlatformErrorStatus(),
    resolveMarketDataCapabilities: () => lookup.resolveMarketDataCapabilities(),
    refreshOpenDataStockDailyFreshness,
    invalidateOpenDataStockDailyFreshnessRequest,
    isMarketPageSelectableFamily: (
      family: MarketDataQueryBundleFamily,
      assetType: MarketAssetType,
    ) => v2Query.isMarketPageSelectableFamily(family, assetType),
    lookupInstrument: (intent) => lookup.lookupInstrument(intent),
  })

  const lookup = useMarketDataLookup({
    t,
    form,
    dateRange,
    loading,
    result,
    dataPageDisplayMode,
    selectedFamilyId,
    selectedMarketPageFamily: presentation.selectedMarketPageFamily,
    isReferenceSeriesSelected: presentation.isReferenceSeriesSelected,
    isGenericObservationSelected: presentation.isGenericObservationSelected,
    instrumentOptions,
    instrumentOptionsCatalogMode,
    instrumentOptionsError,
    instrumentAliasEffectiveOn,
    instrumentOptionsSearchTerm,
    relatedTables,
    coverageRows,
    coverageLoading,
    coverageRefreshing,
    coverageError,
    marketDataPlatformStatus,
    marketDataQueryBundle,
    marketDataCapabilities,
    marketDataCapabilitiesResolved,
    marketDataRouteSelection,
    referenceSeriesResult,
    genericObservationResult,
    requestState,
    formSymbolText: catalog.formSymbolText,
    formMarketText: catalog.formMarketText,
    invalidateOpenDataDirectRequest: directKline.invalidateOpenDataDirectRequest,
    routeOpenDataDirectQuery: directKline.routeOpenDataDirectQuery,
    clearMarketDataQueryResults: directKline.clearMarketDataQueryResults,
    invalidateOpenDataStockDailyFreshnessRequest,
    clearMarketDataFamilyScopedState: v2Query.clearMarketDataFamilyScopedState,
    setMarketDataPlatformErrorStatus: v2Query.setMarketDataPlatformErrorStatus,
    setLegacyMarketDataPlatformStatus: v2Query.setLegacyMarketDataPlatformStatus,
    setMarketDataBundleUnconfiguredStatus: v2Query.setMarketDataBundleUnconfiguredStatus,
    setMarketDataBundlePeriodUnsupportedStatus: v2Query.setMarketDataBundlePeriodUnsupportedStatus,
    setV2MarketDataPlatformStatus: v2Query.setV2MarketDataPlatformStatus,
    constrainDateRangeForFamily: directKline.constrainDateRangeForFamily,
    queryContractForCurrentLookup: v2Query.queryContractForCurrentLookup,
    resolveV2QueryBundle: v2Query.resolveV2QueryBundle,
    resolveV2QueryContract: v2Query.resolveV2QueryContract,
    selectedMarketPageFamilyFromQueryBundle: v2Query.selectedMarketPageFamilyFromQueryBundle,
    lookupShellForV2Query: v2Query.lookupShellForV2Query,
    queryV2FromLookupContract: v2Query.queryV2FromLookupContract,
    loadInstrumentOptions: catalog.loadInstrumentOptions,
    loadRelatedTables: catalog.loadRelatedTables,
    loadInstrumentsThenLookup: catalog.loadInstrumentsThenLookup,
  })

  const chart = createMarketDataChartManager({
    t,
    dataPageDisplayMode,
    openDataDirectKlineDisplay,
    chartCanRender: presentation.chartCanRender,
    chartMode,
    marketChartRef,
    historyRows,
    ohlcHistoryRows: presentation.ohlcHistoryRows,
    hasOhlcChart: presentation.hasOhlcChart,
    viewportWidth,
  })

  onMounted(() => {
    const routeAssetType = routeTabMap[String(route.query.tab || '').toLowerCase()]
    if (routeAssetType) {
      lookup.applyAssetType(routeAssetType, false)
    } else {
      lookup.restoreAssetSelection(form.asset_type)
    }
    catalog.loadInstrumentsThenLookup()
    window.addEventListener('resize', chart.handleViewportResize)
  })

  onUnmounted(() => {
    requestState.marketPageBootstrapEpoch += 1
    directKline.invalidateOpenDataDirectRequest()
    invalidateOpenDataStockDailyFreshnessRequest()
    lookup.abortActiveMarketDataQueryLifecycle()
    window.removeEventListener('resize', chart.handleViewportResize)
    chart.disposeMarketChart()
  })

  watch(
    () => lookup.marketDataQuerySelectionKey(),
    (selectionKey) => {
      if (
        requestState.activeMarketDataQueryAbortController
        && requestState.activeMarketDataQuerySelectionKey !== selectionKey
      ) {
        lookup.invalidateMarketDataQueryLifecycle()
      }
    },
  )

  watch(
    () => [
      form.asset_type,
      catalog.formSymbolText(),
      form.period,
      selectedFamilyId.value,
      dateRange.value?.[0] || '',
      dateRange.value?.[1] || '',
      instrumentAliasEffectiveOn.value || '',
      instrumentOptionsCatalogMode.value || '',
      instrumentOptionsLoading.value,
      instrumentOptions.value,
    ],
    () => {
      if (dataPageDisplayMode.value === 'opendata_direct') {
        directKline.invalidateOpenDataDirectRequest()
      }
    },
    { flush: 'sync' },
  )

  watch(
    () => route.query.tab,
    (tab) => {
      if (lookup.applyRouteTab(tab, true)) {
        catalog.loadInstrumentsThenLookup()
      }
    },
  )

  watch(
    presentation.chartModeOptions,
    (options) => {
      if (!options.some((option) => option.value === chartMode.value)) {
        chartMode.value = options[0]?.value || 'price'
      }
    },
    { immediate: true },
  )

  watch(
    () => {
      const rows = historyRows.value
      const firstDate = rows[0]?.date || ''
      const lastDate = rows[rows.length - 1]?.date || ''
      return `${form.asset_type}:${result.value?.symbol || ''}:${chartMode.value}:${rows.length}:${firstDate}:${lastDate}`
    },
    () => {
      void nextTick(chart.renderMarketChart)
    },
    { flush: 'post' },
  )

  watch(
    () => {
      const display = openDataDirectKlineDisplay.value
      const firstDate = display.rows[0]?.date || ''
      const lastDate = display.rows[display.rows.length - 1]?.date || ''
      return `${dataPageDisplayMode.value}:${display.status}:${display.rows.length}:${firstDate}:${lastDate}`
    },
    () => {
      void nextTick(chart.renderMarketChart)
    },
    { flush: 'post' },
  )

  return {
    t,
    route,
    router,
    today,
    ninetyDaysAgo,
    assetTabs,
    assetDisplayConfigs,
    assetDataFamilySpecs,
    assetTableSearchKeywords,
    fieldLabelKeys,
    selectedFamilyId,
    routeTabMap,
    form,
    dateRange,
    loading,
    dataPageDisplayMode,
    openDataDirectKlineDisplay,
    openDataStockDailyFreshnessDisplay,
    canReadOpenDataStockDailyFreshness,
    openDataStockDailyFreshnessAvailability,
    stockDataRouteNotice,
    showLocalCoverageMatrix,
    result,
    chartMode,
    marketChartRef,
    instrumentOptions,
    instrumentOptionsLoading,
    instrumentOptionsCatalogMode,
    instrumentOptionsError,
    instrumentAliasEffectiveOn,
    relatedTablesLoading,
    relatedTables,
    relatedTablesError,
    coverageRows,
    coverageLoading,
    coverageRefreshing,
    coverageError,
    coverageTimeframe,
    coverageProvider,
    marketDataPlatformStatus,
    marketChart: chart.getMarketChart(),
    instrumentOptionsRequestId: requestState.instrumentOptionsRequestId,
    relatedTableRequestId: requestState.relatedTableRequestId,
    coverageRequestId: requestState.coverageRequestId,
    snapshot,
    historyRows,
    referenceSeriesResult,
    genericObservationResult,
    ...presentation,
    ...lookup,
    ...v2Query,
    ...catalog,
    ...chart,
    refreshOpenDataStockDailyFreshness,
    v2FrequencyForLegacyPeriod,
    queryWindowFromDateRange,
    referenceSeriesRowsFromV2Response,
    genericObservationResultFromV2Response,
    v2HistoryRows,
    v2EventTimeLabel,
    instrumentOptionLabel,
    instrumentOptionStatusTagType,
    toDateInput,
    capitalize,
    ohlcTuple,
    candleColor,
    formatReferenceSeriesField,
    referenceSeriesFieldTone,
    formatHistoryCell,
    formatGenericObservationCell,
    formatGenericObservationValue,
    formatPair,
    formatText,
    numericSeries,
    numericValue,
    isFiniteNumber,
    sumNumbers,
    averageNumbers,
    periodReturnPct,
    closeVolatilityPct,
    cumulativeReturns,
    drawdownSeries,
    formatNumber,
    formatPercent,
    coverageStatusTagType,
    formatCoverageRatio,
    toneClass,
    hasValue,
  }
}
