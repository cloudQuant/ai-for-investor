import type { MarketAssetType } from '@/api/marketData'
import type { AIStrategyResearchRunRequest } from '@/api/strategy'

export interface AIResearchTaskFormState {
  prompt: string
  workflow_mode: 'auto' | 'prompt'
  symbol: string
  symbol_name: string
  market_data_asset_type: '' | MarketAssetType
  timeframe: string
  timeframe_n: number
  start_date: string
  end_date: string
  knowledge_base_id: string
  thinking_mode: boolean
  target_sharpe: number
  min_total_trades: number
  max_iterations: number
  initial_cash: number
  commission: number
  use_manual_commission: boolean
  annual_days: number
  calc_method: string
  weight_mode: string
  group_name: string
  backtest_timeout_seconds: number
  poll_interval_seconds: number
  research_workspace_id: string
  trading_workspace_id: string
  seed_strategy_id: string
  continue_from_run_id: string
  continuation_source: string
  start_paper_trading: boolean
  paper_workspace_name: string
  gateway_config_json: string
  use_max_drawdown_limit: boolean
  max_drawdown_limit: number
  use_min_total_return: boolean
  min_total_return: number
  use_min_annual_return: boolean
  min_annual_return: number
  use_min_win_rate: boolean
  min_win_rate: number
  out_of_sample_validation: boolean
  require_out_of_sample_validation: boolean
  out_of_sample_ratio_pct: number
  use_min_out_of_sample_sharpe: boolean
  min_out_of_sample_sharpe: number
  use_min_out_of_sample_trades: boolean
  min_out_of_sample_trades: number
  robustness_validation: boolean
  require_robustness_validation: boolean
  robustness_methods: string[]
  min_robustness_score: number
  robustness_monte_carlo_iterations: number
  robustness_random_seed: number | null
  min_paper_trading_days: number
}

export interface AIResearchMandateSnapshot {
  rawPrompt: string
  promptOrigin: 'explicit' | 'auto_generated'
  symbol: string | null
  symbolName: string | null
  marketDataAssetType: MarketAssetType | undefined
  timeframe: string | null
  riskConstraints: Record<string, unknown>
  tradingConstraints: Record<string, unknown>
  qualityGates: Record<string, unknown>
}

export interface AIResearchSubmissionSnapshot {
  request: AIStrategyResearchRunRequest
  mandate: AIResearchMandateSnapshot
  marketDataAssetType: MarketAssetType | undefined
}

export interface AIResearchMandateInput {
  prompt: string
  symbol: string
  shouldUseServerGeneratedPrompt?: boolean
}

export interface AIResearchRunnableInput extends AIResearchMandateInput {
  shouldUseServerGeneratedPrompt: boolean
}

export interface AIResearchAutoContinuationSource {
  prompt: string
  mandateId: string
}

export interface AIResearchPreparedSubmission {
  input: AIResearchRunnableInput
  submission: AIResearchSubmissionSnapshot
}
