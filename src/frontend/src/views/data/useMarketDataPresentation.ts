import { computed, type Component, type ComputedRef, type Ref } from 'vue'
import type {
  MarketAssetType,
  MarketDataQueryBundle,
  MarketDataQueryBundleFamily,
  MarketHistoryRow,
  MarketInstrumentLookupResponse,
} from '@/api/marketData'
import type { DataTable } from '@/types'
import type { MarketDataCoverageResponse } from '@/types/trust'
import { assetDisplayConfigs, basePeriods } from './marketDataCatalogSpecs'
import {
  formatGenericObservationValue,
  formatNumber,
  formatPair,
  formatPercent,
  formatReferenceSeriesField,
  formatText,
  hasValue,
  historyRowTimestamp,
  isFiniteNumber,
  marketPagePeriodForV2Frequency,
  numericValue,
  periodLabelKey,
  referenceSeriesFieldTone,
  sameDeclaredFields,
  toneClass,
} from './marketDataFormatters'
import type {
  AssetTab,
  ChartModeOption,
  CoverageRow,
  DataFamilyOption,
  DataFamilyView,
  DetailFieldSpec,
  DetailRow,
  GenericObservationColumn,
  GenericObservationResult,
  HistoryTableColumn,
  KpiCard,
  MarketDataPlatformProvenance,
  MarketDataPlatformStatus,
  RangeStat,
  ReferenceSeriesResult,
  SnapshotMetric,
} from './marketDataTypes'

export interface MarketDataPresentationDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  form: {
    asset_type: MarketAssetType
    symbol: string
    period: string
    market: string
  }
  selectedFamilyId: Ref<string>
  result: Ref<MarketInstrumentLookupResponse | null>
  snapshot: ComputedRef<Record<string, unknown>>
  historyRows: ComputedRef<MarketHistoryRow[]>
  referenceSeriesResult: Ref<ReferenceSeriesResult | null>
  genericObservationResult: Ref<GenericObservationResult | null>
  marketDataQueryBundle: Ref<MarketDataQueryBundle | null>
  marketDataPlatformStatus: Ref<MarketDataPlatformStatus>
  viewportWidth: Ref<number>
  coverageRows: Ref<MarketDataCoverageResponse[]>
  coverageTimeframe: Ref<string>
  coverageProvider: Ref<string>
  relatedTables: Ref<DataTable[]>
  relatedTablesError: Ref<string>
  currentAssetTab: () => AssetTab
  assetLabel: (assetType: MarketAssetType) => string
  fieldLabel: (field: string) => string
  formatDetailValue: (field: DetailFieldSpec) => string
  formatValuation: () => string
  shouldShowHistoryColumn: (field: string) => boolean
  metricCard: (labelKey: string, value: string, tone?: string) => KpiCard
  buildAssetKpiCards: () => KpiCard[]
  buildRangeStats: () => RangeStat[]
  buildCoverageRows: () => CoverageRow[]
  buildAssetDataFamilies: () => DataFamilyView[]
  selectedMarketPageFamilyFromQueryBundle: (
    bundle: MarketDataQueryBundle,
    assetType: MarketAssetType,
    familyId: string,
  ) => MarketDataQueryBundleFamily | null
  isMarketPageSelectableFamily: (
    family: MarketDataQueryBundleFamily,
    assetType: MarketAssetType,
  ) => boolean
  marketPageFamilyLabel: (family: MarketDataQueryBundleFamily) => string
}

export function useMarketDataPresentation(deps: MarketDataPresentationDeps) {
  const { t, form, selectedFamilyId, result, snapshot, historyRows } = deps

  const periods = computed(() => {
    const bundle = deps.marketDataQueryBundle.value
    if (!bundle || bundle.requested_asset_type !== form.asset_type) return basePeriods
    const family = deps.selectedMarketPageFamilyFromQueryBundle(
      bundle,
      form.asset_type,
      selectedFamilyId.value,
    )
    if (!family) return basePeriods
    return family.frequencies
      .map((frequency) => ({
        value: marketPagePeriodForV2Frequency(frequency),
        labelKey: periodLabelKey(frequency),
      }))
  })

  const selectedMarketPageFamily = computed(() => {
    const bundle = deps.marketDataQueryBundle.value
    if (!bundle || bundle.requested_asset_type !== form.asset_type) return null
    return deps.selectedMarketPageFamilyFromQueryBundle(
      bundle,
      form.asset_type,
      selectedFamilyId.value,
    )
  })

  const selectableDataFamilies = computed<DataFamilyOption[]>(() => {
    const bundle = deps.marketDataQueryBundle.value
    if (!bundle || bundle.requested_asset_type !== form.asset_type) return []
    return bundle.families
      .filter((family) => deps.isMarketPageSelectableFamily(family, form.asset_type))
      .map((family) => ({
        value: family.family_id,
        label: deps.marketPageFamilyLabel(family),
      }))
  })

  const isReferenceSeriesSelected = computed(() => (
    selectedMarketPageFamily.value?.data_kind === 'reference_series'
    || deps.referenceSeriesResult.value?.familyId === selectedFamilyId.value
  ))

  const isGenericObservationSelected = computed(() => (
    (selectedMarketPageFamily.value !== null
      && selectedMarketPageFamily.value.data_kind !== 'bars'
      && selectedMarketPageFamily.value.data_kind !== 'reference_series')
    || deps.genericObservationResult.value?.familyId === selectedFamilyId.value
  ))

  const isFundNavReferenceSeries = computed(() => {
    const presentation = deps.referenceSeriesResult.value
    const request = result.value?.query_contract?.request
    return form.asset_type === 'fund'
      && selectedFamilyId.value === 'fund.nav'
      && presentation?.familyId === 'fund.nav'
      && request?.family_id === 'fund.nav'
      && request.dataset_code === 'market.fund_nav'
      && request.data_kind === 'reference_series'
      && sameDeclaredFields(presentation.requiredFields, request.required_fields)
  })

  const fundNavReferenceFields = computed(() => {
    if (!isFundNavReferenceSeries.value) return []
    return [...(deps.referenceSeriesResult.value?.requiredFields || [])]
  })

  const referenceSeriesRows = computed(() => {
    const presentation = deps.referenceSeriesResult.value
    if (!presentation || presentation.familyId !== selectedFamilyId.value) return []
    return [...presentation.rows].sort(
      (left, right) => historyRowTimestamp(right) - historyRowTimestamp(left),
    )
  })

  const referenceSeriesTableColumns = computed<HistoryTableColumn[]>(() => {
    const presentation = deps.referenceSeriesResult.value
    if (!presentation || presentation.familyId !== selectedFamilyId.value) return []
    return [
      {
        key: 'date',
        label: t('dataMgmt.colDate'),
        width: 120,
        align: 'left',
        fixed: 'left',
        format: 'text',
      },
      ...presentation.requiredFields.map((field) => ({
        key: field,
        label: deps.fieldLabel(field),
        minWidth: 130,
        align: 'right' as const,
        format: field === 'daily_growth_rate' ? 'percent' as const : 'number' as const,
      })),
    ]
  })

  const referenceSeriesEmptyText = computed(() => (
    deps.referenceSeriesResult.value ? t('dataMgmt.emptyNoRows') : t('dataMgmt.emptyQueryFirst')
  ))

  const genericObservationRows = computed(() => {
    const presentation = deps.genericObservationResult.value
    if (!presentation || presentation.familyId !== selectedFamilyId.value) return []
    return [...presentation.observations].sort((left, right) => (
      Date.parse(right.event_at) - Date.parse(left.event_at)
    ))
  })

  const genericObservationColumns = computed<GenericObservationColumn[]>(() => {
    const presentation = deps.genericObservationResult.value
    if (!presentation || presentation.familyId !== selectedFamilyId.value) return []
    return [
      { key: 'event_at', label: t('dataMgmt.genericObservationColumnEventAt'), source: 'metadata' },
      { key: 'quality', label: t('dataMgmt.genericObservationColumnQuality'), source: 'metadata' },
      {
        key: 'source_snapshot_id',
        label: t('dataMgmt.genericObservationColumnSourceSnapshotId'),
        source: 'metadata',
      },
      { key: 'revision_id', label: t('dataMgmt.genericObservationColumnRevisionId'), source: 'metadata' },
      { key: 'available_at', label: t('dataMgmt.genericObservationColumnAvailableAt'), source: 'metadata' },
      { key: 'committed_at', label: t('dataMgmt.genericObservationColumnCommittedAt'), source: 'metadata' },
      {
        key: 'revision_number',
        label: t('dataMgmt.genericObservationColumnRevisionNumber'),
        source: 'metadata',
      },
      ...presentation.dimensionFields.map((field) => ({
        key: field,
        label: deps.fieldLabel(field),
        source: 'field' as const,
      })),
      ...presentation.requiredFields.map((field) => ({
        key: field,
        label: deps.fieldLabel(field),
        source: 'field' as const,
      })),
    ]
  })

  const genericObservationEmptyText = computed(() => {
    if (!deps.genericObservationResult.value) return t('dataMgmt.emptyQueryFirst')
    return t('dataMgmt.genericObservationEmpty')
  })

  const displayHistoryRows = computed(() => (
    [...historyRows.value].sort((left, right) => historyRowTimestamp(right) - historyRowTimestamp(left))
  ))

  const ohlcHistoryRows = computed(() => historyRows.value.filter((row) => (
    hasValue(row.date)
    && isFiniteNumber(numericValue(row.open, null))
    && isFiniteNumber(numericValue(row.high, null))
    && isFiniteNumber(numericValue(row.low, null))
    && isFiniteNumber(numericValue(row.close, null))
  )))

  const hasOhlcChart = computed(() => ohlcHistoryRows.value.length > 0)
  const hasStructureChart = computed(() => historyRows.value.some((row) => (
    hasValue(row.name) || hasValue(row.open_interest) || hasValue(row.volume)
  )))

  const chartCanRender = computed(() => (
    !isReferenceSeriesSelected.value
    && !isGenericObservationSelected.value
    && (hasOhlcChart.value || hasStructureChart.value)
  ))

  const activeAssetConfig = computed(() => assetDisplayConfigs[form.asset_type])
  const activeAssetIcon = computed<Component>(() => deps.currentAssetTab().icon)
  const symbolPlaceholder = computed(() => t(deps.currentAssetTab().placeholderKey))
  const emptyHistoryText = computed(() => (
    result.value ? t('dataMgmt.emptyNoRows') : t('dataMgmt.emptyQueryFirst')
  ))
  const chartEmptyText = computed(() => (
    result.value ? t('dataMgmt.chartEmpty') : t('dataMgmt.emptyQueryFirst')
  ))
  const chartSubtitle = computed(() => {
    const symbol = result.value?.symbol || form.symbol || '-'
    const rows = result.value?.history.total || 0
    return t('dataMgmt.chartSubtitle', { symbol, rows })
  })
  const chartAriaLabel = computed(() => t('dataMgmt.chartAria', {
    asset: deps.assetLabel(form.asset_type),
    symbol: result.value?.symbol || form.symbol || '-',
  }))

  const hasSnapshotChange = computed(() => (
    hasValue(snapshot.value.change) || hasValue(snapshot.value.change_pct)
  ))
  const marketOverviewPrimaryLabel = computed(() => (
    isFundNavReferenceSeries.value ? deps.fieldLabel('nav') : t('dataMgmt.fieldPrice')
  ))
  const marketOverviewPrimaryValue = computed(() => (
    isFundNavReferenceSeries.value
      ? formatReferenceSeriesField('nav', snapshot.value.nav)
      : formatNumber(snapshot.value.price)
  ))
  const marketOverviewTone = computed(() => (
    isFundNavReferenceSeries.value
      ? toneClass(snapshot.value.daily_growth_rate)
      : toneClass(snapshot.value.change_pct ?? snapshot.value.change)
  ))
  const marketOverviewSecondaryText = computed(() => {
    if (isFundNavReferenceSeries.value) {
      return hasValue(snapshot.value.daily_growth_rate)
        ? `${deps.fieldLabel('daily_growth_rate')} ${formatReferenceSeriesField('daily_growth_rate', snapshot.value.daily_growth_rate)}`
        : null
    }
    if (!hasSnapshotChange.value) return null
    return `${formatNumber(snapshot.value.change)} / ${formatPercent(snapshot.value.change_pct)}`
  })
  const assetOverviewDescription = computed(() => (
    isFundNavReferenceSeries.value
      ? t('dataMgmt.familyNavDesc', { count: 0 })
      : t(activeAssetConfig.value.descKey)
  ))
  const assetDetailTitle = computed(() => (
    isFundNavReferenceSeries.value
      ? t('dataMgmt.familyNav')
      : t(activeAssetConfig.value.detailTitleKey)
  ))
  const assetDetailNote = computed(() => (
    isFundNavReferenceSeries.value
      ? t('dataMgmt.familyNavDesc', { count: 0 })
      : t(activeAssetConfig.value.detailNoteKey)
  ))

  const hasSnapshotTurnover = computed(() => hasValue(snapshot.value.turnover))
  const hasSnapshotBidAsk = computed(() => hasValue(snapshot.value.bid) || hasValue(snapshot.value.ask))
  const hasSnapshotOpenInterest = computed(() => hasValue(snapshot.value.open_interest))
  const hasSnapshotSettle = computed(() => hasValue(snapshot.value.settle))
  const hasSnapshotValuation = computed(() => hasValue(snapshot.value.pe) || hasValue(snapshot.value.pb))
  const hasSnapshotDataSource = computed(() => hasValue(snapshot.value.data_source_table))
  const snapshotDescriptionColumns = computed(() => (deps.viewportWidth.value >= 720 ? 2 : 1))

  const snapshotMetrics = computed<SnapshotMetric[]>(() => {
    const metrics: SnapshotMetric[] = [
      { key: 'symbol', label: t('dataMgmt.fieldSymbol'), value: formatText(result.value?.symbol) },
      { key: 'name', label: t('dataMgmt.fieldName'), value: formatText(result.value?.name) },
      { key: 'market', label: t('dataMgmt.fieldMarket'), value: formatText(result.value?.market) },
    ]

    if (hasSnapshotDataSource.value) {
      metrics.push({
        key: 'data_source_table',
        label: t('dataMgmt.fieldDataSourceTable'),
        value: formatText(snapshot.value.data_source_table),
      })
    }

    if (isFundNavReferenceSeries.value) {
      metrics.push(...fundNavReferenceFields.value.map((field) => ({
        key: field,
        label: deps.fieldLabel(field),
        value: formatReferenceSeriesField(field, snapshot.value[field]),
        tone: referenceSeriesFieldTone(field, snapshot.value[field]),
      })))
      metrics.push({ key: 'updated', label: t('dataMgmt.fieldUpdated'), value: formatText(snapshot.value.update_time) })
      return metrics
    }

    metrics.push({ key: 'price', label: t('dataMgmt.fieldPrice'), value: formatNumber(snapshot.value.price) })
    if (hasSnapshotChange.value) {
      metrics.push({
        key: 'change',
        label: t('dataMgmt.colChange'),
        value: `${formatNumber(snapshot.value.change)} / ${formatPercent(snapshot.value.change_pct)}`,
        tone: toneClass(snapshot.value.change_pct ?? snapshot.value.change),
      })
    }
    metrics.push(
      { key: 'open', label: t('dataMgmt.fieldOpen'), value: formatNumber(snapshot.value.open) },
      {
        key: 'high_low',
        label: t('dataMgmt.fieldHighLow'),
        value: formatPair(snapshot.value.high, snapshot.value.low),
      },
      { key: 'volume', label: t('dataMgmt.fieldVolume'), value: formatNumber(snapshot.value.volume) },
    )

    if (hasSnapshotTurnover.value) {
      metrics.push({ key: 'turnover', label: t('dataMgmt.fieldTurnover'), value: formatNumber(snapshot.value.turnover) })
    }
    if (hasSnapshotBidAsk.value) {
      metrics.push({ key: 'bid_ask', label: t('dataMgmt.fieldBidAsk'), value: formatPair(snapshot.value.bid, snapshot.value.ask) })
    }
    if (hasSnapshotOpenInterest.value) {
      metrics.push({
        key: 'open_interest',
        label: t('dataMgmt.fieldOpenInterest'),
        value: formatNumber(snapshot.value.open_interest),
      })
    }
    if (hasSnapshotSettle.value) {
      metrics.push({ key: 'settle', label: t('dataMgmt.fieldSettle'), value: formatNumber(snapshot.value.settle) })
    }
    if (hasSnapshotValuation.value) {
      metrics.push({ key: 'valuation', label: t('dataMgmt.fieldValuation'), value: deps.formatValuation() })
    }

    metrics.push({ key: 'updated', label: t('dataMgmt.fieldUpdated'), value: formatText(snapshot.value.update_time) })
    return metrics
  })

  const assetKpiCards = computed<KpiCard[]>(() => deps.buildAssetKpiCards())

  const chartModeOptions = computed<ChartModeOption[]>(() => {
    if (hasOhlcChart.value) {
      return [
        { value: 'price', label: t('dataMgmt.chartModePrice') },
        { value: 'return', label: t('dataMgmt.chartModeReturn') },
        { value: 'liquidity', label: t('dataMgmt.chartModeLiquidity') },
      ]
    }
    if (hasStructureChart.value) {
      return [
        { value: 'structure', label: t('dataMgmt.chartModeStructure') },
        { value: 'liquidity', label: t('dataMgmt.chartModeLiquidity') },
      ]
    }
    return [{ value: 'price', label: t('dataMgmt.chartModePrice') }]
  })

  const rangeStats = computed<RangeStat[]>(() => deps.buildRangeStats())
  const dataCoverageRows = computed<CoverageRow[]>(() => deps.buildCoverageRows())
  const coverageScore = computed(() => {
    if (!dataCoverageRows.value.length) return 0
    const total = dataCoverageRows.value.reduce((sum, item) => sum + item.coverage, 0)
    return Math.round(total / dataCoverageRows.value.length)
  })
  const displayedObservationCount = computed(() => (
    deps.genericObservationResult.value?.familyId === selectedFamilyId.value
      ? deps.genericObservationResult.value.observations.length
      : result.value?.history.total
  ))
  const heroStats = computed<KpiCard[]>(() => [
    deps.metricCard('dataMgmt.heroStatAsset', deps.assetLabel(form.asset_type)),
    deps.metricCard('dataMgmt.heroStatSymbol', result.value?.symbol || form.symbol || '-'),
    deps.metricCard('dataMgmt.heroStatRows', formatNumber(displayedObservationCount.value)),
    deps.metricCard('dataMgmt.heroStatCoverage', `${coverageScore.value}%`),
  ])

  const marketDataPlatformSourceText = computed(() => {
    const status = deps.marketDataPlatformStatus.value
    if (status.path === 'provider_persisted') {
      return status.provider
        ? t('dataMgmt.marketDataSourceProviderPersistedWithProvider', { provider: status.provider })
        : t('dataMgmt.marketDataSourceProviderPersisted')
    }
    if (status.path === 'provider_persisted_incomplete') {
      const receipts = t('dataMgmt.marketDataSourceProviderPersistedIncomplete', {
        count: status.fetchedProviderCount,
      })
      return status.fallbackReason === 'ONLINE_FETCH_DISABLED'
        ? t('dataMgmt.marketDataSourceOnlineFetchDisabled', { receipts })
        : receipts
    }
    if (status.path === 'local_only') return t('dataMgmt.marketDataSourceLocalOnly')
    if (status.path === 'local_first') {
      return status.provider
        ? t('dataMgmt.marketDataSourceLocalFirstWithProvider', { provider: status.provider })
        : t('dataMgmt.marketDataSourceLocalFirst')
    }
    if (status.path === 'local_coverage_incomplete') {
      return status.fallbackReason === 'ONLINE_FETCH_DISABLED'
        ? t('dataMgmt.marketDataSourceCoverageIncompleteOnlineDisabled')
        : status.fallbackReason === 'LOCAL_ONLY_COVERAGE_INCOMPLETE'
          ? t('dataMgmt.marketDataSourceCoverageIncompleteLocalOnly')
          : t('dataMgmt.marketDataSourceCoverageIncomplete')
    }
    if (status.path === 'legacy_fallback') return t('dataMgmt.marketDataSourceLegacyFallback')
    if (status.path === 'family_selection_pending') return t('dataMgmt.marketDataSourceFamilySelectionPending')
    if (status.path === 'bundle_unconfigured') return t('dataMgmt.marketDataSourceBundleUnconfigured')
    if (status.path === 'bundle_period_unsupported') return t('dataMgmt.marketDataSourceBundlePeriodUnsupported')
    if (status.path === 'error') return t('dataMgmt.marketDataSourceError')
    return t('dataMgmt.marketDataSourceLegacy')
  })

  const marketDataPlatformCacheText = computed(() => {
    const status = deps.marketDataPlatformStatus.value
    if (status.path === 'provider_persisted') {
      return t('dataMgmt.marketDataCacheProviderPersisted', { count: status.fetchedProviderCount })
    }
    if (status.path === 'provider_persisted_incomplete') {
      return t('dataMgmt.marketDataCacheProviderPersistedIncomplete', {
        count: status.fetchedProviderCount,
      })
    }
    if (status.path === 'local_only') return t('dataMgmt.marketDataCacheLocalOnly')
    if (status.path === 'local_first') return t('dataMgmt.marketDataCacheLocalFirst')
    if (status.path === 'local_coverage_incomplete') return t('dataMgmt.marketDataCacheCoverageIncomplete')
    if (status.path === 'legacy_fallback') return t('dataMgmt.marketDataCacheLegacyFallback')
    if (status.path === 'family_selection_pending') return t('dataMgmt.marketDataCacheFamilySelectionPending')
    if (status.path === 'bundle_unconfigured') return t('dataMgmt.marketDataCacheBundleUnconfigured')
    if (status.path === 'bundle_period_unsupported') {
      const resetPeriod = status.periodConstraint?.resetPeriod
      return resetPeriod
        ? t('dataMgmt.marketDataCachePeriodReset', { period: t(periodLabelKey(resetPeriod)) })
        : t('dataMgmt.marketDataCacheNoQuery')
    }
    if (status.path === 'error') return t('dataMgmt.marketDataCacheError')
    return t('dataMgmt.marketDataCacheLegacy')
  })

  const marketDataPlatformCoverageText = computed(() => {
    const status = deps.marketDataPlatformStatus.value
    if (status.path === 'family_selection_pending') {
      return t('dataMgmt.marketDataCoverageFamilySelectionPending')
    }
    if (status.path === 'bundle_unconfigured') {
      return t('dataMgmt.marketDataCoverageBundleUnconfigured')
    }
    if (status.path === 'bundle_period_unsupported') {
      const constraint = status.periodConstraint
      if (!constraint) return t('dataMgmt.marketDataCoverageNoDeclaredFrequency')
      const declaredPeriods = constraint.declaredFrequencies
        .map((frequency) => t(periodLabelKey(frequency)))
      return t('dataMgmt.marketDataCoverageDeclaredFrequencies', {
        familyId: constraint.familyId,
        periods: declaredPeriods.join('/'),
      })
    }
    if (!status.coverageStatus) return t('dataMgmt.marketDataCoverageUnavailable')
    const ratio = status.coverageRatio === null ? '-' : `${(status.coverageRatio * 100).toFixed(2)}%`
    return `${status.coverageStatus} · ${ratio}`
  })

  const marketDataPlatformTagType = computed<'success' | 'warning' | 'info'>(() => {
    const path = deps.marketDataPlatformStatus.value.path
    if (path === 'local_only' || path === 'local_first' || path === 'provider_persisted') return 'success'
    if (
      path === 'local_coverage_incomplete'
      || path === 'provider_persisted_incomplete'
      || path === 'legacy_fallback'
      || path === 'family_selection_pending'
      || path === 'bundle_unconfigured'
      || path === 'bundle_period_unsupported'
      || path === 'error'
    ) return 'warning'
    return 'info'
  })

  const marketDataPlatformProvenance = computed<MarketDataPlatformProvenance[]>(() => {
    const status = deps.marketDataPlatformStatus.value
    const entries: Array<MarketDataPlatformProvenance | null> = [
      status.canonicalId ? { label: t('dataMgmt.marketDataProvenanceCanonicalId'), value: status.canonicalId } : null,
      status.datasetCode ? { label: t('dataMgmt.marketDataProvenanceDataset'), value: status.datasetCode } : null,
      status.familyId ? { label: t('dataMgmt.marketDataProvenanceFamily'), value: status.familyId } : null,
      status.sourcePolicyId ? { label: t('dataMgmt.marketDataProvenanceSourcePolicy'), value: status.sourcePolicyId } : null,
      status.instrumentMetadataVersion
        ? { label: t('dataMgmt.marketDataProvenanceMetadataVersion'), value: status.instrumentMetadataVersion }
        : null,
    ]
    return entries.filter((entry): entry is MarketDataPlatformProvenance => entry !== null)
  })

  const coverageMatrixSubtitle = computed(() => {
    const provider = deps.coverageProvider.value.trim() || t('dataMgmt.coverageAllProviders')
    return `${deps.assetLabel(form.asset_type)} · ${deps.coverageTimeframe.value} · ${provider}`
  })

  const coverageSummaryCards = computed<KpiCard[]>(() => {
    const rows = deps.coverageRows.value
    const passed = rows.filter((row) => row.quality_status === 'pass').length
    const warnings = rows.filter((row) => row.quality_status === 'warning').length
    const failed = rows.filter((row) => row.quality_status === 'failed').length
    const totalRows = rows.reduce((sum, row) => sum + (row.row_count || 0), 0)
    return [
      { label: t('dataMgmt.coverageSymbols'), value: formatNumber(rows.length), tone: '' },
      { label: t('dataMgmt.coveragePassed'), value: formatNumber(passed), tone: passed ? 'is-positive' : '' },
      { label: t('dataMgmt.coverageWarning'), value: formatNumber(warnings), tone: warnings ? 'is-warning' : '' },
      { label: t('dataMgmt.coverageFailed'), value: formatNumber(failed), tone: failed ? 'is-negative' : '' },
      { label: t('dataMgmt.coverageTotalRows'), value: formatNumber(totalRows), tone: '' },
    ]
  })

  const assetDataFamilies = computed<DataFamilyView[]>(() => deps.buildAssetDataFamilies())
  const relatedTablesBadge = computed(() => {
    if (deps.relatedTablesError.value) return t('dataMgmt.relatedTablesUnavailable')
    return t('dataMgmt.relatedTablesBadge', { count: deps.relatedTables.value.length })
  })
  const relatedTableSummary = computed(() => {
    const totalRows = deps.relatedTables.value.reduce((sum, table) => sum + (table.row_count || 0), 0)
    return t('dataMgmt.relatedTablesSummary', {
      count: deps.relatedTables.value.length,
      rows: formatNumber(totalRows),
    })
  })

  const assetDetailRows = computed<DetailRow[]>(() => {
    if (isFundNavReferenceSeries.value) {
      return fundNavReferenceFields.value.map((field) => ({
        label: deps.fieldLabel(field),
        value: formatReferenceSeriesField(field, snapshot.value[field]),
        tone: referenceSeriesFieldTone(field, snapshot.value[field]),
      }))
    }
    return activeAssetConfig.value.detailFields.map((field) => ({
      label: t(field.labelKey),
      value: deps.formatDetailValue(field),
      tone: field.tone ? toneClass(snapshot.value[field.fields[0]]) : '',
    }))
  })

  const historyTableColumns = computed<HistoryTableColumn[]>(() => [
    {
      key: 'date',
      label: t('dataMgmt.colDate'),
      width: 120,
      align: 'left',
      fixed: 'left',
      format: 'text',
    },
    ...activeAssetConfig.value.historyColumns
      .filter((column) => deps.shouldShowHistoryColumn(column.key))
      .map((column) => ({
        ...column,
        label: t(column.labelKey),
      })),
  ])

  void formatGenericObservationValue

  return {
    periods,
    selectedMarketPageFamily,
    selectableDataFamilies,
    isReferenceSeriesSelected,
    isGenericObservationSelected,
    isFundNavReferenceSeries,
    fundNavReferenceFields,
    referenceSeriesRows,
    referenceSeriesTableColumns,
    referenceSeriesEmptyText,
    genericObservationRows,
    genericObservationColumns,
    genericObservationEmptyText,
    displayHistoryRows,
    ohlcHistoryRows,
    hasOhlcChart,
    hasStructureChart,
    chartCanRender,
    activeAssetConfig,
    activeAssetIcon,
    symbolPlaceholder,
    emptyHistoryText,
    chartEmptyText,
    chartSubtitle,
    chartAriaLabel,
    hasSnapshotChange,
    marketOverviewPrimaryLabel,
    marketOverviewPrimaryValue,
    marketOverviewTone,
    marketOverviewSecondaryText,
    assetOverviewDescription,
    assetDetailTitle,
    assetDetailNote,
    hasSnapshotTurnover,
    hasSnapshotBidAsk,
    hasSnapshotOpenInterest,
    hasSnapshotSettle,
    hasSnapshotValuation,
    hasSnapshotDataSource,
    snapshotDescriptionColumns,
    snapshotMetrics,
    assetKpiCards,
    chartModeOptions,
    rangeStats,
    dataCoverageRows,
    coverageScore,
    displayedObservationCount,
    heroStats,
    marketDataPlatformSourceText,
    marketDataPlatformCacheText,
    marketDataPlatformCoverageText,
    marketDataPlatformTagType,
    marketDataPlatformProvenance,
    coverageMatrixSubtitle,
    coverageSummaryCards,
    assetDataFamilies,
    relatedTablesBadge,
    relatedTableSummary,
    assetDetailRows,
    historyTableColumns,
  }
}
