import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ElMessage } from 'element-plus'
import { ref } from 'vue'
import type {
  AIStrategyResearchRunRequest,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
  AIStrategyResearchTaskListResponse,
  AIStrategyResearchTaskResponse,
  InvestmentMandateResponse,
} from '@/api/strategy'
import { useAIResearchTaskLifecycle, type AIResearchTaskApi } from '@/views/strategy/useAIResearchTaskLifecycle'
import {
  useAIResearchRunExecution,
  type AIResearchRunExecutionOptions,
} from '@/views/strategy/useAIResearchRunExecution'
import { useAIResearchTaskState } from '@/views/strategy/useAIResearchTaskState'
import type {
  AIResearchRunnableInput,
  AIResearchSubmissionSnapshot,
  AIResearchTaskFormState,
} from '@/views/strategy/aiResearchTaskTypes'

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
}))

vi.mock('element-plus', () => ({ ElMessage: messageMocks }))

describe('AI research task lifecycle collaborator', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('propagates a polling failure after applying the latest task state', async () => {
    const getAIResearchTask = vi.fn(async (_taskId: string): Promise<AIStrategyResearchTaskResponse> => {
      throw new Error('task polling unavailable')
    })
    const api = {
      runAIResearchLoop: async () => {
        throw new Error('legacy fallback should not be used')
      },
      getAIResearchTask,
    } satisfies AIResearchTaskApi
    const fixture = createLifecycle(api)

    await expect(fixture.lifecycle.pollAIResearchTask(runningTask())).rejects.toThrow(
      'task polling unavailable'
    )

    expect(getAIResearchTask).toHaveBeenCalledWith('task-1')
    expect(fixture.taskState.aiResearchTaskId.value).toBe('task-1')
    expect(fixture.taskState.aiResearchTaskStatus.value).toBe('running')
  })

  it('records a task-list restore failure and always releases the running state', async () => {
    const listAIResearchTasks = vi.fn(async (
      _activeOnly?: boolean,
      _limit?: number
    ): Promise<AIStrategyResearchTaskListResponse> => {
      throw new Error('task history unavailable')
    })
    const api = {
      runAIResearchLoop: async () => {
        throw new Error('legacy fallback should not be used')
      },
      listAIResearchTasks,
    } satisfies AIResearchTaskApi
    const fixture = createLifecycle(api)

    await fixture.lifecycle.restoreActiveAIResearchTask()

    expect(listAIResearchTasks).toHaveBeenCalledWith(true, 5)
    expect(fixture.taskState.aiResearchTaskError.value).toBe('task history unavailable')
    expect(fixture.aiResearchRunning.value).toBe(false)
    expect(fixture.scheduleAutoRefresh).toHaveBeenCalledTimes(1)
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })

  it('clears the cancel spinner when the cancel request fails', async () => {
    const cancelAIResearchTask = vi.fn(async (_taskId: string): Promise<AIStrategyResearchTaskResponse> => {
      throw new Error('cancel unavailable')
    })
    const api = {
      runAIResearchLoop: async () => {
        throw new Error('legacy fallback should not be used')
      },
      cancelAIResearchTask,
    } satisfies AIResearchTaskApi
    const fixture = createLifecycle(api)
    fixture.taskState.aiResearchTaskId.value = 'task-1'

    await fixture.lifecycle.cancelAIResearchTask()

    expect(cancelAIResearchTask).toHaveBeenCalledWith('task-1')
    expect(fixture.taskState.aiResearchCancelling.value).toBe(false)
    expect(fixture.taskState.aiResearchCancelRequested.value).toBe(true)
    expect(ElMessage.error).toHaveBeenCalledWith('strategy.aiResearchRunFailed')
  })
})

describe('AI research run execution continuation', () => {
  it('keeps the running guard active while continuing a task and polling its result', async () => {
    const pendingTask = deferred<AIStrategyResearchTaskResponse>()
    const continueAIResearchTask = vi.fn(
      (_taskId: string, _data?: Parameters<NonNullable<AIResearchTaskApi['continueAIResearchTask']>>[1]) =>
        pendingTask.promise
    )
    const fixture = createRunExecution({
      runAIResearchLoop: async (_request: AIStrategyResearchRunRequest) => completedRun(),
      continueAIResearchTask,
    })

    const firstContinuation = fixture.execution.continueAIResearchFromTaskSnapshot()
    await vi.waitFor(() => expect(continueAIResearchTask).toHaveBeenCalledTimes(1))

    expect(fixture.aiResearchRunning.value).toBe(true)
    await fixture.execution.continueAIResearchFromTaskSnapshot()
    expect(continueAIResearchTask).toHaveBeenCalledTimes(1)

    const task = runningTask()
    pendingTask.resolve(task)
    await firstContinuation

    expect(fixture.pollAIResearchTask).toHaveBeenCalledWith(task, expect.any(Number))
    expect(fixture.aiResearchResult.value).toEqual(completedRun())
    expect(fixture.aiResearchRunning.value).toBe(false)
    expect(fixture.scheduleAutoRefresh).toHaveBeenCalledTimes(1)
  })

  it('releases the running state when continuing a task fails', async () => {
    const pendingTask = deferred<AIStrategyResearchTaskResponse>()
    const continueAIResearchTask = vi.fn(
      (_taskId: string, _data?: Parameters<NonNullable<AIResearchTaskApi['continueAIResearchTask']>>[1]) =>
        pendingTask.promise
    )
    const fixture = createRunExecution({
      runAIResearchLoop: async (_request: AIStrategyResearchRunRequest) => completedRun(),
      continueAIResearchTask,
    })

    const continuation = fixture.execution.continueAIResearchFromTaskSnapshot()
    await vi.waitFor(() => expect(continueAIResearchTask).toHaveBeenCalledTimes(1))
    expect(fixture.aiResearchRunning.value).toBe(true)

    const failure = new Error('continue unavailable')
    pendingTask.reject(failure)
    await continuation

    expect(fixture.handleAIResearchRunError).toHaveBeenCalledWith(failure)
    expect(fixture.aiResearchRunning.value).toBe(false)
    expect(fixture.scheduleAutoRefresh).toHaveBeenCalledTimes(1)
  })
})

function createLifecycle(api: AIResearchTaskApi) {
  const taskState = useAIResearchTaskState({
    aiResearchForm: createTaskForm(),
    aiResearchTaskAutoContinuationSourceFromTask: () => null,
    gatewayConfigJsonFromTaskSnapshot: () => '',
    aiResearchMarketDataAssetTypeFromDataConfig: () => '',
    resolvedAIResearchTaskBacktestEnvironment: () => null,
    aiResearchTaskRestoredCommission: () => null,
    aiResearchTaskUsesManualCommission: () => false,
    promotionAuditFromPayload: () => [],
  })
  const aiResearchRunning = ref(false)
  const aiResearchResult = ref<AIStrategyResearchRunResponse | null>(null)
  const scheduleAutoRefresh = vi.fn()
  const lifecycle = useAIResearchTaskLifecycle({
    t: key => key,
    api,
    taskState,
    aiResearchRunning,
    aiResearchResult,
    restoreAIResearchResultFromTask: async () => null,
    syncAIResearchFormFromResult: () => undefined,
    setAIResearchConfigProfileFromRunRecord: (_record: AIStrategyResearchRunRecord) => undefined,
    upsertAIResearchRunRecord: (_record: AIStrategyResearchRunRecord) => undefined,
    loadAIResearchRuns: async () => undefined,
    refreshAIResearchRunRecord: async () => null,
    researchResultFromRunRecord: (_record: AIStrategyResearchRunRecord) => {
      throw new Error('run record should not be converted')
    },
    notifyAIResearchResult: () => undefined,
    scheduleAIResearchRunsAutoRefresh: scheduleAutoRefresh,
  })
  return { lifecycle, taskState, aiResearchRunning, scheduleAutoRefresh }
}

function createTaskForm(): AIResearchTaskFormState {
  return {
    prompt: '',
    workflow_mode: 'auto',
    symbol: '000001.SZ',
    symbol_name: '',
    market_data_asset_type: '',
    timeframe: '1d',
    timeframe_n: 1,
    start_date: '2020-01-01',
    end_date: '2026-10-12',
    knowledge_base_id: '',
    thinking_mode: false,
    target_sharpe: 1,
    min_total_trades: 1,
    max_iterations: 3,
    initial_cash: 100000,
    commission: 0.001,
    use_manual_commission: false,
    annual_days: 252,
    calc_method: 'simple',
    weight_mode: 'equal',
    group_name: '',
    backtest_timeout_seconds: 600,
    poll_interval_seconds: 2,
    research_workspace_id: '',
    trading_workspace_id: '',
    seed_strategy_id: '',
    continue_from_run_id: '',
    continuation_source: '',
    start_paper_trading: true,
    paper_workspace_name: '',
    gateway_config_json: '',
    use_max_drawdown_limit: false,
    max_drawdown_limit: 20,
    use_min_total_return: false,
    min_total_return: 0,
    use_min_annual_return: false,
    min_annual_return: 0,
    use_min_win_rate: false,
    min_win_rate: 50,
    out_of_sample_validation: true,
    require_out_of_sample_validation: true,
    out_of_sample_ratio_pct: 25,
    use_min_out_of_sample_sharpe: false,
    min_out_of_sample_sharpe: 0.6,
    use_min_out_of_sample_trades: false,
    min_out_of_sample_trades: 1,
    robustness_validation: false,
    require_robustness_validation: false,
    robustness_methods: ['monte_carlo'],
    min_robustness_score: 55,
    robustness_monte_carlo_iterations: 300,
    robustness_random_seed: null,
    min_paper_trading_days: 7,
  }
}

function createRunExecution(api: AIResearchTaskApi) {
  const aiResearchForm = createTaskForm()
  const taskState = useAIResearchTaskState({
    aiResearchForm,
    aiResearchTaskAutoContinuationSourceFromTask: () => null,
    gatewayConfigJsonFromTaskSnapshot: () => '',
    aiResearchMarketDataAssetTypeFromDataConfig: () => '',
    resolvedAIResearchTaskBacktestEnvironment: () => null,
    aiResearchTaskRestoredCommission: () => null,
    aiResearchTaskUsesManualCommission: () => false,
    promotionAuditFromPayload: () => [],
  })
  taskState.aiResearchTaskId.value = 'task-1'

  const aiResearchRunning = ref(false)
  const aiResearchResult = ref<AIStrategyResearchRunResponse | null>(null)
  const aiResearchMandate = ref<InvestmentMandateResponse | null>(null)
  const pollAIResearchTask = vi.fn(async (
    _task: AIStrategyResearchTaskResponse,
    _timeoutMs?: number
  ) => completedRun())
  const handleAIResearchRunError = vi.fn((_error: unknown) => true)
  const scheduleAutoRefresh = vi.fn()
  const loadAIResearchRuns = vi.fn(async () => undefined)
  const submission = createSubmission()
  const input: AIResearchRunnableInput = {
    prompt: 'research task',
    symbol: '000001.SZ',
    shouldUseServerGeneratedPrompt: false,
  }

  const options: AIResearchRunExecutionOptions = {
    api,
    taskState,
    aiResearchForm,
    aiResearchRunning,
    aiResearchResult,
    aiResearchMandate,
    canRetryAIResearchTask: () => false,
    aiResearchRunnableInput: () => input,
    aiResearchContinuationRunnableInput: () => input,
    captureAIResearchSubmission: (_input: AIResearchRunnableInput) => submission,
    loadAIResearchMandate: async (_mandateId: string) => undefined,
    ensureAIResearchMandateConfirmed: async (_snapshot) => createMandate(),
    resolveAIResearchMarketDataCapabilitiesForAction: async () => ({
      capabilities: null,
      lastKnownBridgeEnabled: false,
    }),
    ensureAIResearchStrictLocalMarketDataReady: async () => true,
    applyAIResearchMarketDataBridgeIntent: (request) => request,
    prepareAIResearchOutputForRun: () => undefined,
    runAIResearchRequest: async (_request) => completedRun(),
    applyCompletedAIResearchResult: async (_result) => undefined,
    handleAIResearchRunError,
    clearAIResearchContinuation: () => undefined,
    scheduleAIResearchRunsAutoRefresh: scheduleAutoRefresh,
    aiResearchTaskPollTimeoutMs: () => 1000,
    pollAIResearchTask,
    setAIResearchConfigProfileFromRunRecord: (_record) => undefined,
    upsertAIResearchRunRecord: (_record) => undefined,
    loadAIResearchRuns,
    notifyAIResearchResult: (_result) => undefined,
  }

  return {
    execution: useAIResearchRunExecution(options),
    aiResearchRunning,
    aiResearchResult,
    handleAIResearchRunError,
    loadAIResearchRuns,
    pollAIResearchTask,
    scheduleAutoRefresh,
  }
}

function createSubmission(): AIResearchSubmissionSnapshot {
  return {
    request: { symbol: '000001.SZ' },
    mandate: {
      rawPrompt: 'research task',
      promptOrigin: 'explicit',
      symbol: '000001.SZ',
      symbolName: null,
      marketDataAssetType: undefined,
      timeframe: '1d',
      riskConstraints: {},
      tradingConstraints: {},
      qualityGates: {},
    },
    marketDataAssetType: undefined,
  }
}

function createMandate(): InvestmentMandateResponse {
  return {
    id: 'mandate-1',
    raw_prompt: 'research task',
    structured_goal: {},
    asset_scope: {},
    risk_constraints: {},
    trading_constraints: {},
    quality_gates: {},
    status: 'confirmed',
    source: 'user',
    created_at: '2026-10-12T00:00:00Z',
    updated_at: '2026-10-12T00:00:00Z',
  }
}

function completedRun(): AIStrategyResearchRunResponse {
  return {
    run_id: 'run-1',
    status: 'completed',
    achieved: false,
    target_sharpe: 1,
    started_at: '2026-10-12T00:00:00Z',
    completed_at: '2026-10-12T00:01:00Z',
    best_quality_score: 0,
    best_quality_gate_evaluations: [],
    best_metrics: {},
    research_workspace: {
      id: 'workspace-1',
      user_id: 'user-1',
      name: 'Research workspace',
      description: null,
      workspace_type: 'research',
      settings: {},
      trading_config: {},
      unit_count: 0,
      completed_count: 0,
      status: 'idle',
      created_at: '2026-10-12T00:00:00Z',
      updated_at: '2026-10-12T00:00:00Z',
    },
    iterations: [],
    next_actions: [],
    message: 'completed',
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function runningTask(): AIStrategyResearchTaskResponse {
  return {
    task_id: 'task-1',
    status: 'running',
    submitted_at: '2026-10-12T00:00:00Z',
    current_stage: 'backtest',
    progress: 25,
    iteration_count: 1,
    message: '',
  }
}
