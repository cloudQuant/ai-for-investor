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
  get: vi.fn(),
  getTemplateReadme: vi.fn(),
  startAIResearchPaperTrading: vi.fn(),
  reviewAIResearchPaperTrading: vi.fn(),
  buildAIResearchLiveHandoff: vi.fn(),
  approveAIResearchLiveHandoff: vi.fn(),
  prepareAIResearchLiveTrading: vi.fn(),
  activateAIResearchLiveTrading: vi.fn(),
  deactivateAIResearchLiveTrading: vi.fn(),
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

  it('applies a successful paper start to history and keeps failed start state when refresh fails', async () => {
    const options = createRuntimeOperationsOptions()
    const failedRecord = { run_id: 'run-2', status: 'paper_failed' } as AIStrategyResearchRunRecord
    options.paperStartedRunRecord = vi.fn((record) => ({ ...record, paper_trading_started: true }))
    options.paperStartFailedRunRecord = vi.fn(() => failedRecord)
    const operations = useAIResearchRuntimeOperations(options)
    const startedRecord = {
      run_id: 'run-1', research_workspace_id: 'workspace-1',
    } as AIStrategyResearchRunRecord
    strategyApiMocks.startAIResearchPaperTrading.mockResolvedValueOnce({
      started: true,
      run_record: null,
    })

    await operations.startPaperFromResearchRecord(startedRecord)

    expect(options.paperStartedRunRecord).toHaveBeenCalledOnce()
    expect(options.upsertAIResearchRunRecord).toHaveBeenCalledWith(expect.objectContaining({
      run_id: 'run-1', paper_trading_started: true,
    }))
    expect(options.applyPaperStartToCurrentResult).toHaveBeenCalledWith(
      'run-1', expect.objectContaining({ started: true }), expect.objectContaining({
        paper_trading_started: true,
      }),
    )
    expect(ElMessage.success).toHaveBeenCalledWith('strategy.aiResearchPaperStartedSuccess')
    expect(options.aiResearchPaperStartingRunId.value).toBe('')

    vi.clearAllMocks()
    strategyApiMocks.startAIResearchPaperTrading.mockResolvedValueOnce({
      started: false,
      run_record: null,
    })
    vi.mocked(options.refreshAIResearchRunRecord).mockRejectedValue(new Error('history unavailable'))
    await operations.startPaperFromResearchRecord({
      run_id: 'run-2', research_workspace_id: 'workspace-2',
    } as AIStrategyResearchRunRecord)

    expect(options.paperStartFailedRunRecord).toHaveBeenCalledOnce()
    expect(options.upsertAIResearchRunRecord).toHaveBeenCalledWith(failedRecord)
    expect(options.refreshAIResearchRunRecord).toHaveBeenCalledWith('run-2', 'workspace-2')
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchPaperStartFailed')
    expect(options.aiResearchPaperStartingRunId.value).toBe('')
  })

  it('loads a strategy only when the iteration has no inline code and has an id', async () => {
    const options = createRuntimeOperationsOptions()
    const operations = useAIResearchRuntimeOperations(options)
    const inlineStrategy = { id: 'inline', name: 'Inline', code: 'def run(): pass' } as Strategy
    await operations.viewResearchIterationStrategy({ strategy: inlineStrategy } as AIStrategyResearchRunResponse['iterations'][number])
    await operations.viewResearchIterationStrategy({
      strategy: { id: '', code: '' },
    } as AIStrategyResearchRunResponse['iterations'][number])

    expect(options.viewStrategy).toHaveBeenCalledOnce()
    expect(options.viewStrategy).toHaveBeenCalledWith(inlineStrategy)
    expect(strategyApiMocks.get).not.toHaveBeenCalled()

    strategyApiMocks.get.mockResolvedValueOnce({ id: 'server', code: 'strategy code' })
    await operations.viewResearchIterationStrategy({
      strategy: { id: 'server', code: ' ' },
    } as AIStrategyResearchRunResponse['iterations'][number])
    expect(strategyApiMocks.get).toHaveBeenCalledWith('server')
    expect(options.viewStrategy).toHaveBeenLastCalledWith({ id: 'server', code: 'strategy code' })

    strategyApiMocks.get.mockRejectedValueOnce(new Error('strategy missing'))
    await operations.viewResearchIterationStrategy({
      strategy: { id: 'missing', code: '' },
    } as AIStrategyResearchRunResponse['iterations'][number])
    expect(options.aiResearchStrategyViewingRunId.value).toBe('')
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })

  it('reviews a paper run, records its live handoff, and resets loading on API failure', async () => {
    const options = createRuntimeOperationsOptions()
    options.reviewedRunRecord = vi.fn((record) => ({ ...record, status: 'reviewed' }))
    const operations = useAIResearchRuntimeOperations(options)
    const record = {
      run_id: 'review-run', research_workspace_id: 'workspace-3',
    } as AIStrategyResearchRunRecord
    const handoff = {
      ready_for_live: false,
      approval_required: true,
      status: 'blocked',
      generated_at: '2026-10-13T00:00:00Z',
      deployment_blockers: [],
      next_actions: [],
    } as unknown as AIStrategyLiveHandoffPackage
    strategyApiMocks.reviewAIResearchPaperTrading.mockResolvedValueOnce({
      ready_for_live: false,
      live_handoff: handoff,
    })

    await operations.reviewPaperFromResearchRecord(record)

    expect(options.aiResearchPaperReviews['review-run']).toMatchObject({ ready_for_live: false })
    expect(options.aiResearchLiveHandoffs['review-run']).toMatchObject({
      ready_for_live: false,
      status: 'blocked',
    })
    expect(options.applyPaperReviewToCurrentResult).toHaveBeenCalledWith(
      'review-run', expect.objectContaining({ status: 'reviewed' }),
    )
    expect(options.aiResearchPaperReviewingRunId.value).toBe('')
    expect(ElMessage.success).toHaveBeenCalledWith('strategy.aiResearchPaperReviewUpdated')
    expect(ElMessage.success).toHaveBeenCalledWith('strategy.aiResearchLiveHandoffBlocked')

    strategyApiMocks.reviewAIResearchPaperTrading.mockRejectedValueOnce(new Error('offline'))
    await operations.reviewPaperFromResearchRecord(record)
    expect(options.aiResearchPaperReviewingRunId.value).toBe('')
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })

  it('guards live preparation and clears activation state when the server declines activation', async () => {
    const options = createRuntimeOperationsOptions()
    const canPrepare = vi.fn().mockReturnValue(false)
    const canActivate = vi.fn().mockReturnValue(false)
    options.canPrepareLiveTradingFromRecord = canPrepare
    options.canActivateLiveTradingFromRecord = canActivate
    const operations = useAIResearchRuntimeOperations(options)
    const record = { run_id: 'live-run', research_workspace_id: 'workspace-4' } as AIStrategyResearchRunRecord

    await operations.prepareLiveTradingFromResearchRecord(record)
    expect(strategyApiMocks.prepareAIResearchLiveTrading).not.toHaveBeenCalled()

    canPrepare.mockReturnValue(true)
    strategyApiMocks.prepareAIResearchLiveTrading.mockResolvedValueOnce({
      prepared: true,
      workspace: { id: 'live-workspace', name: 'Live' },
      unit: { id: 'live-unit', lock_trading: true },
      handoff: { live_trading_prepared_at: '2026-10-13T00:00:00Z' },
      next_actions: ['monitor'],
    })
    await operations.prepareLiveTradingFromResearchRecord(record)
    expect(options.aiResearchLiveTradingPreparingRunId.value).toBe('')
    expect(options.upsertAIResearchRunRecord).toHaveBeenCalledWith(expect.objectContaining({
      live_workspace_id: 'live-workspace', live_unit_id: 'live-unit', live_trading_prepared: true,
    }))

    canActivate.mockReturnValue(true)
    strategyApiMocks.activateAIResearchLiveTrading.mockResolvedValueOnce({
      activated: false,
      activation_status: 'pending',
    })
    await operations.activateLiveTradingFromResearchRecord(record)
    expect(options.aiResearchLiveTradingActivatingRunId.value).toBe('')
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })

  it('builds a handoff for the selected run and recovers cleanly when generation fails', async () => {
    const options = createRuntimeOperationsOptions()
    const record = { run_id: 'handoff-run', research_workspace_id: 'workspace-5' } as AIStrategyResearchRunRecord
    options.aiResearchResult.value = { run_record: record } as AIStrategyResearchRunResponse
    const operations = useAIResearchRuntimeOperations(options)
    const handoff = {
      ready_for_live: true,
      approval_required: true,
      status: 'ready_for_approval',
      generated_at: '2026-10-13T00:00:00Z',
      deployment_blockers: [],
      next_actions: ['approve'],
    } as unknown as AIStrategyLiveHandoffPackage
    strategyApiMocks.buildAIResearchLiveHandoff.mockResolvedValueOnce(handoff)

    await operations.buildLiveHandoffFromCurrentResult()
    expect(strategyApiMocks.buildAIResearchLiveHandoff).toHaveBeenCalledWith(
      'handoff-run', 'workspace-5',
    )
    expect(options.aiResearchLiveHandoffLoadingRunId.value).toBe('')
    expect(options.aiResearchLiveHandoffs['handoff-run']).toMatchObject({ ready_for_live: true })
    expect(options.applyResearchRunRecordToCurrentResult).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: 'handoff-run', live_handoff: handoff }),
    )

    options.aiResearchResult.value = null
    await operations.buildLiveHandoffFromCurrentResult()
    expect(strategyApiMocks.buildAIResearchLiveHandoff).toHaveBeenCalledOnce()

    await operations.buildLiveHandoffFromResearchRecord(record)
    expect(options.aiResearchLiveHandoffLoadingRunId.value).toBe('')
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })

  it('requires handoff approval, sends explicit approval fields, and deactivates the live unit', async () => {
    const options = createRuntimeOperationsOptions()
    const handoff = {
      ready_for_live: true,
      approval_required: true,
      status: 'ready_for_approval',
      generated_at: '2026-10-13T00:00:00Z',
      deployment_blockers: [],
      next_actions: [],
    } as unknown as AIStrategyLiveHandoffPackage
    const record = {
      run_id: 'live-ops-run',
      research_workspace_id: 'workspace-6',
      live_handoff: handoff,
    } as AIStrategyResearchRunRecord
    options.liveHandoffForRecord = vi.fn(() => handoff)
    options.canApproveLiveHandoff = vi.fn(() => true)
    options.canDeactivateLiveTradingFromRecord = vi.fn(() => true)
    const operations = useAIResearchRuntimeOperations(options)

    messageMocks.confirm.mockRejectedValueOnce(new Error('operator cancelled'))
    await operations.approveLiveHandoffFromResearchRecord(record, 'approved')
    expect(strategyApiMocks.approveAIResearchLiveHandoff).not.toHaveBeenCalled()

    const approvedHandoff = { ...handoff, status: 'approved' } as AIStrategyLiveHandoffPackage
    strategyApiMocks.approveAIResearchLiveHandoff.mockResolvedValueOnce(approvedHandoff)
    await operations.approveLiveHandoffFromResearchRecord(record, 'approved')
    expect(strategyApiMocks.approveAIResearchLiveHandoff).toHaveBeenCalledWith(
      'live-ops-run',
      expect.objectContaining({
        decision: 'approved',
        account_confirmed: true,
        risk_limit_confirmed: true,
      }),
      'workspace-6',
    )
    expect(options.aiResearchLiveHandoffApprovingRunId.value).toBe('')
    expect(ElMessage.success).toHaveBeenCalledWith('strategy.aiResearchLiveHandoffApproved')

    options.aiResearchLiveHandoffs['live-ops-run'] = handoff
    strategyApiMocks.deactivateAIResearchLiveTrading.mockResolvedValueOnce({
      prepared: false,
      activation_status: 'deactivated',
      activation_instance_id: 'instance-6',
      next_actions: [],
    })
    await operations.deactivateLiveTradingFromResearchRecord(record)
    expect(strategyApiMocks.deactivateAIResearchLiveTrading).toHaveBeenCalledWith(
      'live-ops-run', 'workspace-6',
    )
    expect(options.aiResearchLiveTradingDeactivatingRunId.value).toBe('')
    expect(options.aiResearchLiveHandoffs['live-ops-run']).toBeUndefined()
    expect(options.upsertAIResearchRunRecord).toHaveBeenCalledWith(expect.objectContaining({
      run_id: 'live-ops-run',
      live_handoff: null,
      live_trading_prepared: false,
    }))
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
