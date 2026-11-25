import type { ComputedRef, Ref } from 'vue'
import {
  createMarketDataQueryFromContract,
  hasMarketDataQueryBundle,
  hasMarketDataQueryContract,
  isMarketDataQueryBundleFamilyExecutable,
  isMarketDataQueryV2FallbackError,
  marketDataApi,
  type MarketAssetType,
  type MarketDataCapabilitiesResponse,
  type MarketDataQueryBundle,
  type MarketDataQueryBundleFamily,
  type MarketDataQueryContract,
  type MarketDataQueryContractParams,
  type MarketDataQueryMode,
  type MarketDataQueryResponse,
  type MarketHistoryRow,
  type MarketInstrumentLookupResponse,
} from '@/api/marketData'
import { assetDataFamilySpecs } from './marketDataCatalogSpecs'
import {
  assertMarketDataResponseEcho,
  assertResponseRequiredFields,
  averageNumbers,
  defaultFamilyIdForAsset,
  genericObservationResultFromV2Response,
  isMarketPageSelectableFamilyForBundle,
  lookupShellForV2Query,
  numericSeries,
  numericValue,
  periodReturnPct,
  publicMarketDataProvenanceValue,
  queryWindowFromDateRange,
  referenceSeriesRowsFromV2Response,
  resetToDeclaredPeriod,
  sameDeclaredFields,
  v2FrequencyForLegacyPeriod,
  v2HistoryRows,
} from './marketDataFormatters'
import {
  V2_MARKET_DATA_PAGE_SIZE,
  type GenericObservationResult,
  type MarketDataPlatformStatus,
  type ReferenceSeriesResult,
  type V2LookupResult,
} from './marketDataTypes'

export interface MarketDataV2QueryDeps {
  t: (key: string, params?: Record<string, unknown>) => string
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
  marketDataQueryBundle: Ref<MarketDataQueryBundle | null>
  marketDataPlatformStatus: Ref<MarketDataPlatformStatus>
  invalidateMarketDataQueryLifecycle: () => void
  constrainDateRangeForFamily: (
    family: Pick<MarketDataQueryBundleFamily, 'data_kind'> | null | undefined,
    requestedDateRange?: readonly [string | undefined, string | undefined],
  ) => readonly [string | undefined, string | undefined]
  throwIfMarketDataQueryAborted: (signal?: AbortSignal) => void
}

export function useMarketDataV2Query(deps: MarketDataV2QueryDeps) {
  function queryContractForCurrentPeriod(
    contract: unknown,
    expectedFamilyId: string,
    expectedDataKind: MarketDataQueryBundleFamily['data_kind'] = 'bars',
    period = deps.form.period,
  ): MarketDataQueryContract | null {
    if (!hasMarketDataQueryContract(contract)) return null
    const request = contract.request
    if (
      request.data_kind !== expectedDataKind
      || request.frequency !== v2FrequencyForLegacyPeriod(period)
      || request.family_id !== expectedFamilyId
      || request.family_contract_version !== 'market-data-family-v1'
    ) {
      return null
    }
    return contract
  }

  function queryContractForCurrentLookup(
    lookupResult: MarketInstrumentLookupResponse | null,
    assetType: MarketAssetType,
    symbol: string,
    period = deps.form.period,
  ): MarketDataQueryContract | null {
    if (!lookupResult || lookupResult.asset_type !== assetType) return null
    const expectedSymbol = symbol.trim()
    if (lookupResult.symbol.trim() !== expectedSymbol) return null
    const contract = queryContractForCurrentPeriod(
      lookupResult.query_contract,
      `${assetType}.realtime`,
      'bars',
      period,
    )
    if (!contract) return null
    if (
      typeof lookupResult.query_contract_symbol !== 'string'
      || lookupResult.query_contract_symbol.trim() !== expectedSymbol
      || typeof lookupResult.query_contract_canonical_id !== 'string'
      || lookupResult.query_contract_canonical_id !== contract.request.identity.canonical_id
    ) {
      return null
    }
    return contract
  }

  function familyFromQueryBundle(
    bundle: MarketDataQueryBundle,
    familyId: string,
  ): MarketDataQueryBundleFamily | null {
    return bundle.families.find((family) => family.family_id === familyId) || null
  }

  function defaultFamilyId(assetType: MarketAssetType): string {
    return defaultFamilyIdForAsset(assetType)
  }

  function isMarketPageSelectableFamily(
    family: MarketDataQueryBundleFamily,
    assetType: MarketAssetType,
  ): boolean {
    return family.asset_type === assetType && isMarketDataQueryBundleFamilyExecutable(family)
  }

  function selectedMarketPageFamilyFromQueryBundle(
    bundle: MarketDataQueryBundle,
    assetType: MarketAssetType,
    familyId: string,
  ): MarketDataQueryBundleFamily | null {
    const family = familyFromQueryBundle(bundle, familyId)
    return family && isMarketPageSelectableFamily(family, assetType) ? family : null
  }

  function marketPageFamilyLabel(family: MarketDataQueryBundleFamily): string {
    const spec = assetDataFamilySpecs[family.asset_type].find(
      (candidate) => candidate.familyId === family.family_id,
    )
    return spec ? deps.t(spec.labelKey) : family.family_id
  }

  function createEmptyStatus(
    path: MarketDataPlatformStatus['path'],
    overrides: Partial<MarketDataPlatformStatus> = {},
  ): MarketDataPlatformStatus {
    return {
      path,
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
      ...overrides,
    }
  }

  function setLegacyMarketDataPlatformStatus(fallbackReason: string | null = null) {
    deps.marketDataPlatformStatus.value = createEmptyStatus(
      fallbackReason ? 'legacy_fallback' : 'legacy',
      { fallbackReason },
    )
  }

  function setMarketDataPlatformErrorStatus() {
    deps.marketDataPlatformStatus.value = createEmptyStatus('error')
  }

  function clearMarketDataFamilyScopedState(familyId: string | null) {
    deps.marketDataPlatformStatus.value = createEmptyStatus('family_selection_pending', { familyId })
  }

  function setMarketDataBundleUnconfiguredStatus(familyId: string | null = null) {
    deps.marketDataPlatformStatus.value = createEmptyStatus('bundle_unconfigured', { familyId })
  }

  function setMarketDataBundlePeriodUnsupportedStatus(
    family: MarketDataQueryBundleFamily,
    requestedFrequency: string,
    resetPeriod: string | null,
  ) {
    deps.marketDataPlatformStatus.value = createEmptyStatus('bundle_period_unsupported', {
      familyId: family.family_id,
      periodConstraint: {
        familyId: family.family_id,
        requestedFrequency,
        declaredFrequencies: [...family.frequencies],
        resetPeriod,
      },
    })
  }

  function setV2MarketDataPlatformStatus(
    response: MarketDataQueryResponse,
    queryMode: MarketDataQueryMode,
    capabilities: MarketDataCapabilitiesResponse | null,
  ) {
    const fetches = response.fetches || []
    const incompleteLocalCoverage = response.coverage.status !== 'complete'
    const onlineFetchDisabled = capabilities?.online_fetch_enabled === false
      && response.warnings.some((warning) => warning.code === 'ONLINE_FETCH_DISABLED')
    const incompleteFallbackReason = queryMode === 'local_only'
      ? 'LOCAL_ONLY_COVERAGE_INCOMPLETE'
      : onlineFetchDisabled ? 'ONLINE_FETCH_DISABLED' : 'LOCAL_COVERAGE_INCOMPLETE'
    deps.marketDataPlatformStatus.value = {
      path: incompleteLocalCoverage
        ? fetches.length ? 'provider_persisted_incomplete' : 'local_coverage_incomplete'
        : queryMode === 'local_only'
          ? 'local_only'
          : fetches.length ? 'provider_persisted' : 'local_first',
      provider: fetches[fetches.length - 1]?.provider_id || null,
      coverageStatus: response.coverage.status,
      coverageRatio: response.coverage.coverage_ratio,
      fetchedProviderCount: fetches.length,
      fallbackReason: incompleteLocalCoverage ? incompleteFallbackReason : null,
      queryId: response.query_id,
      canonicalId: publicMarketDataProvenanceValue(response.canonical_id),
      datasetCode: publicMarketDataProvenanceValue(response.dataset_code),
      sourcePolicyId: publicMarketDataProvenanceValue(response.source_policy_id),
      instrumentMetadataVersion: publicMarketDataProvenanceValue(response.instrument_metadata_version),
      familyId: publicMarketDataProvenanceValue(response.family_id),
      periodConstraint: null,
    }
  }

  function selectDataFamily(familyId: string): void {
    const bundle = deps.marketDataQueryBundle.value
    const family = bundle && bundle.requested_asset_type === deps.form.asset_type
      ? selectedMarketPageFamilyFromQueryBundle(bundle, deps.form.asset_type, familyId)
      : null
    if (!family) {
      const fallbackFamilyId = defaultFamilyId(deps.form.asset_type)
      const changed = deps.selectedFamilyId.value !== fallbackFamilyId
      deps.selectedFamilyId.value = fallbackFamilyId
      deps.referenceSeriesResult.value = null
      deps.genericObservationResult.value = null
      if (changed) {
        deps.invalidateMarketDataQueryLifecycle()
        deps.result.value = null
        clearMarketDataFamilyScopedState(fallbackFamilyId)
      }
      return
    }

    const changed = deps.selectedFamilyId.value !== family.family_id
    deps.selectedFamilyId.value = family.family_id
    deps.referenceSeriesResult.value = null
    deps.genericObservationResult.value = null
    if (changed) {
      deps.invalidateMarketDataQueryLifecycle()
      deps.result.value = null
      clearMarketDataFamilyScopedState(family.family_id)
    }

    const requestedFrequency = v2FrequencyForLegacyPeriod(deps.form.period)
    if (!family.frequencies.includes(requestedFrequency)) {
      const resetPeriod = resetToDeclaredPeriod(family)
      if (resetPeriod) deps.form.period = resetPeriod
    }
    deps.constrainDateRangeForFamily(family)
  }

  function contractMatchesDeclaredFamily(
    contract: MarketDataQueryContract,
    family: MarketDataQueryBundleFamily,
    period = deps.form.period,
  ): boolean {
    const request = contract.request
    return request.family_id === family.family_id
      && request.family_contract_version === family.family_contract_version
      && request.dataset_code === family.dataset_code
      && request.data_kind === family.data_kind
      && request.frequency === v2FrequencyForLegacyPeriod(period)
      && family.frequencies.includes(request.frequency)
      && sameDeclaredFields(request.required_fields, family.required_fields)
      && family.source_policy_id !== null
      && request.source_policy_id === family.source_policy_id
  }

  async function resolveV2QueryBundle(
    assetType: MarketAssetType,
    enabled: boolean,
  ): Promise<{ bundle: MarketDataQueryBundle | null; fellBack: boolean }> {
    if (!enabled) return { bundle: null, fellBack: false }
    try {
      const bundle = await marketDataApi.getQueryBundle({ asset_type: assetType })
      if (
        !hasMarketDataQueryBundle(bundle)
        || bundle.requested_asset_type !== assetType
        || bundle.families.some((family) => family.asset_type !== assetType)
      ) {
        throw new Error('MARKET_DATA_QUERY_BUNDLE_INVALID')
      }
      return { bundle, fellBack: false }
    } catch (error) {
      if (isMarketDataQueryV2FallbackError(error)) return { bundle: null, fellBack: true }
      throw error
    }
  }

  async function resolveV2QueryContract(
    assetType: MarketAssetType,
    symbol: string,
    period: string,
    declaredFamily: MarketDataQueryBundleFamily | null = null,
  ): Promise<{ contract: MarketDataQueryContract | null; fellBack: boolean }> {
    const expectedFamilyId = declaredFamily?.family_id || `${assetType}.realtime`
    try {
      const contract = await marketDataApi.getQueryContract({
        asset_type: assetType,
        symbol,
        period: period as MarketDataQueryContractParams['period'],
        family_id: expectedFamilyId,
      })
      const currentContract = queryContractForCurrentPeriod(
        contract,
        expectedFamilyId,
        declaredFamily?.data_kind || 'bars',
        period,
      )
      if (
        !currentContract
        || (declaredFamily && !contractMatchesDeclaredFamily(currentContract, declaredFamily, period))
      ) {
        throw new Error('MARKET_DATA_QUERY_CONTRACT_INVALID')
      }
      return { contract: currentContract, fellBack: false }
    } catch (error) {
      if (isMarketDataQueryV2FallbackError(error)) return { contract: null, fellBack: true }
      throw error
    }
  }

  function lookupFromV2Response(
    response: MarketDataQueryResponse,
    legacyLookup: MarketInstrumentLookupResponse,
    requiredFields: readonly string[] = ['close'],
  ): MarketInstrumentLookupResponse {
    const rows = v2HistoryRows(response, requiredFields)
    const latestRow = rows[rows.length - 1]
    const latestFields: Record<string, unknown> = latestRow ? { ...latestRow } : {}
    delete latestFields.date
    const closeValues = numericSeries(rows, 'close')
    const volumeValues = numericSeries(rows, 'volume')
    const latestClose = closeValues[closeValues.length - 1] ?? null
    const lastFetch = response.fetches[response.fetches.length - 1]
    const lastObservation = response.observations[response.observations.length - 1]
    const provider = lastFetch?.provider_id || legacyLookup.provider || 'local_market_data'
    const warnings = response.warnings.map((warning) => warning.code)

    return {
      ...legacyLookup,
      asset_type: response.asset_type,
      provider,
      snapshot: {
        ...legacyLookup.snapshot,
        ...latestFields,
        price: numericValue(latestFields.price ?? latestFields.close, legacyLookup.snapshot.price ?? null),
        update_time: lastObservation?.available_at || legacyLookup.snapshot.update_time,
        data_source_table: response.dataset_code,
      },
      history: {
        period: deps.form.period,
        rows,
        total: rows.length,
      },
      indicators: {
        latest_close: latestClose,
        return_pct: periodReturnPct(closeValues),
        highest_close: closeValues.length ? Math.max(...closeValues) : null,
        lowest_close: closeValues.length ? Math.min(...closeValues) : null,
        avg_volume: averageNumbers(volumeValues),
        observation_count: rows.length,
      },
      warnings,
    }
  }

  function lookupFromReferenceSeriesResponse(
    response: MarketDataQueryResponse,
    legacyLookup: MarketInstrumentLookupResponse,
    rows: MarketHistoryRow[],
  ): MarketInstrumentLookupResponse {
    const latestRow = rows[rows.length - 1]
    const latestFields: Record<string, unknown> = latestRow ? { ...latestRow } : {}
    delete latestFields.date
    const lastFetch = response.fetches[response.fetches.length - 1]
    const lastObservation = response.observations
      .filter((observation) => observation.quality === 'pass')
      .sort((left, right) => Date.parse(left.event_at) - Date.parse(right.event_at))
      .at(-1)
    const provider = lastFetch?.provider_id || 'local_market_data'

    return {
      ...legacyLookup,
      asset_type: response.asset_type,
      provider,
      snapshot: {
        ...latestFields,
        update_time: lastObservation?.available_at,
        data_source_table: response.dataset_code,
      },
      history: {
        period: deps.form.period,
        rows,
        total: rows.length,
      },
      indicators: {
        observation_count: rows.length,
        avg_volume: averageNumbers(numericSeries(rows, 'volume')),
      },
      warnings: response.warnings.map((warning) => warning.code),
    }
  }

  function lookupFromGenericObservationResponse(
    response: MarketDataQueryResponse,
    legacyLookup: MarketInstrumentLookupResponse,
  ): MarketInstrumentLookupResponse {
    const lastFetch = response.fetches[response.fetches.length - 1]
    const lastPassingObservation = response.observations
      .filter((observation) => observation.quality === 'pass')
      .sort((left, right) => Date.parse(left.event_at) - Date.parse(right.event_at))
      .at(-1)
    const provider = lastFetch?.provider_id || 'local_market_data'

    return {
      ...legacyLookup,
      asset_type: response.asset_type,
      provider,
      snapshot: {
        update_time: lastPassingObservation?.available_at,
        data_source_table: response.dataset_code,
      },
      history: {
        period: deps.form.period,
        rows: [],
        total: 0,
      },
      indicators: {
        observation_count: response.observations.length,
      },
      warnings: response.warnings.map((warning) => warning.code),
    }
  }

  async function queryAllV2MarketDataPages(
    initialRequest: ReturnType<typeof createMarketDataQueryFromContract>,
    expectedAssetType: MarketAssetType,
    signal?: AbortSignal,
  ): Promise<MarketDataQueryResponse> {
    const first = await marketDataApi.queryLocalFirst(
      initialRequest,
      { signal, suppressErrorMessage: true },
    )
    deps.throwIfMarketDataQueryAborted(signal)
    assertMarketDataResponseEcho(first, initialRequest, expectedAssetType)
    const observations = [...first.observations]
    const warnings = [...first.warnings]
    const observationIds = new Set(first.observations.map((item) => item.revision_id))
    const cursors = new Set<string>()
    let cursor = first.next_cursor

    while (cursor) {
      deps.throwIfMarketDataQueryAborted(signal)
      if (cursors.has(cursor)) {
        throw new Error('MARKET_DATA_CURSOR_PAGINATION_INTEGRITY')
      }
      cursors.add(cursor)
      const page = await marketDataApi.queryLocalFirst(
        { ...initialRequest, cursor },
        { signal, suppressErrorMessage: true },
      )
      deps.throwIfMarketDataQueryAborted(signal)
      assertMarketDataResponseEcho(page, initialRequest, expectedAssetType)
      if (
        page.query_id !== first.query_id
        || page.knowledge_cutoff !== first.knowledge_cutoff
        || page.identity_knowledge_cutoff !== first.identity_knowledge_cutoff
      ) {
        throw new Error('MARKET_DATA_CURSOR_PAGINATION_INTEGRITY')
      }
      for (const observation of page.observations) {
        if (observationIds.has(observation.revision_id)) {
          throw new Error('MARKET_DATA_CURSOR_PAGINATION_INTEGRITY')
        }
        observationIds.add(observation.revision_id)
        observations.push(observation)
      }
      warnings.push(...page.warnings)
      cursor = page.next_cursor
    }

    return {
      ...first,
      observations,
      next_cursor: null,
      warnings,
    }
  }

  async function queryV2FromLookupContract(
    contract: MarketDataQueryContract,
    legacyLookup: MarketInstrumentLookupResponse,
    queryMode: MarketDataQueryMode = 'local_first',
    requestedDateRange: readonly [string | undefined, string | undefined] = deps.dateRange.value,
    declaredFamily: MarketDataQueryBundleFamily | null = null,
    signal?: AbortSignal,
  ): Promise<V2LookupResult> {
    const window = queryWindowFromDateRange(requestedDateRange)
    if (!window) throw new Error('MARKET_DATA_QUERY_WINDOW_INVALID')

    const response = await queryAllV2MarketDataPages(
      createMarketDataQueryFromContract(contract, {
        ...window,
        mode: queryMode,
        purpose: 'display',
        consistency: 'display',
        page_size: V2_MARKET_DATA_PAGE_SIZE,
      }),
      legacyLookup.asset_type,
      signal,
    )
    assertResponseRequiredFields(response, contract.request.required_fields)
    if (contract.request.data_kind === 'reference_series') {
      const rows = referenceSeriesRowsFromV2Response(response, contract.request.required_fields)
      return {
        response,
        referenceSeries: {
          familyId: contract.request.family_id,
          requiredFields: [...contract.request.required_fields],
          rows,
        },
        lookup: lookupFromReferenceSeriesResponse(response, legacyLookup, rows),
        genericObservations: null,
      }
    }
    if (contract.request.data_kind === 'bars') {
      return {
        response,
        referenceSeries: null,
        genericObservations: null,
        lookup: lookupFromV2Response(response, legacyLookup, contract.request.required_fields),
      }
    }
    if (!declaredFamily || !contractMatchesDeclaredFamily(contract, declaredFamily)) {
      throw new Error('MARKET_DATA_GENERIC_FAMILY_CONTRACT_UNAVAILABLE')
    }
    const genericObservations = genericObservationResultFromV2Response(response, declaredFamily)
    return {
      response,
      referenceSeries: null,
      genericObservations,
      lookup: lookupFromGenericObservationResponse(response, legacyLookup),
    }
  }

  return {
    lookupShellForV2Query: (
      assetType: MarketAssetType,
      symbol: string,
      market: string,
      contract: MarketDataQueryContract | null,
      period = deps.form.period,
    ) => lookupShellForV2Query(assetType, symbol, market, contract, period),
    isMarketPageSelectableFamilyForAsset: (
      bundle: MarketDataQueryBundle | null,
      family: MarketDataQueryBundleFamily,
      assetType: MarketAssetType,
    ) => isMarketPageSelectableFamilyForBundle(bundle, family, assetType),
    queryContractForCurrentPeriod,
    queryContractForCurrentLookup,
    familyFromQueryBundle,
    defaultFamilyId,
    isMarketPageSelectableFamily,
    selectedMarketPageFamilyFromQueryBundle,
    marketPageFamilyLabel,
    selectDataFamily,
    contractMatchesDeclaredFamily,
    resolveV2QueryBundle,
    resolveV2QueryContract,
    lookupFromV2Response,
    lookupFromReferenceSeriesResponse,
    lookupFromGenericObservationResponse,
    setLegacyMarketDataPlatformStatus,
    setMarketDataPlatformErrorStatus,
    clearMarketDataFamilyScopedState,
    setMarketDataBundleUnconfiguredStatus,
    setMarketDataBundlePeriodUnsupportedStatus,
    setV2MarketDataPlatformStatus,
    queryAllV2MarketDataPages,
    queryV2FromLookupContract,
  }
}

export type MarketDataV2QueryModule = ReturnType<typeof useMarketDataV2Query>
export type { ComputedRef }
