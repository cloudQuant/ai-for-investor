import { computed, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  createMarketDataQueryFromContract,
  hasMarketDataCapabilities,
  hasMarketDataQueryContract,
  isMarketDataQueryV2FallbackError,
  marketDataApi,
  type MarketAssetType,
  type MarketDataCapabilitiesResponse,
  type MarketDataQueryContract,
  type MarketDataQueryResponse,
} from '@/api/marketData'
import type { DataPrecheckResponse } from '@/types/trust'
import { isRecord, parseResearchDate } from './aiResearchValueAdapters'

export interface AIResearchMarketDataPrecheckSnapshot {
  symbol: string
  assetType: MarketAssetType | undefined
  timeframe: string
  startDate: string | null
  endDate: string | null
  period: 'daily' | 'weekly' | 'monthly' | null
  window: { start: string; end: string } | null
}

interface AIResearchMarketDataForm {
  symbol: string
  symbol_name: string
  market_data_asset_type: '' | MarketAssetType
  timeframe: string
  start_date: string
  end_date: string
}

/**
 * The authenticated data service owns effective rollout state. Browser build
 * flags are intentionally not an authority: a stale bundle must never enable
 * a bridge that the serving backend has disabled, nor suppress an approved
 * strict-local bridge after the backend has enabled it.
 */
export function isAIResearchMarketDataPlatformBridgeEnabled(
  capabilities: MarketDataCapabilitiesResponse | null,
): boolean {
  return capabilities?.query_v2_enabled === true
    && capabilities.research_backtest_bridge_enabled === true
}

function isAIResearchMarketDataCacheFillEnabled(
  capabilities: MarketDataCapabilitiesResponse | null,
): boolean {
  return capabilities?.query_v2_enabled === true
    && capabilities.research_cache_fill_enabled === true
}

/**
 * Research needs a time-series bars contract. The browser uses this only to
 * verify the family returned by the server-owned control plane; the server
 * still resolves and issues the concrete contract for the selected symbol.
 *
 * Crypto's ``realtime`` family is a quote snapshot, so it cannot be used as
 * research bars. ``crypto.range`` is its dedicated bars family and remains
 * fail-closed until the server marks that product executable.
 */
const AI_RESEARCH_STRICT_BARS_FAMILY_IDS: Record<MarketAssetType, string> = {
  stock: 'stock.realtime',
  futures: 'futures.realtime',
  bond: 'bond.realtime',
  fund: 'fund.realtime',
  option: 'option.realtime',
  fx: 'fx.realtime',
  crypto: 'crypto.range',
}

function aiResearchStrictBarsFamilyId(assetType: MarketAssetType): string {
  return AI_RESEARCH_STRICT_BARS_FAMILY_IDS[assetType]
}

/**
 * Keep an explicit family lifecycle rejection separate from a transport or
 * rollout outage. A rejected unconfigured product must neither call the v2
 * query endpoint nor take a legacy fallback path.
 */
function isAIResearchMarketDataFamilyUnconfiguredError(error: unknown): boolean {
  if (!error || typeof error !== 'object') return false
  const response = (error as { response?: { data?: unknown } }).response
  const data = response?.data
  if (!data || typeof data !== 'object') return false
  const record = data as Record<string, unknown>
  const detail = record.detail
  const details = record.details
  const detailCode = detail && typeof detail === 'object'
    ? (detail as Record<string, unknown>).code
    : undefined
  const detailsCode = details && typeof details === 'object'
    ? (details as Record<string, unknown>).code
    : undefined
  return [record.code, detailCode, detailsCode].some(code => code === 'DATA_FAMILY_UNCONFIGURED')
}

export function useAIResearchMarketData({ t, aiResearchForm }: {
  t: (key: string) => string
  aiResearchForm: AIResearchMarketDataForm
}) {

  const aiResearchMarketDataCapabilities = ref<MarketDataCapabilitiesResponse | null>(null)

  const aiResearchMarketDataPlatformBridgeEnabled = computed(() => (
    isAIResearchMarketDataPlatformBridgeEnabled(aiResearchMarketDataCapabilities.value)
  ))

  const aiResearchMarketDataCacheFillEnabled = computed(() => (
    isAIResearchMarketDataCacheFillEnabled(aiResearchMarketDataCapabilities.value)
  ))

  let aiResearchMarketDataCapabilitiesResolved = false

  let aiResearchMarketDataCapabilitiesRequest: Promise<MarketDataCapabilitiesResponse | null> | null = null

  let aiResearchMarketDataCapabilitiesRequestGeneration = 0

  const aiResearchPrecheckLoading = ref(false)

  const aiResearchCacheFillLoading = ref(false)

  const aiResearchPrecheckResult = ref<DataPrecheckResponse | null>(null)

  const aiResearchPrecheckError = ref('')

  const aiResearchMarketDataPlatformStatus = ref<AIResearchMarketDataPlatformStatus>({
    path: 'legacy',
    provider: null,
    coverageStatus: null,
    coverageRatio: null,
    queryId: null,
    detail: null,
  })

  const aiResearchMarketDataQueryContracts = new Map<string, MarketDataQueryContract>()

  const AI_RESEARCH_PRECHECK_DEBOUNCE_MS = 350

  let aiResearchPrecheckTimer: ReturnType<typeof setTimeout> | null = null

  let aiResearchPrecheckController: AbortController | null = null

  let aiResearchPrecheckSequence = 0

  let aiResearchCacheFillSequence = 0

  type AIResearchMarketDataPlatformStatus = {
    path: (
      | 'legacy'
      | 'strict_local'
      | 'local_first'
      | 'provider_persisted'
      | 'legacy_fallback'
      | 'unsupported'
      | 'error'
    )
    provider: string | null
    coverageStatus: string | null
    coverageRatio: number | null
    queryId: string | null
    detail: string | null
  }

  const aiResearchMarketDataAssetTypeOptions: ReadonlyArray<{
    value: MarketAssetType
    label: string
  }> = [
    { value: 'stock', label: t('strategy.aiResearchAssetTypes.stock') },
    { value: 'futures', label: t('strategy.aiResearchAssetTypes.futures') },
    { value: 'bond', label: t('strategy.aiResearchAssetTypes.bond') },
    { value: 'fund', label: t('strategy.aiResearchAssetTypes.fund') },
    { value: 'option', label: t('strategy.aiResearchAssetTypes.option') },
    { value: 'fx', label: t('strategy.aiResearchAssetTypes.fx') },
    { value: 'crypto', label: t('strategy.aiResearchAssetTypes.crypto') },
  ]

  const aiResearchPrecheckTagType = computed(() => {
    if (aiResearchPrecheckError.value) return 'danger'
    const status = aiResearchPrecheckResult.value?.status
    if (status === 'pass') return 'success'
    if (status === 'failed') return 'danger'
    if (status === 'warning') return 'warning'
    return 'info'
  })

  const aiResearchPrecheckSummary = computed(() => {
    if (aiResearchPrecheckError.value) return aiResearchPrecheckError.value
    const result = aiResearchPrecheckResult.value
    if (!result) return '未预检'
    const issueCount = (result.reasons?.length || 0) + (result.warnings?.length || 0)
    const label = result.passed ? '预检通过' : '预检未通过'
    return issueCount ? `${label} · ${issueCount} 项` : label
  })

  const aiResearchMarketDataPlatformTagType = computed<'success' | 'warning' | 'danger' | 'info'>(() => {
    const path = aiResearchMarketDataPlatformStatus.value.path
    if (path === 'strict_local' || path === 'local_first' || path === 'provider_persisted') return 'success'
    if (path === 'error') return 'danger'
    if (path === 'legacy_fallback' || path === 'unsupported') return 'warning'
    return 'info'
  })

  const aiResearchMarketDataPlatformSummary = computed(() => {
    const status = aiResearchMarketDataPlatformStatus.value
    if (status.path === 'strict_local') {
      const ratio = status.coverageRatio === null ? '-' : `${(status.coverageRatio * 100).toFixed(2)}%`
      const provider = status.provider ? ` · ${status.provider}` : ''
      return `数据中台严格本地预检${provider} · ${status.coverageStatus || 'unknown'} · ${ratio}`
    }
    if (status.path === 'provider_persisted') {
      const ratio = status.coverageRatio === null ? '-' : `${(status.coverageRatio * 100).toFixed(2)}%`
      const provider = status.provider ? ` · ${status.provider}` : ''
      return `数据中台已补齐并持久化${provider} · ${status.coverageStatus || 'unknown'} · ${ratio}`
    }
    if (status.path === 'local_first') {
      const ratio = status.coverageRatio === null ? '-' : `${(status.coverageRatio * 100).toFixed(2)}%`
      const provider = status.provider ? ` · ${status.provider}` : ''
      return `数据中台本地优先预检${provider} · ${status.coverageStatus || 'unknown'} · ${ratio}`
    }
    if (status.path === 'legacy_fallback') return '数据中台不可用，已保留原预检'
    if (status.path === 'unsupported') return '当前标的尚无数据中台契约'
    if (status.path === 'error') return '数据中台预检异常，原预检结果未改变'
    return '原数据预检'
  })

  function aiResearchStrictMarketDataRunBlockReasonForStatus(
    status: AIResearchMarketDataPlatformStatus,
  ): string {
    if (status.path === 'strict_local') return ''
    if (status.path === 'legacy') {
      return '严格本地市场数据预检尚未完成，无法运行 AI 策略'
    }
    if (status.path === 'unsupported') {
      return `严格本地市场数据预检被阻断：${status.detail || '当前标的尚无数据中台契约'}`
    }
    if (status.path === 'legacy_fallback') {
      return '严格本地市场数据预检不可用，无法运行 AI 策略'
    }
    if (status.detail === 'MARKET_DATA_STRICT_LOCAL_INCOMPLETE') {
      const coverage = status.coverageRatio === null
        ? ''
        : `（覆盖率 ${(status.coverageRatio * 100).toFixed(2)}%）`
      return `严格本地市场数据覆盖不完整${coverage}，无法运行 AI 策略`
    }
    return `严格本地市场数据预检被阻断：${status.detail || '预检未通过'}`
  }

  const aiResearchStrictMarketDataRunBlockReason = computed(() => {
    if (!aiResearchMarketDataPlatformBridgeEnabled.value) return ''
    if (aiResearchPrecheckLoading.value) {
      return '严格本地市场数据预检正在进行，请等待预检完成后再运行'
    }
    return aiResearchStrictMarketDataRunBlockReasonForStatus(
      aiResearchMarketDataPlatformStatus.value,
    )
  })

  const aiResearchStrictMarketDataRunBlocked = computed(() => (
    aiResearchStrictMarketDataRunBlockReason.value.length > 0
  ))

  function aiResearchAssetTypeForSymbol(symbol: string): MarketAssetType | undefined {
    const normalized = symbol.trim().toUpperCase()
    if (isAIResearchFuturesSymbol(normalized)) return 'futures'
    if (/(USDT|USDC|PERP|SWAP|BTC|ETH)/.test(normalized)) return 'crypto'
    if (/\.(SZ|SH|BJ)$/.test(normalized) || /^\d{6}$/.test(normalized)) return 'stock'
    return undefined
  }

  function isAIResearchMarketDataAssetType(value: unknown): value is MarketAssetType {
    return aiResearchMarketDataAssetTypeOptions.some(option => option.value === value)
  }

  function aiResearchSelectedMarketDataAssetType(): MarketAssetType | undefined {
    const value = aiResearchForm.market_data_asset_type
    return isAIResearchMarketDataAssetType(value) ? value : undefined
  }

  function aiResearchResolvedMarketDataAssetType(symbol: string): MarketAssetType | undefined {
    return aiResearchSelectedMarketDataAssetType() ?? aiResearchAssetTypeForSymbol(symbol)
  }

  function aiResearchMarketDataAssetTypeFromDataConfig(value: unknown): '' | MarketAssetType {
    if (!isRecord(value)) return ''
    const assetType = value.market_data_asset_type
    return isAIResearchMarketDataAssetType(assetType) ? assetType : ''
  }

  function aiResearchPrecheckAssetType(): MarketAssetType | undefined {
    return aiResearchResolvedMarketDataAssetType(aiResearchForm.symbol)
  }

  function aiResearchLegacyPeriod(): 'daily' | 'weekly' | 'monthly' | null {
    if (aiResearchForm.timeframe === '1d') return 'daily'
    if (aiResearchForm.timeframe === '1w') return 'weekly'
    if (aiResearchForm.timeframe === '1mo') return 'monthly'
    return null
  }

  function aiResearchQueryWindow(): { start: string; end: string } | null {
    const start = parseResearchDate(aiResearchForm.start_date)
    const endInclusive = parseResearchDate(aiResearchForm.end_date)
    if (!start || !endInclusive || start > endInclusive) return null
    endInclusive.setUTCDate(endInclusive.getUTCDate() + 1)
    return { start: start.toISOString(), end: endInclusive.toISOString() }
  }

  function captureAIResearchMarketDataPrecheckSnapshot(): AIResearchMarketDataPrecheckSnapshot | null {
    const symbol = aiResearchForm.symbol.trim()
    if (!symbol) return null
    return {
      symbol,
      assetType: aiResearchResolvedMarketDataAssetType(symbol),
      timeframe: aiResearchForm.timeframe,
      startDate: aiResearchForm.start_date || null,
      endDate: aiResearchForm.end_date || null,
      period: aiResearchLegacyPeriod(),
      window: aiResearchQueryWindow(),
    }
  }

  function aiResearchQueryContractKey(
    assetType: MarketAssetType,
    symbol: string,
    period: 'daily' | 'weekly' | 'monthly',
  ): string {
    // The server resolves exact imported symbols and deliberately does not
    // case-fold identifiers. Preserve that boundary in the client cache so
    // an earlier contract can never be reused for a different instrument.
    return `${assetType}:${symbol.trim()}:${period}`
  }

  function setAIResearchMarketDataPlatformStatus(
    status: Partial<AIResearchMarketDataPlatformStatus> & Pick<AIResearchMarketDataPlatformStatus, 'path'>,
  ): AIResearchMarketDataPlatformStatus {
    const nextStatus: AIResearchMarketDataPlatformStatus = {
      provider: null,
      coverageStatus: null,
      coverageRatio: null,
      queryId: null,
      detail: null,
      ...status,
    }
    aiResearchMarketDataPlatformStatus.value = nextStatus
    return nextStatus
  }

  /**
   * Read authenticated, server-owned rollout state. Page load and passive
   * prechecks may use the most recently resolved value, while any action that
   * submits or continues research forces a fresh authorization decision.
   *
   * An absent, malformed, or failed response remains null. A client that has
   * never received an enabled server capability can keep the Iteration 196
   * path active; a submit-time caller that has already received an enabled
   * capability treats that null as an unavailable strict-data authorization
   * and blocks rather than silently downgrading its known gate.
   */
  async function resolveAIResearchMarketDataCapabilities(
    { forceRefresh = false }: { forceRefresh?: boolean } = {},
  ): Promise<MarketDataCapabilitiesResponse | null> {
    if (!forceRefresh && aiResearchMarketDataCapabilitiesResolved) {
      return aiResearchMarketDataCapabilities.value
    }
    if (!forceRefresh && aiResearchMarketDataCapabilitiesRequest) {
      return aiResearchMarketDataCapabilitiesRequest
    }

    const requestGeneration = ++aiResearchMarketDataCapabilitiesRequestGeneration
    const request = marketDataApi.getCapabilities()
      .then((value: unknown) => (hasMarketDataCapabilities(value) ? value : null))
      .catch(() => null)
      .then(capabilities => {
        // A forced submit-time read can supersede a still-pending page-load
        // request. Do not let that older response restore stale authority.
        if (requestGeneration === aiResearchMarketDataCapabilitiesRequestGeneration) {
          // Do not erase a previously authenticated enabled capability on a
          // transport or schema failure. It remains a safety constraint for
          // submit-time callers, but cannot itself authorize a new request.
          if (capabilities) {
            aiResearchMarketDataCapabilities.value = capabilities
          }
          aiResearchMarketDataCapabilitiesResolved = true
        }
        return capabilities
      })
    aiResearchMarketDataCapabilitiesRequest = request
    try {
      return await request
    } finally {
      if (aiResearchMarketDataCapabilitiesRequest === request) {
        aiResearchMarketDataCapabilitiesRequest = null
      }
    }
  }

  function isAIResearchMarketDataContractCompatible(
    contract: MarketDataQueryContract,
    assetType: MarketAssetType,
    period: 'daily' | 'weekly' | 'monthly',
  ): boolean {
    const expectedFrequency = period === 'daily' ? '1d' : period === 'weekly' ? '1w' : '1mo'
    return contract.request.data_kind === 'bars'
      && contract.request.frequency === expectedFrequency
      && contract.request.family_id === aiResearchStrictBarsFamilyId(assetType)
      && contract.request.family_contract_version === 'market-data-family-v1'
  }

  /**
   * A strategy-research precheck may display strict-local evidence only when
   * the response is bound to the exact server-issued contract.  This is a
   * runtime check because an upgraded frontend can still receive a stale or
   * mixed-deployment HTTP payload despite its TypeScript declaration.
   */
  function isAIResearchMarketDataResponseCompatible(
    response: MarketDataQueryResponse,
    contract: MarketDataQueryContract,
    assetType: MarketAssetType,
    period: 'daily' | 'weekly' | 'monthly',
  ): boolean {
    const expectedFrequency = period === 'daily' ? '1d' : period === 'weekly' ? '1w' : '1mo'
    const request = contract.request
    return typeof response.canonical_id === 'string'
      && response.canonical_id === request.identity.canonical_id
      && typeof response.dataset_code === 'string'
      && response.dataset_code === request.dataset_code
      && response.asset_type === assetType
      && typeof response.instrument_metadata_version === 'string'
      && response.instrument_metadata_version.trim().length > 0
      && response.data_kind === request.data_kind
      && response.frequency === expectedFrequency
      && response.frequency === request.frequency
      && response.source_policy_id === request.source_policy_id
      && response.family_id === request.family_id
      && response.family_contract_version === request.family_contract_version
  }

  async function resolveAIResearchMarketDataContract(
    assetType: MarketAssetType,
    symbol: string,
    period: 'daily' | 'weekly' | 'monthly',
  ): Promise<MarketDataQueryContract | null> {
    const key = aiResearchQueryContractKey(assetType, symbol, period)
    const cached = aiResearchMarketDataQueryContracts.get(key)
    if (cached && isAIResearchMarketDataContractCompatible(cached, assetType, period)) return cached
    if (cached) aiResearchMarketDataQueryContracts.delete(key)

    const expectedFamilyId = aiResearchStrictBarsFamilyId(assetType)
    const contract = await marketDataApi.getQueryContract({
      asset_type: assetType,
      symbol,
      period,
      family_id: expectedFamilyId,
    })
    if (!hasMarketDataQueryContract(contract)) return null
    if (!isAIResearchMarketDataContractCompatible(contract, assetType, period)) {
      return null
    }
    aiResearchMarketDataQueryContracts.set(key, contract)
    return contract
  }

  async function runAIResearchMarketDataPlatformPrecheck(
    snapshot: AIResearchMarketDataPrecheckSnapshot,
    controller: AbortController,
    {
      fillLocalCache = false,
      forceStrictLocalReread = false,
      capabilities: preResolvedCapabilities,
    }: {
      fillLocalCache?: boolean
      forceStrictLocalReread?: boolean
      capabilities?: MarketDataCapabilitiesResponse | null
    } = {},
  ): Promise<AIResearchMarketDataPlatformStatus | null> {
    const capabilities = preResolvedCapabilities === undefined
      ? await resolveAIResearchMarketDataCapabilities()
      : preResolvedCapabilities
    if (controller.signal.aborted) return null
    if (
      fillLocalCache
        ? !isAIResearchMarketDataCacheFillEnabled(capabilities)
        : !forceStrictLocalReread
          && !isAIResearchMarketDataPlatformBridgeEnabled(capabilities)
    ) return null

    const { assetType, symbol, period, window } = snapshot
    if (!assetType || !period || !window) {
      return setAIResearchMarketDataPlatformStatus({
        path: 'unsupported',
        detail: 'TYPED_QUERY_CONTRACT_UNAVAILABLE',
      })
    }
    let contractIssued = false
    try {
      const contract = await resolveAIResearchMarketDataContract(assetType, symbol, period)
      if (controller.signal.aborted) return null
      if (!contract) {
        return setAIResearchMarketDataPlatformStatus({
          path: 'unsupported',
          detail: 'TYPED_QUERY_CONTRACT_UNAVAILABLE',
        })
      }
      contractIssued = true
      // Both scheduled and interactive prechecks are deliberately strict-local
      // so inspecting a research form never starts an external provider
      // request. Only the separate, explicit cache-fill action may use the
      // reviewed local-first collection purpose. It persists independently
      // validated market facts only; it never creates an Iteration 196
      // research/backtest artifact or approval input.
      const executionOptions = fillLocalCache
        ? {
            mode: 'local_first' as const,
            purpose: 'research_cache_fill' as const,
            consistency: 'display' as const,
            page_size: 500,
          }
        : {
            mode: 'local_only' as const,
            purpose: 'research' as const,
            consistency: 'strict' as const,
            knowledge_cutoff: new Date().toISOString(),
            page_size: 500,
          }
      const response: MarketDataQueryResponse = await marketDataApi.queryLocalFirst(
        createMarketDataQueryFromContract(contract, {
          ...window,
          ...executionOptions,
        }),
        { signal: controller.signal, suppressErrorMessage: true },
      )
      if (controller.signal.aborted) return null
      if (!isAIResearchMarketDataResponseCompatible(response, contract, assetType, period)) {
        return setAIResearchMarketDataPlatformStatus({
          path: 'error',
          queryId: typeof response.query_id === 'string' ? response.query_id : null,
          detail: 'MARKET_DATA_STRICT_LOCAL_RESPONSE_MISMATCH',
        })
      }
      if (response.coverage.status !== 'complete') {
        return setAIResearchMarketDataPlatformStatus({
          path: 'error',
          coverageStatus: response.coverage.status,
          coverageRatio: response.coverage.coverage_ratio,
          queryId: response.query_id,
          detail: 'MARKET_DATA_STRICT_LOCAL_INCOMPLETE',
        })
      }
      const lastFetch = response.fetches[response.fetches.length - 1]
      return setAIResearchMarketDataPlatformStatus({
        path: fillLocalCache
          ? response.fetches.length > 0
            ? 'provider_persisted'
            : 'local_first'
          : 'strict_local',
        provider: lastFetch?.provider_id || null,
        coverageStatus: response.coverage.status,
        coverageRatio: response.coverage.coverage_ratio,
        queryId: response.query_id,
      })
    } catch (error) {
      if (controller.signal.aborted) return null
      if (!contractIssued && isAIResearchMarketDataFamilyUnconfiguredError(error)) {
        return setAIResearchMarketDataPlatformStatus({
          path: 'unsupported',
          detail: 'DATA_FAMILY_UNCONFIGURED',
        })
      }
      if (!contractIssued && isMarketDataQueryV2FallbackError(error)) {
        return setAIResearchMarketDataPlatformStatus({
          path: 'legacy_fallback',
          detail: 'MARKET_DATA_QUERY_V2_UNAVAILABLE',
        })
      }
      return setAIResearchMarketDataPlatformStatus({
        path: 'error',
        detail: 'MARKET_DATA_QUERY_V2_PRECHECK_FAILED',
      })
    }
  }

  async function runAIResearchDataPrecheck(
    {
      interactive = true,
      forceStrictLocalReread = false,
    }: {
      interactive?: boolean
      forceStrictLocalReread?: boolean
    } = {},
  ) {
    const snapshot = captureAIResearchMarketDataPrecheckSnapshot()
    if (!snapshot) {
      if (interactive) ElMessage.warning(t('strategy.aiResearchSymbolRequired'))
      return
    }
    const requestSequence = ++aiResearchPrecheckSequence
    aiResearchPrecheckController?.abort()
    const controller = new AbortController()
    aiResearchPrecheckController = controller
    aiResearchPrecheckLoading.value = true
    aiResearchPrecheckError.value = ''
    try {
      // Capability is only needed for the optional Iteration 197 sidecar.
      // Start the established Iteration 196 precheck immediately so a delayed
      // rollout-state read cannot turn a debounced input edit into a silent
      // no-op. The snapshot/sequence fence below still governs both results.
      const capabilitiesRequest = resolveAIResearchMarketDataCapabilities()
      const result = await marketDataApi.runPrecheck({
        asset_type: snapshot.assetType,
        symbol: snapshot.symbol,
        timeframe: snapshot.timeframe,
        start_date: snapshot.startDate,
        end_date: snapshot.endDate,
      }, { signal: controller.signal })
      if (requestSequence !== aiResearchPrecheckSequence) return
      aiResearchPrecheckResult.value = result
      const capabilities = await capabilitiesRequest
      if (requestSequence !== aiResearchPrecheckSequence || controller.signal.aborted) return
      // The Iteration 196 precheck remains authoritative. The Iteration 197
      // sidecar can issue a strict-local v2 control-plane or fact request only
      // when the authenticated backend has enabled that bridge.
      if (
        forceStrictLocalReread
        || isAIResearchMarketDataPlatformBridgeEnabled(capabilities)
      ) {
        await runAIResearchMarketDataPlatformPrecheck(snapshot, controller, {
          fillLocalCache: false,
          forceStrictLocalReread,
        })
      } else {
        setAIResearchMarketDataPlatformStatus({ path: 'legacy' })
      }
      if (interactive) {
        if (result.passed) {
          ElMessage.success(t('strategy.aiResearchPrecheckPassed'))
        } else {
          ElMessage.warning(t('strategy.aiResearchPrecheckBlocked'))
        }
      }
    } catch {
      if (requestSequence !== aiResearchPrecheckSequence || controller.signal.aborted) return
      aiResearchPrecheckResult.value = null
      aiResearchPrecheckError.value = '预检失败'
      if (interactive) ElMessage.error(t('strategy.aiResearchPrecheckFailed'))
    } finally {
      if (requestSequence === aiResearchPrecheckSequence) {
        aiResearchPrecheckLoading.value = false
      }
    }
  }

  async function warmAIResearchLocalCache() {
    const snapshot = captureAIResearchMarketDataPrecheckSnapshot()
    if (!snapshot) {
      ElMessage.warning(t('strategy.aiResearchSymbolRequired'))
      return
    }

    const requestSequence = ++aiResearchPrecheckSequence
    const cacheFillSequence = ++aiResearchCacheFillSequence
    aiResearchPrecheckController?.abort()
    const controller = new AbortController()
    aiResearchPrecheckController = controller
    aiResearchCacheFillLoading.value = true
    aiResearchPrecheckError.value = ''
    try {
      const capabilities = await resolveAIResearchMarketDataCapabilities({ forceRefresh: true })
      if (requestSequence !== aiResearchPrecheckSequence || controller.signal.aborted) return
      if (!isAIResearchMarketDataCacheFillEnabled(capabilities)) return

      await runAIResearchMarketDataPlatformPrecheck(
        snapshot,
        controller,
        { fillLocalCache: true },
      )
      if (requestSequence !== aiResearchPrecheckSequence || controller.signal.aborted) return

      const cacheFillPath = aiResearchMarketDataPlatformStatus.value.path
      if (cacheFillPath !== 'provider_persisted' && cacheFillPath !== 'local_first') return

      // A successful collection receipt only proves that market facts were
      // persisted. Re-read the exact frozen v2 query strictly locally. This
      // must not call or rewrite the Iteration 196 precheck: cache filling is
      // independent of the backtest bridge and is never a research artifact.
      await runAIResearchMarketDataPlatformPrecheck(snapshot, controller, {
        fillLocalCache: false,
        forceStrictLocalReread: true,
      })
    } finally {
      if (cacheFillSequence === aiResearchCacheFillSequence) {
        aiResearchCacheFillLoading.value = false
      }
    }
  }

  function scheduleAIResearchDataPrecheck() {
    if (aiResearchPrecheckTimer !== null) clearTimeout(aiResearchPrecheckTimer)
    // Invalidate the in-flight result as soon as an input changes, rather
    // than after the next debounced request starts. This prevents an old
    // symbol's successful response from briefly replacing the precheck while
    // the user is already editing a different asset.
    aiResearchPrecheckSequence += 1
    aiResearchCacheFillSequence += 1
    aiResearchPrecheckController?.abort()
    aiResearchPrecheckController = null
    aiResearchPrecheckLoading.value = false
    aiResearchCacheFillLoading.value = false
    setAIResearchMarketDataPlatformStatus({ path: 'legacy' })
    if (!aiResearchForm.symbol.trim()) return
    aiResearchPrecheckTimer = setTimeout(() => {
      aiResearchPrecheckTimer = null
      void runAIResearchDataPrecheck({ interactive: false })
    }, AI_RESEARCH_PRECHECK_DEBOUNCE_MS)
  }

  const AI_RESEARCH_FUTURES_PREFIXES = [
    'IF', 'IC', 'IH', 'IM', 'T', 'TF', 'TL', 'TS',
    'AU', 'AG', 'CU', 'AL', 'ZN', 'PB', 'NI', 'SN', 'AO', 'RB', 'HC', 'SS',
    'BU', 'RU', 'BR', 'FU', 'SP', 'WR',
    'SC', 'LU', 'NR', 'BC', 'EC',
    'A', 'B', 'C', 'CS', 'EB', 'EG', 'I', 'J', 'JD', 'JM', 'L', 'LH',
    'M', 'P', 'PG', 'PP', 'RR', 'V', 'Y',
    'SA', 'FG', 'MA', 'TA', 'SR', 'CF', 'OI', 'RM', 'AP', 'CJ', 'CY',
    'PF', 'PK', 'SF', 'SM', 'UR', 'WH', 'ZC',
    'SI', 'LC',
  ].sort((left, right) => right.length - left.length)

  function isAIResearchFuturesSymbol(symbol: string) {
    const normalized = symbol.trim().toUpperCase()
    if (!normalized) return false
    if (/\.(CFE|CFFEX|SHFE|INE|DCE|CZCE|GFEX)$/.test(normalized)) return true
    return AI_RESEARCH_FUTURES_PREFIXES.some(prefix => {
      if (!normalized.startsWith(prefix)) return false
      const suffix = normalized.slice(prefix.length)
      if (/\d/.test(suffix)) return true
      return !suffix && prefix.length >= 2
    })
  }

  function aiResearchAssetConstraintLine() {
    const assetType = aiResearchResolvedMarketDataAssetType(aiResearchForm.symbol)
    if (assetType === 'futures') {
      return '按期货/合约资产处理，必须使用交易所或本地资产规格中的合约乘数、保证金、杠杆、最小变动价位和真实手续费估算仓位与风险。'
    }
    if (assetType === 'crypto') {
      return '按数字资产或永续合约处理，必须显式考虑资金费率、杠杆、滑点、交易费率和保证金约束。'
    }
    if (assetType === 'stock') {
      return '按股票资产处理，必须控制单票仓位、换手率、手续费和不可成交假设，避免过度交易。'
    }
    if (assetType === 'bond') {
      return '按债券资产处理，必须使用久期、票息、应计利息、到期收益率、流动性和交易成本约束评估仓位与风险。'
    }
    if (assetType === 'fund') {
      return '按基金或 ETF 资产处理，必须区分净值与二级市场价格，并考虑跟踪误差、申赎、流动性和交易成本。'
    }
    if (assetType === 'option') {
      return '按期权资产处理，必须使用到期日、行权价、合约乘数、Greeks、隐含波动率、保证金和流动性约束评估风险。'
    }
    if (assetType === 'fx') {
      return '按外汇资产处理，必须明确货币对方向、报价精度、点差、隔夜利息、交易时段和杠杆约束。'
    }
    return '必须从交易所或本地资产规格读取手续费、合约乘数、保证金、价格精度和最小下单量，并在仓位 sizing 中使用这些约束。'
  }

  onUnmounted(() => {
    if (aiResearchPrecheckTimer !== null) clearTimeout(aiResearchPrecheckTimer)
    aiResearchPrecheckController?.abort()
  })

  return {
    aiResearchMarketDataCapabilities,
    aiResearchMarketDataPlatformBridgeEnabled,
    aiResearchMarketDataCacheFillEnabled,
    aiResearchMarketDataPlatformStatus,
    aiResearchMarketDataAssetTypeOptions,
    aiResearchPrecheckLoading,
    aiResearchCacheFillLoading,
    aiResearchPrecheckResult,
    aiResearchPrecheckError,
    aiResearchPrecheckTagType,
    aiResearchPrecheckSummary,
    aiResearchMarketDataPlatformTagType,
    aiResearchMarketDataPlatformSummary,
    aiResearchStrictMarketDataRunBlockReason,
    aiResearchStrictMarketDataRunBlocked,
    aiResearchStrictMarketDataRunBlockReasonForStatus,
    isAIResearchMarketDataPlatformBridgeEnabled,
    isAIResearchMarketDataAssetType,
    aiResearchAssetTypeForSymbol,
    aiResearchResolvedMarketDataAssetType,
    aiResearchMarketDataAssetTypeFromDataConfig,
    aiResearchPrecheckAssetType,
    aiResearchLegacyPeriod,
    aiResearchQueryWindow,
    captureAIResearchMarketDataPrecheckSnapshot,
    aiResearchQueryContractKey,
    setAIResearchMarketDataPlatformStatus,
    resolveAIResearchMarketDataCapabilities,
    resolveAIResearchMarketDataContract,
    runAIResearchMarketDataPlatformPrecheck,
    runAIResearchDataPrecheck,
    warmAIResearchLocalCache,
    scheduleAIResearchDataPrecheck,
    AI_RESEARCH_FUTURES_PREFIXES,
    isAIResearchFuturesSymbol,
    aiResearchAssetConstraintLine,
  }
}
