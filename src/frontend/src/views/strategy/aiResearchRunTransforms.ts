import type {
  AIStrategyPaperTradingReview,
  AIStrategyPaperTradingStart,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunRequest,
  AIStrategyResearchTaskResponse,
} from '@/api/strategy'
import {
  AI_RESEARCH_WORKFLOW_STEPS,
  DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS,
} from './aiResearchConstants'
import {
  isPaperTradingStartFailure,
  liveReadinessChecklistForReview,
  paperHandoffRunRecordAssetSpecs,
  paperHandoffRunRecordBacktestEnvironment,
  paperMonitoringPlanFromHandoff,
  paperReviewLockFromPayload,
  paperTradingStartError,
} from './aiResearchFormatters'
import {
  isRecord,
  optionalBoolean,
  optionalNumber,
  stringArrayFromUnknown,
} from './aiResearchValueAdapters'

export function paperStartedPipeline(
  record: AIStrategyResearchRunRecord,
  t: (key: string) => string,
) {
  return {
    current_stage: 'paper_trading',
    status: record.status,
    progress: 80,
    ready_for_live: false,
    paper_trading_error: null,
    live_readiness_checklist: [],
    live_readiness_expires_at: null,
    workflow_mode: record.workflow_mode ?? 'auto',
    workflow_steps: record.workflow_steps ?? [...AI_RESEARCH_WORKFLOW_STEPS],
    steps: [
      { key: 'strategy_idea', label: t('strategy.aiResearchHeroStepIdea'), status: 'completed' },
      { key: 'draft', label: t('strategy.aiResearchStageDraft'), status: 'completed' },
      {
        key: 'backtest_loop',
        label: t('strategy.aiResearchHeroStepBacktest'),
        status: record.iteration_count > 0 ? 'completed' : 'pending',
        iteration_count: record.iteration_count,
        max_iterations: record.max_iterations,
      },
      {
        key: 'strategy_review',
        label: t('strategy.aiResearchStageReview'),
        status: record.iteration_count > 0 ? 'completed' : 'pending',
        iteration_count: record.iteration_count,
      },
      {
        key: 'optimization_loop',
        label: t('strategy.aiResearchStageOptimization'),
        status: record.iteration_count > 1 ? 'completed' : record.achieved ? 'skipped' : 'running',
        iteration_count: record.iteration_count,
        max_iterations: record.max_iterations,
      },
      {
        key: 'quality_gate',
        label: t('strategy.aiResearchQualityGates'),
        status: record.achieved ? 'completed' : 'running',
      },
      {
        key: 'paper_trading',
        label: t('strategy.aiResearchPaperStatus'),
        status: 'completed',
        error: null,
      },
      {
        key: 'paper_review',
        label: t('strategy.aiResearchPaperReview'),
        status: 'pending',
        review_status: null,
      },
    ],
  }
}

export function paperStartedRunRecord(
  record: AIStrategyResearchRunRecord,
  paper: AIStrategyPaperTradingStart,
  t: (key: string) => string,
): AIStrategyResearchRunRecord {
  const handoff = isRecord(paper.handoff) ? paper.handoff : {}
  return {
    ...record,
    asset_specs: paperHandoffRunRecordAssetSpecs(record, handoff),
    backtest_environment: paperHandoffRunRecordBacktestEnvironment(record, handoff),
    paper_trading_started: paper.started,
    paper_workspace_id: paper.workspace.id,
    paper_workspace_name: paper.workspace.name,
    paper_unit_id: paper.unit.id,
    paper_handoff: handoff,
    paper_monitoring_plan:
      paperMonitoringPlanFromHandoff(handoff) ?? record.paper_monitoring_plan,
    paper_review_status: null,
    paper_review_ready_for_live: false,
    paper_reviewed_at: null,
    paper_review_evaluations: [],
    paper_review_next_actions: [],
    live_readiness_checklist: [],
    live_readiness_expires_at: null,
    pipeline: paperStartedPipeline(record, t),
    next_actions: [
      '模拟交易已启动，正在等待后端同步模拟复核状态。',
      '如果同步暂不可用，可稍后手动复核模拟交易监控指标。',
    ],
  }
}

export function paperStartFailedRunRecord(
  record: AIStrategyResearchRunRecord,
  paper: AIStrategyPaperTradingStart,
  t: (key: string) => string,
): AIStrategyResearchRunRecord {
  const error = paperTradingStartError(paper)
  const previousSteps = record.pipeline?.steps ?? []
  const steps = previousSteps.some(step => step.key === 'paper_trading')
    ? previousSteps.map(step =>
        step.key === 'paper_trading'
          ? { ...step, status: 'failed', error }
          : step,
      )
    : [
        ...previousSteps,
        {
          key: 'paper_trading',
          label: t('strategy.aiResearchPaperStatus'),
          status: 'failed',
          error,
        },
      ]
  return {
    ...paperStartedRunRecord(record, paper, t),
    paper_trading_started: false,
    paper_review_status: null,
    paper_review_ready_for_live: false,
    paper_reviewed_at: null,
    paper_review_evaluations: [],
    paper_review_next_actions: [],
    live_readiness_checklist: [],
    live_readiness_expires_at: null,
    pipeline: {
      current_stage: 'paper_trading_failed',
      status: record.status,
      progress: record.pipeline?.progress ?? 92,
      ready_for_live: false,
      paper_trading_error: error,
      live_readiness_checklist: [],
      live_readiness_expires_at: null,
      steps,
    },
    next_actions: [
      `模拟交易启动错误：${error}`,
      '检查交易工作区、网关配置、策略脚本依赖和资产参数后可重试模拟。',
      '如果启动问题来自策略脚本或交易环境假设，可从该记录继续投研。',
    ],
  }
}

export function reviewedRunRecord(
  record: AIStrategyResearchRunRecord,
  review: AIStrategyPaperTradingReview,
): AIStrategyResearchRunRecord {
  const liveReadinessChecklist = liveReadinessChecklistForReview(review)
  const paperHandoff: Record<string, unknown> = { ...(record.paper_handoff ?? {}) }
  if (liveReadinessChecklist.length) {
    paperHandoff.live_readiness_checklist = liveReadinessChecklist
  } else {
    delete paperHandoff.live_readiness_checklist
  }
  if (review.live_readiness_expires_at) {
    paperHandoff.live_readiness_expires_at = review.live_readiness_expires_at
  } else {
    delete paperHandoff.live_readiness_expires_at
  }
  const reviewLock = paperReviewLockFromPayload(review.pipeline?.paper_review_lock)
  if (reviewLock) {
    paperHandoff.paper_review_lock = reviewLock
  } else {
    delete paperHandoff.paper_review_lock
  }
  return {
    ...record,
    paper_review_status: review.status,
    paper_review_ready_for_live: review.ready_for_live,
    paper_reviewed_at: review.reviewed_at ?? record.paper_reviewed_at,
    paper_review_evaluations: review.evaluations,
    paper_review_next_actions: review.next_actions,
    live_readiness_checklist: liveReadinessChecklist,
    live_readiness_expires_at: review.live_readiness_expires_at ?? null,
    paper_handoff: paperHandoff,
    pipeline: review.pipeline ?? record.pipeline,
    next_actions: review.next_actions,
  }
}

export function aiResearchRequestSnapshotFromRunRecord(record: AIStrategyResearchRunRecord) {
  const gates = record.quality_gates || {}
  return {
    prompt: record.prompt,
    workflow_mode: record.workflow_mode ?? 'auto',
    workflow_steps: record.workflow_steps ?? [...AI_RESEARCH_WORKFLOW_STEPS],
    symbol: record.symbol,
    symbol_name: record.symbol_name || '',
    timeframe: record.timeframe || '1d',
    timeframe_n: record.timeframe_n || 1,
    start_date: record.start_date ?? null,
    end_date: record.end_date ?? null,
    target_sharpe: record.target_sharpe,
    min_total_trades: record.min_total_trades,
    max_drawdown_limit: gates.max_drawdown_limit,
    min_total_return: gates.min_total_return,
    min_annual_return: gates.min_annual_return,
    min_win_rate: gates.min_win_rate,
    max_iterations: record.max_iterations,
    out_of_sample_validation: optionalBoolean(gates.out_of_sample_validation, true),
    require_out_of_sample_validation: optionalBoolean(
      gates.require_out_of_sample_validation,
      false,
    ),
    out_of_sample_ratio: optionalNumber(gates.out_of_sample_ratio) ?? 0.25,
    min_out_of_sample_sharpe: gates.min_out_of_sample_sharpe,
    min_out_of_sample_trades: gates.min_out_of_sample_trades,
    robustness_validation: optionalBoolean(gates.robustness_validation, true),
    require_robustness_validation: optionalBoolean(
      gates.require_robustness_validation,
      true,
    ),
    robustness_methods: stringArrayFromUnknown(gates.robustness_methods).length
      ? stringArrayFromUnknown(gates.robustness_methods)
      : ['monte_carlo'],
    min_robustness_score: optionalNumber(gates.min_robustness_score) ?? 55,
    robustness_monte_carlo_iterations:
      optionalNumber(gates.robustness_monte_carlo_iterations) ?? 300,
    robustness_random_seed: optionalNumber(gates.robustness_random_seed),
    backtest_timeout_seconds: record.backtest_timeout_seconds,
    poll_interval_seconds: record.poll_interval_seconds,
    initial_cash: record.initial_cash,
    commission: record.commission,
    annual_days: record.annual_days,
    calc_method: record.calc_method,
    weight_mode: record.weight_mode,
    research_workspace_id: record.research_workspace_id,
    mandate_id: record.mandate_id,
    seed_strategy_id: record.seed_strategy_id,
    continue_from_run_id: record.continued_from_run_id,
    start_paper_trading: record.paper_trading_started,
    min_paper_trading_days:
      optionalNumber(gates.min_paper_trading_days) ?? DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS,
    paper_workspace_name: record.paper_workspace_name,
    group_name: record.group_name,
    knowledge_base_id: record.knowledge_base_id,
    thinking_mode: Boolean(record.thinking_mode),
    continuation_context: record.continuation_context ?? {},
  } as AIStrategyResearchRunRequest & Record<string, unknown>
}

export function aiResearchTaskFromRunRecord(
  record: AIStrategyResearchRunRecord,
): AIStrategyResearchTaskResponse {
  const iterations = (record.iterations || []).filter(isRecord)
  const bestIterationPayload =
    iterations.find(item => optionalNumber(item.iteration) === record.best_iteration)
    ?? null
  const latestIteration = iterations[iterations.length - 1] ?? bestIterationPayload
  return {
    task_id: `run-${record.run_id}`,
    status: 'completed',
    submitted_at: record.started_at,
    started_at: record.started_at,
    completed_at: record.completed_at,
    run_id: record.run_id,
    research_workspace_id: record.research_workspace_id,
    mandate_id: record.mandate_id,
    request_snapshot: aiResearchRequestSnapshotFromRunRecord(record),
    ...(Object.prototype.hasOwnProperty.call(record, 'request_explicit_fields')
      ? { request_explicit_fields: record.request_explicit_fields }
      : {}),
    ...(Object.prototype.hasOwnProperty.call(record, 'request_explicit_fields_persisted')
      ? { request_explicit_fields_persisted: record.request_explicit_fields_persisted }
      : {}),
    continued_from_run_id: record.continued_from_run_id,
    continuation_source: record.continuation_source,
    continuation_context: record.continuation_context ?? {},
    current_stage: record.pipeline?.current_stage || record.status || 'completed',
    progress: optionalNumber(record.pipeline?.progress) ?? 100,
    current_iteration: record.best_iteration ?? record.iteration_count ?? null,
    iteration_count: record.iteration_count,
    max_iterations: record.max_iterations,
    latest_iteration: latestIteration,
    best_iteration_payload: bestIterationPayload,
    run_status: record.status,
    achieved: record.achieved,
    target_sharpe: record.target_sharpe,
    best_iteration: record.best_iteration,
    best_sharpe: record.best_sharpe,
    best_quality_score: record.best_quality_score,
    best_quality_gate_evaluations: record.best_quality_gate_evaluations ?? [],
    best_diagnostics: record.best_diagnostics,
    best_metrics: record.best_metrics,
    best_strategy_id: record.best_strategy_id,
    best_strategy_name: record.best_strategy_name,
    asset_specs: record.asset_specs,
    backtest_environment: record.backtest_environment,
    paper_workspace_id: record.paper_workspace_id,
    paper_workspace_name: record.paper_workspace_name,
    paper_unit_id: record.paper_unit_id,
    paper_trading_started: record.paper_trading_started,
    paper_monitoring_plan: record.paper_monitoring_plan,
    paper_handoff: record.paper_handoff,
    paper_review_status: record.paper_review_status,
    paper_review_ready_for_live: record.paper_review_ready_for_live,
    paper_reviewed_at: record.paper_reviewed_at,
    paper_review_evaluations: record.paper_review_evaluations,
    paper_review_next_actions: record.paper_review_next_actions,
    live_readiness_checklist: record.live_readiness_checklist,
    live_readiness_expires_at: record.live_readiness_expires_at,
    live_handoff: record.live_handoff,
    live_handoff_approval: record.live_handoff_approval,
    live_workspace_id: record.live_workspace_id,
    live_workspace_name: record.live_workspace_name,
    live_unit_id: record.live_unit_id,
    live_trading_prepared: record.live_trading_prepared,
    live_trading_prepared_at: record.live_trading_prepared_at,
    pipeline: record.pipeline,
    promotion_audit: record.promotion_audit,
    next_actions: record.next_actions,
    message: 'AI research result restored from run history',
  }
}

export function isKeepLocalFailedPaper(runRecord: AIStrategyResearchRunRecord): boolean {
  return isPaperTradingStartFailure(runRecord)
}
