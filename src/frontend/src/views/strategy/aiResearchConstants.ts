import { reactive } from 'vue'
import type { MarketAssetType } from '@/api/marketData'
import type { AIStrategyResearchRunRequest } from '@/api/strategy'

export type AIResearchWorkflowMode = NonNullable<AIStrategyResearchRunRequest['workflow_mode']>
export type AIResearchPromptGenerationMode = 'default' | 'ai'

export const AI_RESEARCH_RUNS_AUTO_REFRESH_MS = 30_000

export const AI_RESEARCH_STAGE_LABELS: Record<string, string> = {
  queued: '排队中',
  starting: '启动中',
  running: '运行中',
  initializing: '初始化',
  workspace_ready: '工作区已就绪',
  configuration_invalid: '配置无效',
  strategy_idea: '策略构思',
  drafting: '生成策略脚本',
  draft: '策略生成',
  draft_generation_failed: '脚本生成失败',
  repairing_code: '修复策略脚本',
  backtesting: '运行回测',
  backtest_loop: '策略回测',
  backtest_failed: '回测失败',
  backtest_submission_failed: '回测提交失败',
  backtest_timeout: '回测超时',
  strategy_review: '策略审查',
  optimization_loop: '策略优化',
  improving: '改进策略',
  validating: '样本外验证',
  robustness_validation: '稳健性验证',
  robustness_failed: '稳健性失败',
  evaluating: '评估策略',
  quality_achieved: '质量达标',
  paper_trading: '模拟交易',
  paper_trading_failed: '模拟启动失败',
  paper_review: '模拟复核',
  live_candidate: '实盘候选',
  live_handoff: '实盘交接',
  live_trading_prepare: '实盘准备',
  research_iteration: '投研迭代',
  interrupted: '任务中断',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  timeout: '超时',
}

export const AI_RESEARCH_RUN_STATUS_LABELS: Record<string, string> = {
  achieved: '已达标',
  completed: '已完成',
  failed: '未达标',
  interrupted: '任务中断',
  cancelled: '已取消',
  timeout: '超时',
  backtest_submission_failed: '回测提交失败',
  configuration_invalid: '配置无效',
}

export const AI_RESEARCH_PAPER_REVIEW_STATUS_LABELS: Record<string, string> = {
  ready_for_live_candidate: '实盘候选',
  live_readiness_expired: '实盘候选已过期',
  monitoring: '继续观察',
  needs_research_review: '需要重新投研',
  paper_workspace_missing: '模拟工作区缺失',
  paper_unit_missing: '模拟单元缺失',
  monitoring_plan_missing: '监控计划缺失',
}

export const AI_RESEARCH_PAPER_RULE_STATUS_LABELS: Record<string, string> = {
  passed: '已通过',
  pending: '继续观察',
  failed: '未通过',
}

export const AI_RESEARCH_LIVE_READINESS_STATUS_LABELS: Record<string, string> = {
  passed: '已通过',
  pending: '待确认',
  pending_manual_confirmation: '待人工确认',
  skipped: '已跳过',
  expired: '已过期',
  failed: '未通过',
}

export const AI_RESEARCH_LIVE_HANDOFF_STATUS_LABELS: Record<string, string> = {
  ready_for_approval: '可提交审批',
  blocked: '存在阻塞',
  approved_for_live: '已批准实盘',
  approval_rejected: '审批驳回',
}

export const AI_RESEARCH_PIPELINE_STEP_STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  running: '进行中',
  completed: '已完成',
  failed: '失败',
  cancelled: '已取消',
  skipped: '已跳过',
}

export const AI_RESEARCH_WORKFLOW_STEPS: NonNullable<AIStrategyResearchRunRequest['workflow_steps']> = [
  'ideation',
  'generation',
  'backtest',
  'review',
  'optimization',
]

export function todayIsoDate() {
  return new Date().toISOString().slice(0, 10)
}

export const DEFAULT_AI_RESEARCH_START_DATE = '2020-01-01'
export const DEFAULT_AI_RESEARCH_END_DATE = todayIsoDate()
export const DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS = 7
export const PAPER_GATEWAY_CONFIG_PLACEHOLDER = '{"name":"paper_gateway","params":{}}'
export const LIVE_GATEWAY_CONFIG_PLACEHOLDER = '{"name":"ctp_live","params":{}}'

export class AIResearchConfigError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'AIResearchConfigError'
  }
}

export const AI_RESEARCH_CONFIG_ERROR_MESSAGES = new Set([
  '模拟网关配置必须是合法 JSON',
  '模拟网关配置必须是 JSON 对象',
  '模拟网关配置包含脱敏凭据，请重新输入真实网关配置',
  '实盘网关配置必须是合法 JSON',
  '实盘网关配置必须是 JSON 对象',
  '实盘网关配置包含脱敏凭据，请重新输入真实网关配置',
])

export function createAIResearchForm() {
  return reactive({
    prompt: '',
    workflow_mode: 'auto' as AIResearchWorkflowMode,
    symbol: '000001.SZ',
    symbol_name: '',
    market_data_asset_type: '' as '' | MarketAssetType,
    timeframe: '1d',
    timeframe_n: 1,
    start_date: DEFAULT_AI_RESEARCH_START_DATE,
    end_date: DEFAULT_AI_RESEARCH_END_DATE,
    knowledge_base_id: '',
    thinking_mode: false,
    target_sharpe: 1.0,
    min_total_trades: 1,
    use_max_drawdown_limit: false,
    max_drawdown_limit: 20,
    use_min_total_return: false,
    min_total_return: 0,
    use_min_annual_return: false,
    min_annual_return: 0,
    use_min_win_rate: false,
    min_win_rate: 50,
    max_iterations: 3,
    out_of_sample_validation: true,
    require_out_of_sample_validation: true,
    out_of_sample_ratio_pct: 25,
    use_min_out_of_sample_sharpe: false,
    min_out_of_sample_sharpe: 0.6,
    use_min_out_of_sample_trades: false,
    min_out_of_sample_trades: 1,
    robustness_validation: false,
    require_robustness_validation: false,
    robustness_methods: ['monte_carlo'] as string[],
    min_robustness_score: 55,
    robustness_monte_carlo_iterations: 300,
    robustness_random_seed: null as number | null,
    initial_cash: 100000,
    use_manual_commission: false,
    commission: 0.001,
    annual_days: 252,
    calc_method: 'simple',
    weight_mode: 'equal',
    group_name: '',
    backtest_timeout_seconds: 600,
    poll_interval_seconds: 2,
    research_workspace_id: '',
    seed_strategy_id: '',
    continue_from_run_id: '',
    continuation_source: '',
    start_paper_trading: true,
    min_paper_trading_days: DEFAULT_AI_RESEARCH_MIN_PAPER_TRADING_DAYS,
    paper_workspace_name: '',
    trading_workspace_id: '',
    gateway_config_json: '',
    live_workspace_name: '',
    live_trading_workspace_id: '',
    live_gateway_config_json: '',
  })
}

export type AIResearchFormState = ReturnType<typeof createAIResearchForm>
