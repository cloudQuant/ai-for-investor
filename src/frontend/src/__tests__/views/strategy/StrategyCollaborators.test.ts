import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent, h, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { Router } from 'vue-router'
import { useAIResearchMarketData } from '@/views/strategy/useAIResearchMarketData'
import { useAIResearchRunRecordAdapters } from '@/views/strategy/useAIResearchRunRecordAdapters'
import {
  useAIResearchRuntimeOperations,
  type AIResearchRuntimeOperationsOptions,
} from '@/views/strategy/useAIResearchRuntimeOperations'
import { useStrategyPageDialogs } from '@/views/strategy/useStrategyPageDialogs'
import type { useStrategyStore } from '@/stores/strategy'
import type {
  AIStrategyLiveHandoffPackage,
  AIStrategyPaperTradingReview,
  AIStrategyPaperTradingStart,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
  AIStrategyResearchTaskResponse,
} from '@/api/strategy'
import type { Strategy } from '@/types'

const marketDataMocks = vi.hoisted(() => ({
  getCapabilities: vi.fn(),
  runPrecheck: vi.fn(),
  getQueryContract: vi.fn(),
  queryLocalFirst: vi.fn(),
}))

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  confirm: vi.fn(),
}))

const strategyApiMocks = vi.hoisted(() => ({
  getTemplateReadme: vi.fn(),
  startAIResearchPaperTrading: vi.fn(),
}))

vi.mock('@/api/marketData', () => ({
  createMarketDataQueryFromContract: vi.fn(),
  hasMarketDataCapabilities: (value: unknown) => Boolean(value && typeof value === 'object'),
  hasMarketDataQueryContract: vi.fn(() => false),
  isMarketDataQueryV2FallbackError: vi.fn(() => false),
  marketDataApi: marketDataMocks,
}))

vi.mock('element-plus', () => ({
  ElMessage: {
    success: messageMocks.success,
    error: messageMocks.error,
    warning: messageMocks.warning,
  },
  ElMessageBox: { confirm: messageMocks.confirm },
}))

vi.mock('@/api/strategy', () => ({
  strategyApi: strategyApiMocks,
}))

describe('strategy page collaborators', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    marketDataMocks.getCapabilities.mockResolvedValue({
      query_v2_enabled: true,
      research_backtest_bridge_enabled: true,
      research_cache_fill_enabled: false,
    })
    marketDataMocks.runPrecheck.mockResolvedValue({
      passed: true,
      status: 'pass',
      reasons: [],
      warnings: [],
    })
    marketDataMocks.getQueryContract.mockRejectedValue({
      response: { data: { code: 'DATA_FAMILY_UNCONFIGURED' } },
    })
    marketDataMocks.queryLocalFirst.mockResolvedValue({})
    messageMocks.confirm.mockResolvedValue('confirm')
  })

  it('keeps a rejected market data family unsupported without issuing a query fallback', async () => {
    let marketData!: ReturnType<typeof useAIResearchMarketData>
    const wrapper = mount(defineComponent({
      setup() {
        marketData = useAIResearchMarketData({
          t: key => key,
          aiResearchForm: reactive({
            symbol: 'IF2406',
            symbol_name: '',
            market_data_asset_type: 'futures' as const,
            timeframe: '1d',
            start_date: '2024-01-01',
            end_date: '2024-01-31',
          }),
        })
        return () => h('div')
      },
    }))

    await marketData.runAIResearchDataPrecheck({ interactive: false })

    expect(marketData.aiResearchMarketDataPlatformStatus.value).toMatchObject({
      path: 'unsupported',
      detail: 'DATA_FAMILY_UNCONFIGURED',
    })
    expect(marketDataMocks.getQueryContract).toHaveBeenCalledWith({
      asset_type: 'futures',
      symbol: 'IF2406',
      period: 'daily',
      family_id: 'futures.realtime',
    })
    expect(marketDataMocks.runPrecheck).toHaveBeenCalledTimes(1)
    expect(marketDataMocks.queryLocalFirst).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('resets save state and leaves the form open when strategy creation rejects', async () => {
    const createStrategy = vi.fn().mockRejectedValue(new Error('create failed'))
    const strategyStore = {
      createStrategy,
      updateStrategy: vi.fn(),
      deleteStrategy: vi.fn(),
    } as unknown as ReturnType<typeof useStrategyStore>
    const page = useStrategyPageDialogs({
      t: key => key,
      router: { push: vi.fn() } as unknown as Router,
      strategyStore,
      activeTab: ref<string>('gallery'),
    })
    page.showCreateDialog()
    Object.assign(page.form, { name: 'Failure strategy', code: 'def run(): pass' })

    await expect(page.saveStrategy()).rejects.toThrow('create failed')

    expect(page.saving.value).toBe(false)
    expect(page.dialogVisible.value).toBe(true)
    expect(createStrategy).toHaveBeenCalledTimes(1)
    expect(ElMessage.success).not.toHaveBeenCalled()
  })

  it('does not delete a strategy when the confirmation dialog rejects', async () => {
    const deleteStrategy = vi.fn()
    const strategyStore = {
      createStrategy: vi.fn(),
      updateStrategy: vi.fn(),
      deleteStrategy,
    } as unknown as ReturnType<typeof useStrategyStore>
    const page = useStrategyPageDialogs({
      t: key => key,
      router: { push: vi.fn() } as unknown as Router,
      strategyStore,
      activeTab: ref<string>('gallery'),
    })
    messageMocks.confirm.mockRejectedValueOnce(new Error('cancelled'))

    await expect(page.deleteStrategy('strategy-1')).rejects.toThrow('cancelled')

    expect(deleteStrategy).not.toHaveBeenCalled()
  })

  it('returns no restored result for a task without a run identity or workspace', () => {
    const runAdapters = useAIResearchRunRecordAdapters({
      minPaperTradingDays: 7,
      runtimeAssetSpecsPayload: () => ({}),
      runtimeEnvironmentPayload: () => ({}),
      bestIterationPayloadForRecord: () => null,
      bestStrategyFromRunRecord: () => null,
      fallbackSnapshotStrategyId: (record: AIStrategyResearchRunRecord) => `${record.run_id}-strategy`,
      iterationStrategyPayload: () => ({}),
      iterationUnitPayload: () => ({}),
      iterationRunResultPayload: () => ({}),
      iterationUnitStatusPayload: () => ({}),
      validationWindowFromUnknown: () => null,
      promotionAuditFromPayload: () => [],
      hydrateLiveHandoffFromRunRecord: vi.fn(),
      liveTradingPreparedAtFromPipeline: () => '',
    })

    expect(runAdapters.researchResultFromTaskSummary({} as AIStrategyResearchTaskResponse)).toBeNull()
  })

  it('clears the paper-start loading state and refreshes history after a runtime request fails', async () => {
    const options = createRuntimeOperationsOptions()
    const operations = useAIResearchRuntimeOperations(options)
    const record = {
      run_id: 'run-1',
      research_workspace_id: 'workspace-1',
    } as AIStrategyResearchRunRecord
    strategyApiMocks.startAIResearchPaperTrading.mockRejectedValueOnce(new Error('offline'))

    await operations.startPaperFromResearchRecord(record)

    expect(options.aiResearchPaperStartingRunId.value).toBe('')
    expect(options.refreshAIResearchRunRecord).toHaveBeenCalledWith('run-1', 'workspace-1')
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })
})

function createRuntimeOperationsOptions(): AIResearchRuntimeOperationsOptions {
  return {
    t: key => key,
    aiResearchPaperStartingRunId: ref(''),
    aiResearchStrategyViewingRunId: ref(''),
    aiResearchPaperReviewingRunId: ref(''),
    aiResearchLiveHandoffLoadingRunId: ref(''),
    aiResearchLiveHandoffApprovingRunId: ref(''),
    aiResearchLiveTradingPreparingRunId: ref(''),
    aiResearchLiveTradingActivatingRunId: ref(''),
    aiResearchLiveTradingDeactivatingRunId: ref(''),
    aiResearchLiveHandoffs: reactive<Record<string, AIStrategyLiveHandoffPackage>>({}),
    aiResearchPaperReviews: reactive<Record<string, AIStrategyPaperTradingReview>>({}),
    aiResearchResult: ref<AIStrategyResearchRunResponse | null>(null),
    aiResearchPaperStartRequest: record => ({
      research_workspace_id: record.research_workspace_id,
    }),
    aiResearchLivePrepareRequest: record => ({
      research_workspace_id: record.research_workspace_id,
    }),
    refreshAIResearchRunRecord: vi.fn().mockResolvedValue(null),
    upsertAIResearchRunRecord: vi.fn(),
    applyPaperStartToCurrentResult: vi.fn(),
    applyPaperReviewToCurrentResult: vi.fn(),
    applyResearchRunRecordToCurrentResult: vi.fn(),
    paperStartFailedRunRecord: (record, _paper: AIStrategyPaperTradingStart) => record,
    paperStartedRunRecord: (record, _paper: AIStrategyPaperTradingStart) => record,
    reviewedRunRecord: (record, _review: AIStrategyPaperTradingReview) => record,
    bestStrategyFromRunRecord: (_record): Strategy | null => null,
    bestStrategyIdForRecord: () => '',
    liveHandoffForRecord: () => null,
    canApproveLiveHandoff: () => false,
    canPrepareLiveTradingFromRecord: () => false,
    canActivateLiveTradingFromRecord: () => false,
    canDeactivateLiveTradingFromRecord: () => false,
    notifyAIResearchConfigError: () => false,
    viewStrategy: vi.fn(),
  }
}
