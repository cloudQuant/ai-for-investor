import type { ComputedRef, Ref } from 'vue'
import type { Router } from 'vue-router'
import { ElMessage } from 'element-plus'
import { akshareTablesApi } from '@/api/akshare'
import {
  marketDataApi,
  marketDataFamilyObservationShape,
  type MarketAssetType,
  type MarketDataQueryBundle,
  type MarketDataQueryBundleFamily,
  type MarketDataQueryBundleFamilyStatus,
  type MarketDataRouteSelection,
  type MarketHistoryRow,
  type MarketInstrumentLookupResponse,
  type MarketInstrumentOption,
} from '@/api/marketData'
import type { DataTable } from '@/types'
import type { MarketDataCoverageResponse } from '@/types/trust'
import {
  assetDataFamilySpecs,
  assetTableSearchKeywords,
  fieldLabelKeys,
} from './marketDataCatalogSpecs'
import {
  averageNumbers,
  buildRelatedTableKeywordsForAsset,
  capitalize,
  closeVolatilityPct,
  defaultFamilyIdForAsset,
  formatNumber,
  formatPair,
  formatPercent,
  formatReferenceSeriesField,
  formatText,
  hasValue,
  isFiniteNumber,
  isUsableReferenceSeriesValue,
  numericSeries,
  numericValue,
  periodLabelKey,
  periodReturnPct,
  referenceSeriesFieldTone,
  sameDeclaredFields,
  sumNumbers,
  toneClass,
} from './marketDataFormatters'
import type {
  CoverageRow,
  DataFamilyReadState,
  DataFamilySpec,
  DataFamilyView,
  DetailFieldSpec,
  GenericObservationResult,
  HistoryTableColumn,
  KpiCard,
  MarketDataPlatformStatus,
  MarketLookupIntent,
  RangeStat,
  ReferenceSeriesResult,
} from './marketDataTypes'

export interface MarketCatalogRequestState {
  instrumentOptionsRequestId: number
  relatedTableRequestId: number
  coverageRequestId: number
  marketPageBootstrapEpoch: number
}

export interface MarketDataCatalogDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  router: Router
  form: {
    asset_type: MarketAssetType
    symbol: string
    period: string
    market: string
  }
  requestState: MarketCatalogRequestState
  result: Ref<MarketInstrumentLookupResponse | null>
  snapshot: ComputedRef<Record<string, unknown>>
  historyRows: ComputedRef<MarketHistoryRow[]>
  coverageRows: Ref<MarketDataCoverageResponse[]>
  coverageLoading: Ref<boolean>
  coverageRefreshing: Ref<boolean>
  coverageError: Ref<string>
  coverageTimeframe: Ref<string>
  coverageProvider: Ref<string>
  instrumentOptions: Ref<MarketInstrumentOption[]>
  instrumentOptionsLoading: Ref<boolean>
  instrumentOptionsCatalogMode: Ref<'legacy' | 'opendata' | null>
  instrumentOptionsError: Ref<string>
  instrumentAliasEffectiveOn: Ref<string | null>
  instrumentOptionsSearchTerm: Ref<string>
  relatedTables: Ref<DataTable[]>
  relatedTablesLoading: Ref<boolean>
  relatedTablesError: Ref<string>
  selectedFamilyId: Ref<string>
  marketDataQueryBundle: Ref<MarketDataQueryBundle | null>
  marketDataPlatformStatus: Ref<MarketDataPlatformStatus>
  marketDataRouteSelection: Ref<MarketDataRouteSelection>
  referenceSeriesResult: Ref<ReferenceSeriesResult | null>
  genericObservationResult: Ref<GenericObservationResult | null>
  canReadOpenDataStockDailyFreshness: ComputedRef<boolean>
  isFundNavReferenceSeries: ComputedRef<boolean>
  fundNavReferenceFields: ComputedRef<string[]>
  isLocalCoverageMatrixAllowed: () => boolean
  clearLocalCoverageMatrix: () => void
  clearMarketDataQueryResults: () => void
  setMarketDataPlatformErrorStatus: () => void
  resolveMarketDataCapabilities: () => Promise<unknown>
  refreshOpenDataStockDailyFreshness: () => void
  invalidateOpenDataStockDailyFreshnessRequest: () => void
  isMarketPageSelectableFamily: (
    family: MarketDataQueryBundleFamily,
    assetType: MarketAssetType,
  ) => boolean
  lookupInstrument: (intent?: MarketLookupIntent) => Promise<void>
}

export function useMarketDataCatalog(deps: MarketDataCatalogDeps) {
  function formSymbolText() {
    return String(deps.form.symbol || '').trim()
  }

  function formMarketText() {
    return String(deps.form.market || '').trim()
  }

  function formatValuation() {
    const snap = deps.snapshot.value
    if (!hasValue(snap.pe) && !hasValue(snap.pb)) return '-'
    return `PE ${formatNumber(snap.pe)} / PB ${formatNumber(snap.pb)}`
  }

  function bidAskSpread() {
    const snap = deps.snapshot.value
    const bid = Number(snap.bid)
    const ask = Number(snap.ask)
    if (!Number.isFinite(bid) || !Number.isFinite(ask)) return null
    return ask - bid
  }

  function totalHistoryField(field: string) {
    const total = deps.historyRows.value.reduce((sum, row) => {
      const value = Number(row[field])
      return Number.isFinite(value) ? sum + value : sum
    }, 0)
    return total || null
  }

  function hasHistoryValue(field: string) {
    return deps.historyRows.value.some((row) => hasValue(row[field]))
  }

  function shouldShowHistoryColumn(field: string) {
    if (!deps.historyRows.value.length) return true
    return hasHistoryValue(field)
  }

  function coverageStatusLabel(status: string) {
    const labels: Record<string, string> = {
      pass: deps.t('dataMgmt.coveragePassed'),
      warning: deps.t('dataMgmt.coverageWarning'),
      failed: deps.t('dataMgmt.coverageFailed'),
      unknown: deps.t('dataMgmt.coverageUnknown'),
    }
    return labels[status] || status
  }

  function coverageDateRange(row: MarketDataCoverageResponse) {
    const start = row.start_date || '-'
    const end = row.end_date || '-'
    return deps.t('dataMgmt.coverageDateRange', { start, end })
  }

  function formatInstrumentHistoryStatus(option: MarketInstrumentOption) {
    if (
      option.data_availability === 'unknown'
      || option.has_history == null
      || option.history_rows == null
    ) {
      return deps.t('dataMgmt.coverageUnknown')
    }
    return option.has_history ? formatNumber(option.history_rows) : '0'
  }

  function openDataInstrumentReferenceError(error: unknown) {
    if (!error || typeof error !== 'object') return null
    const response = (error as { response?: { data?: unknown } }).response
    const data = response?.data
    if (!data || typeof data !== 'object') return null
    const detail = (data as { detail?: unknown }).detail
    if (!detail || typeof detail !== 'object') return null
    const payload = detail as { catalog_mode?: unknown; code?: unknown }
    if (payload.catalog_mode !== 'opendata') return null
    return payload.code === 'OPENDATA_REFERENCE_EFFECTIVE_DATE_REQUIRED'
      ? 'effective_date_required'
      : 'unavailable'
  }

  function ensureCurrentInstrumentOption(options: MarketInstrumentOption[]) {
    const currentSymbol = formSymbolText()
    if (!currentSymbol) return options
    if (options.some((option) => option.symbol === currentSymbol)) return options
    return [
      {
        asset_type: deps.form.asset_type,
        symbol: currentSymbol,
        name: currentSymbol,
        market: deps.form.asset_type === 'futures' ? formMarketText() || 'CF' : undefined,
        source_table: null,
        latest_date: null,
        has_snapshot: false,
        has_history: false,
        history_rows: 0,
      },
      ...options,
    ]
  }

  function adoptFirstInstrumentOption(items: MarketInstrumentOption[]) {
    if (deps.form.asset_type !== 'option') return
    const currentSymbol = formSymbolText()
    if (items.some((item) => item.symbol === currentSymbol)) return
    const first = items.find((item) => Boolean(item.symbol))
    if (!first) return
    deps.form.symbol = first.symbol
  }

  async function loadCoverageMatrix() {
    if (!deps.isLocalCoverageMatrixAllowed()) {
      deps.clearLocalCoverageMatrix()
      return
    }
    const requestId = ++deps.requestState.coverageRequestId
    const requestAssetType = deps.form.asset_type
    deps.coverageLoading.value = true
    deps.coverageError.value = ''
    try {
      const response = await marketDataApi.listCoverage({
        asset_type: deps.form.asset_type,
        timeframe: deps.coverageTimeframe.value || undefined,
        provider: deps.coverageProvider.value.trim() || undefined,
        limit: 200,
      })
      if (
        requestId !== deps.requestState.coverageRequestId
        || requestAssetType !== deps.form.asset_type
        || !deps.isLocalCoverageMatrixAllowed()
      ) return
      deps.coverageRows.value = response.items
    } catch {
      if (
        requestId === deps.requestState.coverageRequestId
        && requestAssetType === deps.form.asset_type
        && deps.isLocalCoverageMatrixAllowed()
      ) {
        deps.coverageRows.value = []
        deps.coverageError.value = deps.t('dataMgmt.coverageLoadFailed')
      }
    } finally {
      if (requestId === deps.requestState.coverageRequestId) {
        deps.coverageLoading.value = false
      }
    }
  }

  async function refreshCoverageMatrix() {
    if (!deps.isLocalCoverageMatrixAllowed()) {
      deps.clearLocalCoverageMatrix()
      return
    }
    const requestId = ++deps.requestState.coverageRequestId
    const requestAssetType = deps.form.asset_type
    deps.coverageRefreshing.value = true
    deps.coverageError.value = ''
    try {
      const response = await marketDataApi.refreshWarehouseCoverage({
        asset_type: deps.form.asset_type,
        timeframe: deps.coverageTimeframe.value || undefined,
        limit: 500,
      })
      if (
        requestId !== deps.requestState.coverageRequestId
        || requestAssetType !== deps.form.asset_type
        || !deps.isLocalCoverageMatrixAllowed()
      ) return
      deps.coverageRows.value = response.items
      ElMessage.success(deps.t('dataMgmt.coverageRefreshed'))
    } catch {
      if (
        requestId === deps.requestState.coverageRequestId
        && requestAssetType === deps.form.asset_type
        && deps.isLocalCoverageMatrixAllowed()
      ) {
        deps.coverageError.value = deps.t('dataMgmt.coverageRefreshFailed')
        ElMessage.error(deps.coverageError.value)
      }
    } finally {
      if (requestId === deps.requestState.coverageRequestId) deps.coverageRefreshing.value = false
    }
  }

  async function loadInstrumentOptions(search = '', adoptFirstOnMiss = false) {
    const requestId = ++deps.requestState.instrumentOptionsRequestId
    const normalizedSearch = String(search || '').trim()
    deps.instrumentOptionsSearchTerm.value = normalizedSearch
    deps.instrumentOptionsLoading.value = true
    deps.instrumentOptionsError.value = ''
    try {
      const params = {
        asset_type: deps.form.asset_type,
        search: normalizedSearch,
        limit: 80,
        ...(deps.form.asset_type === 'stock'
          && deps.instrumentOptionsCatalogMode.value === 'opendata'
          && deps.instrumentAliasEffectiveOn.value
          ? { effective_on: deps.instrumentAliasEffectiveOn.value }
          : {}),
      }
      const response = await marketDataApi.listInstrumentOptions({ ...params })
      if (requestId !== deps.requestState.instrumentOptionsRequestId) return
      const isOpenDataCatalog = response.catalog_mode === 'opendata'
      deps.instrumentOptionsCatalogMode.value = isOpenDataCatalog ? 'opendata' : 'legacy'
      const responseItems = Array.isArray(response.items) ? response.items : []
      if (isOpenDataCatalog) {
        const verifiedItems = responseItems.filter((item) => item.catalog_verified === true)
        deps.instrumentOptions.value = verifiedItems
        const currentSymbol = deps.form.asset_type === 'stock' ? formSymbolText() : ''
        if (currentSymbol && !verifiedItems.some((item) => item.symbol === currentSymbol)) {
          deps.clearMarketDataQueryResults()
          deps.setMarketDataPlatformErrorStatus()
          deps.instrumentOptionsError.value = '当前目录结果不包含所选标的，请从已验证的 OpenData 目录中重新选择。'
        }
      } else {
        deps.instrumentOptions.value = ensureCurrentInstrumentOption(responseItems)
      }
      if (adoptFirstOnMiss && !isOpenDataCatalog) adoptFirstInstrumentOption(responseItems)
    } catch (error) {
      if (requestId === deps.requestState.instrumentOptionsRequestId) {
        const openDataError = openDataInstrumentReferenceError(error)
        if (openDataError || deps.instrumentOptionsCatalogMode.value === 'opendata') {
          deps.instrumentOptionsCatalogMode.value = 'opendata'
          deps.instrumentOptions.value = []
          deps.clearMarketDataQueryResults()
          deps.setMarketDataPlatformErrorStatus()
          deps.instrumentOptionsError.value = openDataError === 'effective_date_required'
            ? '历史简称查询需要先选择生效日期后重试。'
            : deps.t('dataMgmt.marketDataSourceError')
        } else if (deps.form.asset_type === 'stock') {
          deps.instrumentOptionsCatalogMode.value = null
          deps.instrumentOptionsError.value = deps.t('dataMgmt.marketDataSourceError')
          deps.instrumentOptions.value = []
        } else {
          deps.instrumentOptionsCatalogMode.value = 'legacy'
          deps.instrumentOptionsError.value = ''
          deps.instrumentOptions.value = ensureCurrentInstrumentOption([])
        }
      }
    } finally {
      if (requestId === deps.requestState.instrumentOptionsRequestId) {
        deps.instrumentOptionsLoading.value = false
      }
    }
  }

  function searchInstrumentOptions(query: string) {
    deps.instrumentOptionsSearchTerm.value = String(query || '')
    void loadInstrumentOptions(query)
  }

  function handleInstrumentDropdownVisible(visible: boolean) {
    if (visible && !deps.instrumentOptions.value.length) {
      void loadInstrumentOptions(formSymbolText())
    }
  }

  function handleInstrumentAliasEffectiveDateChange() {
    void loadInstrumentOptions(deps.instrumentOptionsSearchTerm.value)
  }

  function loadInstrumentsThenLookup(): void {
    const bootstrapId = ++deps.requestState.marketPageBootstrapEpoch
    if (deps.form.asset_type !== 'option') {
      if (deps.form.asset_type === 'stock') {
        const requestedSymbol = formSymbolText()
        void (async () => {
          await deps.resolveMarketDataCapabilities()
          if (
            bootstrapId !== deps.requestState.marketPageBootstrapEpoch
            || deps.form.asset_type !== 'stock'
            || formSymbolText() !== requestedSymbol
          ) return

          if (deps.marketDataRouteSelection.value.mode === 'legacy') {
            void loadCoverageMatrix()
            deps.invalidateOpenDataStockDailyFreshnessRequest()
          } else {
            deps.clearLocalCoverageMatrix()
            if (deps.canReadOpenDataStockDailyFreshness.value) {
              deps.refreshOpenDataStockDailyFreshness()
            } else {
              deps.invalidateOpenDataStockDailyFreshnessRequest()
            }
          }

          await loadInstrumentOptions(requestedSymbol)
          if (
            bootstrapId !== deps.requestState.marketPageBootstrapEpoch
            || deps.form.asset_type !== 'stock'
            || formSymbolText() !== requestedSymbol
          ) return
          if (deps.marketDataRouteSelection.value.mode === 'legacy') {
            await deps.lookupInstrument('local_only')
          }
        })()
        return
      }
      void loadInstrumentOptions(formSymbolText())
      void loadCoverageMatrix()
      void deps.lookupInstrument('local_only')
      return
    }
    void (async () => {
      await loadInstrumentOptions(formSymbolText(), true)
      if (bootstrapId !== deps.requestState.marketPageBootstrapEpoch || deps.form.asset_type !== 'option') {
        return
      }
      void loadCoverageMatrix()
      if (formSymbolText()) await deps.lookupInstrument('local_only')
    })()
  }

  function buildRelatedTableKeywords(lookupResult: MarketInstrumentLookupResponse | null) {
    return buildRelatedTableKeywordsForAsset(
      deps.form.asset_type,
      lookupResult?.symbol || deps.form.symbol,
      assetTableSearchKeywords,
      assetDataFamilySpecs[deps.form.asset_type].map((family) => family.tableKeywords),
    )
  }

  function relatedTableScore(table: DataTable) {
    const haystack = `${table.table_name} ${table.table_comment || ''} ${table.script_id || ''}`.toLowerCase()
    const assetKeywords = assetTableSearchKeywords[deps.form.asset_type]
    const keywordScore = assetKeywords.reduce(
      (score, keyword) => score + (haystack.includes(keyword.toLowerCase()) ? 10 : 0),
      0,
    )
    const symbol = (deps.result.value?.symbol || deps.form.symbol || '').replace(/[^A-Za-z0-9]+/g, '').toLowerCase()
    const symbolScore = symbol && haystack.includes(symbol) ? 18 : 0
    const rowScore = Math.min(Math.log10(Math.max(table.row_count || 0, 1)), 8)
    return keywordScore + symbolScore + rowScore
  }

  async function loadRelatedTables(
    lookupResult: MarketInstrumentLookupResponse | null = deps.result.value,
  ) {
    const requestId = ++deps.requestState.relatedTableRequestId
    const keywords = buildRelatedTableKeywords(lookupResult)
    deps.relatedTablesLoading.value = true
    deps.relatedTablesError.value = ''

    try {
      const responses = await Promise.allSettled(
        keywords.map((keyword) => akshareTablesApi.list({
          search: keyword,
          page: 1,
          page_size: 8,
        })),
      )
      if (requestId !== deps.requestState.relatedTableRequestId) return

      const tableMap = new Map<number, DataTable>()
      responses.forEach((response) => {
        if (response.status !== 'fulfilled') return
        response.value.items.forEach((table) => tableMap.set(table.id, table))
      })
      deps.relatedTables.value = Array.from(tableMap.values())
        .sort((left, right) => relatedTableScore(right) - relatedTableScore(left))
        .slice(0, 12)

      if (responses.every((response) => response.status === 'rejected')) {
        deps.relatedTablesError.value = deps.t('dataMgmt.relatedTablesLoadFailed')
      }
    } catch {
      if (requestId === deps.requestState.relatedTableRequestId) {
        deps.relatedTables.value = []
        deps.relatedTablesError.value = deps.t('dataMgmt.relatedTablesLoadFailed')
      }
    } finally {
      if (requestId === deps.requestState.relatedTableRequestId) {
        deps.relatedTablesLoading.value = false
      }
    }
  }

  function goTableDetail(tableId: number) {
    void deps.router.push({ name: 'DataTableDetail', params: { id: tableId } })
  }

  function statRow(labelKey: string, value: string, tone = ''): RangeStat {
    return { label: deps.t(labelKey), value, tone }
  }

  function buildRangeStats(): RangeStat[] {
    const rows = deps.historyRows.value
    if (!rows.length) {
      return [
        statRow('dataMgmt.metricHigh', '-'),
        statRow('dataMgmt.metricLow', '-'),
        statRow('dataMgmt.metricReturn', '-'),
        statRow('dataMgmt.metricAvgVolume', '-'),
      ]
    }
    const closes = numericSeries(rows, 'close')
    const highs = numericSeries(rows, 'high')
    const lows = numericSeries(rows, 'low')
    const volumes = numericSeries(rows, 'volume')
    const turnovers = numericSeries(rows, 'turnover')
    const openInterests = numericSeries(rows, 'open_interest')
    const changes = numericSeries(rows, 'change')
    const returnPct = deps.result.value?.indicators.return_pct ?? periodReturnPct(closes)
    const volatility = closeVolatilityPct(closes)

    if (!closes.length && openInterests.length) {
      return [
        statRow('dataMgmt.metricCmeOpenInterest', formatNumber(sumNumbers(openInterests))),
        statRow('dataMgmt.metric24hVolume', formatNumber(sumNumbers(volumes))),
        statRow('dataMgmt.colChangeValue', formatNumber(sumNumbers(changes)), toneClass(sumNumbers(changes))),
        statRow('dataMgmt.metricSampleCount', formatNumber(rows.length)),
      ]
    }

    return [
      statRow('dataMgmt.metricHigh', formatNumber(highs.length ? Math.max(...highs) : deps.result.value?.indicators.highest_close)),
      statRow('dataMgmt.metricLow', formatNumber(lows.length ? Math.min(...lows) : deps.result.value?.indicators.lowest_close)),
      statRow('dataMgmt.metricReturn', formatPercent(returnPct), toneClass(returnPct)),
      statRow('dataMgmt.metricVolatility', formatPercent(volatility)),
      statRow('dataMgmt.metricAvgVolume', formatNumber(averageNumbers(volumes) ?? deps.result.value?.indicators.avg_volume)),
      statRow('dataMgmt.fieldTurnover', formatNumber(sumNumbers(turnovers) || deps.snapshot.value.turnover)),
    ]
  }

  function coverageRow(labelKey: string, available: number, total: number): CoverageRow {
    return {
      label: deps.t(labelKey),
      value: `${available}/${total}`,
      coverage: total ? Math.round((available / total) * 100) : 0,
    }
  }

  function countSnapshotFields(fields: string[]) {
    return fields.filter((field) => hasValue(deps.snapshot.value[field])).length
  }

  function countHistoryFields(fields: string[]) {
    return fields.filter((field) => hasHistoryValue(field)).length
  }

  function countAvailableAssetFields(fields: string[]) {
    return fields.filter((field) => hasValue(deps.snapshot.value[field]) || hasHistoryValue(field)).length
  }

  function buildCoverageRows(): CoverageRow[] {
    const snapshotFields = ['price', 'change_pct', 'open', 'high', 'low', 'volume', 'turnover', 'bid', 'ask']
    const historyFields = ['open', 'high', 'low', 'close', 'volume', 'turnover', 'change_pct', 'open_interest']
    const assetFields = assetDataFamilySpecs[deps.form.asset_type].flatMap((family) => [
      ...family.fields,
      ...(family.historyFields || []),
    ])
    const uniqueAssetFields = Array.from(new Set(assetFields))

    return [
      coverageRow('dataMgmt.coverageSnapshot', countSnapshotFields(snapshotFields), snapshotFields.length),
      coverageRow('dataMgmt.coverageHistory', countHistoryFields(historyFields), historyFields.length),
      coverageRow('dataMgmt.coverageAssetSpecific', countAvailableAssetFields(uniqueAssetFields), uniqueAssetFields.length),
      {
        label: deps.t('dataMgmt.coverageWarehouse'),
        value: deps.t('dataMgmt.coverageTablesValue', { count: deps.relatedTables.value.length }),
        coverage: Math.min(100, deps.relatedTables.value.length * 20),
      },
    ]
  }

  function fieldLabel(field: string) {
    const labelKey = fieldLabelKeys[field]
    return labelKey ? deps.t(labelKey) : field
  }

  function metricCard(labelKey: string, value: string, tone = ''): KpiCard {
    return { label: deps.t(labelKey), value, tone }
  }

  function buildAssetKpiCards(): KpiCard[] {
    const snap = deps.snapshot.value
    if (deps.isFundNavReferenceSeries.value) {
      return deps.fundNavReferenceFields.value.map((field) => ({
        label: fieldLabel(field),
        value: formatReferenceSeriesField(field, snap[field]),
        tone: referenceSeriesFieldTone(field, snap[field]),
      }))
    }
    const latestPrice = snap.price ?? deps.result.value?.indicators.latest_close
    const periodReturn = deps.result.value?.indicators.return_pct ?? snap.change_pct
    const cardsByAsset: Record<MarketAssetType, KpiCard[]> = {
      stock: [
        metricCard('dataMgmt.fieldPrice', formatNumber(latestPrice)),
        metricCard('dataMgmt.metricReturn', formatPercent(periodReturn), toneClass(periodReturn)),
        metricCard('dataMgmt.fieldTurnover', formatNumber(snap.turnover)),
        metricCard('dataMgmt.metricPePb', formatValuation()),
      ],
      futures: [
        metricCard('dataMgmt.fieldPrice', formatNumber(latestPrice)),
        metricCard('dataMgmt.fieldOpenInterest', formatNumber(snap.open_interest)),
        metricCard('dataMgmt.fieldSettle', formatNumber(snap.settle)),
        metricCard('dataMgmt.metricBidAskSpread', formatNumber(bidAskSpread())),
      ],
      bond: [
        metricCard('dataMgmt.fieldPrice', formatNumber(latestPrice)),
        metricCard('dataMgmt.colChange', formatPercent(snap.change_pct), toneClass(snap.change_pct)),
        metricCard('dataMgmt.fieldTurnover', formatNumber(snap.turnover)),
        metricCard('dataMgmt.fieldBidAsk', formatPair(snap.bid, snap.ask)),
      ],
      fund: [
        metricCard('dataMgmt.fieldPrice', formatNumber(latestPrice)),
        metricCard('dataMgmt.colChange', formatPercent(periodReturn), toneClass(periodReturn)),
        metricCard('dataMgmt.fieldTurnover', formatNumber(snap.turnover)),
        metricCard('dataMgmt.metricAvgVolume', formatNumber(deps.result.value?.indicators.avg_volume)),
      ],
      option: [
        metricCard('dataMgmt.metricPremium', formatNumber(latestPrice)),
        metricCard('dataMgmt.colChangeValue', formatNumber(snap.change), toneClass(snap.change)),
        metricCard('dataMgmt.colChange', formatPercent(periodReturn), toneClass(periodReturn)),
        metricCard('dataMgmt.metricSampleCount', formatNumber(deps.result.value?.indicators.observation_count)),
      ],
      fx: [
        metricCard('dataMgmt.fieldPrice', formatNumber(latestPrice)),
        metricCard('dataMgmt.colChange', formatPercent(periodReturn), toneClass(periodReturn)),
        metricCard('dataMgmt.fieldHighLow', formatPair(snap.high, snap.low)),
        metricCard('dataMgmt.fieldPreviousClose', formatNumber(snap.previous_close)),
      ],
      crypto: [
        metricCard('dataMgmt.fieldPrice', formatNumber(latestPrice)),
        metricCard('dataMgmt.colChange', formatPercent(snap.change_pct), toneClass(snap.change_pct)),
        metricCard('dataMgmt.metric24hVolume', formatNumber(snap.volume)),
        metricCard('dataMgmt.metricCmeOpenInterest', formatNumber(totalHistoryField('open_interest'))),
      ],
    }
    return cardsByAsset[deps.form.asset_type]
  }

  function formatDetailValue(field: DetailFieldSpec) {
    const snap = deps.snapshot.value
    const [firstField, secondField] = field.fields
    if (field.format === 'percent') return formatPercent(snap[firstField])
    if (field.format === 'text') return formatText(snap[firstField])
    if (field.format === 'pair') return formatPair(snap[firstField], snap[secondField])
    if (field.format === 'bidAsk') return formatPair(snap.bid, snap.ask)
    if (field.format === 'valuation') return formatValuation()
    return formatNumber(snap[firstField])
  }

  function dataFamilyBundleStatusLabel(
    status: MarketDataQueryBundleFamilyStatus,
    reasonCode: string | null,
  ): string {
    const label = status === 'ready'
      ? deps.t('dataMgmt.dataFamilyStatusReady')
      : status === 'not_applicable'
        ? deps.t('dataMgmt.dataFamilyStatusNotApplicable')
        : deps.t('dataMgmt.dataFamilyStatusUnconfigured')
    return reasonCode ? `${label} · ${reasonCode}` : label
  }

  function dataFamilyBundleTagType(status: MarketDataQueryBundleFamilyStatus): DataFamilyView['tagType'] {
    if (status === 'ready') return 'success'
    if (status === 'unconfigured') return 'warning'
    return 'info'
  }

  function declaredFamilyFields(family: MarketDataQueryBundleFamily): string[] {
    return Array.from(new Set([
      ...family.required_fields,
      ...family.optional_fields,
      ...family.dimension_fields,
    ]))
  }

  function declaredKlineCompatibilityLabel(family: MarketDataQueryBundleFamily): string {
    const declaredCadences = family.frequencies.map((frequency) => deps.t(periodLabelKey(frequency)))
    return deps.t('dataMgmt.klineCompatibilityLabel', { cadences: declaredCadences.join('/') })
  }

  function dataFamilyBundleDescription(family: MarketDataQueryBundleFamily): string {
    const declaredFields = declaredFamilyFields(family).map(fieldLabel)
    const fieldsLabel = declaredFields.length
      ? declaredFields.join(' / ')
      : deps.t('dataMgmt.dataFamilyNoDeclaredFields')
    return deps.t('dataMgmt.dataFamilyBundleDescription', {
      datasetCode: family.dataset_code,
      frequencySemantics: family.frequency_semantics,
      fields: fieldsLabel,
    })
  }

  function isCurrentPageExecutableFamily(family: MarketDataQueryBundleFamily): boolean {
    return family.family_id === deps.selectedFamilyId.value
      && deps.isMarketPageSelectableFamily(family, deps.form.asset_type)
  }

  function hasRequiredFactRows(family: MarketDataQueryBundleFamily): boolean {
    if (family.data_kind === 'reference_series') {
      const presentation = deps.referenceSeriesResult.value
      return Boolean(
        presentation
        && presentation.familyId === family.family_id
        && sameDeclaredFields(presentation.requiredFields, family.required_fields)
        && presentation.rows.some((row) => (
          family.required_fields.every((field) => isUsableReferenceSeriesValue(row[field]))
        )),
      )
    }
    if (family.data_kind !== 'bars') {
      const presentation = deps.genericObservationResult.value
      return Boolean(
        presentation
        && presentation.familyId === family.family_id
        && sameDeclaredFields(presentation.requiredFields, family.required_fields)
        && sameDeclaredFields(presentation.dimensionFields, family.dimension_fields)
        && presentation.observations.some((observation) => (
          observation.quality === 'pass'
          && [...family.dimension_fields, ...family.required_fields]
            .every((field) => isUsableReferenceSeriesValue(observation.fields[field]))
        )),
      )
    }
    return deps.historyRows.value.some((row) => (
      family.required_fields.every((field) => isFiniteNumber(numericValue(row[field], null)))
    ))
  }

  function hasDeclaredFactValue(family: MarketDataQueryBundleFamily, field: string): boolean {
    if (family.data_kind !== 'bars' && family.data_kind !== 'reference_series') {
      const presentation = deps.genericObservationResult.value
      return Boolean(
        presentation
        && presentation.familyId === family.family_id
        && sameDeclaredFields(presentation.dimensionFields, family.dimension_fields)
        && presentation.observations.some((observation) => (
          observation.quality === 'pass' && isUsableReferenceSeriesValue(observation.fields[field])
        )),
      )
    }
    return hasValue(deps.snapshot.value[field]) || hasHistoryValue(field)
  }

  function hasActiveV2FactsForFamily(family: MarketDataQueryBundleFamily): boolean {
    const status = deps.marketDataPlatformStatus.value
    const contract = deps.result.value?.query_contract
    return (
      (
        status.path === 'local_only'
        || status.path === 'local_first'
        || status.path === 'provider_persisted'
      )
      && status.familyId === family.family_id
      && deps.result.value?.asset_type === deps.form.asset_type
      && contract?.request.family_id === family.family_id
      && contract.request.family_contract_version === family.family_contract_version
      && hasRequiredFactRows(family)
    )
  }

  function dataFamilyReadState(family: MarketDataQueryBundleFamily): DataFamilyReadState {
    if (family.status === 'unconfigured') return 'unconfigured'
    if (family.status === 'not_applicable') return 'not_applicable'
    if (!deps.isMarketPageSelectableFamily(family, deps.form.asset_type)) return 'control_plane_only'
    if (isCurrentPageExecutableFamily(family) && hasActiveV2FactsForFamily(family)) {
      return 'facts_loaded'
    }
    if (family.data_kind === 'bars') return 'bars_query_available'
    if (family.data_kind === 'reference_series') return 'reference_series_query_available'
    return 'generic_query_available'
  }

  function dataFamilyReadStateLabel(readState: DataFamilyReadState): string {
    if (readState === 'facts_loaded') return deps.t('dataMgmt.dataFamilyReadStateFactsLoaded')
    if (readState === 'bars_query_available') return deps.t('dataMgmt.dataFamilyReadStateBarsQueryAvailable')
    if (readState === 'reference_series_query_available') {
      return deps.t('dataMgmt.dataFamilyReadStateReferenceSeriesQueryAvailable')
    }
    if (readState === 'generic_query_available') return deps.t('dataMgmt.dataFamilyReadStateGenericQueryAvailable')
    if (readState === 'control_plane_only') return deps.t('dataMgmt.dataFamilyReadStateControlPlaneOnly')
    if (readState === 'unconfigured') return deps.t('dataMgmt.dataFamilyReadStateUnconfigured')
    return deps.t('dataMgmt.dataFamilyReadStateNotApplicable')
  }

  function dataFamilySpecForCurrentAsset(familyId: string): DataFamilySpec | null {
    return assetDataFamilySpecs[deps.form.asset_type].find((family) => family.familyId === familyId) || null
  }

  function buildIssuedDataFamilyView(
    family: MarketDataQueryBundleFamily,
    familySpec: DataFamilySpec | null,
  ): DataFamilyView {
    const readState = dataFamilyReadState(family)
    const hasActiveFacts = readState === 'facts_loaded'
    const fields = declaredFamilyFields(family).map((field) => ({
      name: field,
      label: fieldLabel(field),
      present: hasActiveFacts && hasDeclaredFactValue(family, field),
    }))
    return {
      familyId: family.family_id,
      label: family.family_id === defaultFamilyIdForAsset(deps.form.asset_type)
        && family.data_kind === 'bars'
        ? declaredKlineCompatibilityLabel(family)
        : familySpec
          ? deps.t(familySpec.labelKey)
          : family.family_id,
      description: dataFamilyBundleDescription(family),
      statusLabel: dataFamilyBundleStatusLabel(family.status, family.reason_code),
      tagType: dataFamilyBundleTagType(family.status),
      contract: {
        dataKind: family.data_kind,
        frequencySemantics: family.frequency_semantics,
        coverageModel: family.coverage_model,
        observationShape: marketDataFamilyObservationShape(family),
      },
      readState,
      readStatusLabel: dataFamilyReadStateLabel(readState),
      fields,
    }
  }

  function buildMissingIssuedDataFamilyView(family: DataFamilySpec): DataFamilyView {
    return {
      familyId: family.familyId,
      label: deps.t(family.labelKey),
      description: deps.t('dataMgmt.dataFamilyMissingDescription'),
      statusLabel: deps.t('dataMgmt.dataFamilyMissingStatus'),
      tagType: 'warning',
      contract: null,
      readState: 'unconfigured',
      readStatusLabel: dataFamilyReadStateLabel('unconfigured'),
      fields: Array.from(new Set([...family.fields, ...(family.historyFields || [])])).map((field) => ({
        name: field,
        label: fieldLabel(field),
        present: false,
      })),
    }
  }

  function countMatchingTables(keywords: string[]) {
    return deps.relatedTables.value.filter((table) => {
      const haystack = `${table.table_name} ${table.table_comment || ''} ${table.script_id || ''}`.toLowerCase()
      return keywords.some((keyword) => haystack.includes(keyword.toLowerCase()))
    }).length
  }

  function buildAssetDataFamilies(): DataFamilyView[] {
    const bundle = deps.marketDataQueryBundle.value
    if (bundle?.requested_asset_type === deps.form.asset_type) {
      const knownSpecs = assetDataFamilySpecs[deps.form.asset_type]
      const issuedById = new Map(bundle.families.map((family) => [family.family_id, family]))
      const knownFamilyIds = new Set(knownSpecs.map((family) => family.familyId))
      const knownFamilyViews = knownSpecs.map((family) => {
        const issuedFamily = issuedById.get(family.familyId)
        return issuedFamily
          ? buildIssuedDataFamilyView(issuedFamily, family)
          : buildMissingIssuedDataFamilyView(family)
      })
      const additionalFamilyViews = bundle.families
        .filter((family) => !knownFamilyIds.has(family.family_id))
        .map((family) => buildIssuedDataFamilyView(family, dataFamilySpecForCurrentAsset(family.family_id)))
      return [...knownFamilyViews, ...additionalFamilyViews]
    }
    return assetDataFamilySpecs[deps.form.asset_type].map((family) => {
      const fields = Array.from(new Set([...family.fields, ...(family.historyFields || [])])).map((field) => ({
        name: field,
        label: fieldLabel(field),
        present: hasValue(deps.snapshot.value[field]) || hasHistoryValue(field),
      }))
      const presentFields = fields.filter((field) => field.present).length
      const relatedTableCount = countMatchingTables(family.tableKeywords)
      const denominator = fields.length + 1
      const score = presentFields + (relatedTableCount ? 1 : 0)
      const status = score >= Math.ceil(denominator * 0.72) ? 'available' : score > 0 ? 'partial' : 'missing'
      return {
        familyId: family.familyId,
        label: deps.t(family.labelKey),
        description: deps.t(family.descKey, { count: relatedTableCount }),
        statusLabel: deps.t(`dataMgmt.familyStatus${capitalize(status)}`),
        tagType: status === 'available' ? 'success' : status === 'partial' ? 'warning' : 'info',
        contract: null,
        readState: null,
        readStatusLabel: null,
        fields,
      }
    })
  }

  function hasRequiredHistoryColumn(_column: HistoryTableColumn) {
    return shouldShowHistoryColumn(_column.key)
  }

  return {
    formSymbolText,
    formMarketText,
    formatValuation,
    bidAskSpread,
    totalHistoryField,
    hasHistoryValue,
    shouldShowHistoryColumn,
    hasRequiredHistoryColumn,
    coverageStatusLabel,
    coverageDateRange,
    formatInstrumentHistoryStatus,
    ensureCurrentInstrumentOption,
    adoptFirstInstrumentOption,
    loadCoverageMatrix,
    refreshCoverageMatrix,
    loadInstrumentOptions,
    searchInstrumentOptions,
    handleInstrumentDropdownVisible,
    handleInstrumentAliasEffectiveDateChange,
    loadInstrumentsThenLookup,
    buildRelatedTableKeywords,
    relatedTableScore,
    loadRelatedTables,
    goTableDetail,
    statRow,
    buildRangeStats,
    coverageRow,
    countSnapshotFields,
    countHistoryFields,
    countAvailableAssetFields,
    buildCoverageRows,
    fieldLabel,
    metricCard,
    buildAssetKpiCards,
    formatDetailValue,
    buildAssetDataFamilies,
    countMatchingTables,
  }
}
