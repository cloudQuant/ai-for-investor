import api from './index'

export type PortfolioAnalyticsSourceMode = 'research' | 'imported' | 'paper'
export type PortfolioAnalyticsTaskState =
  | 'pending'
  | 'running'
  | 'succeeded'
  | 'unavailable'
  | 'failed'
  | 'cancelled'
  | 'expired'

export interface PortfolioAnalyticsFactsV2 {
  version: 2
  portfolio_ref: string
  source_mode: PortfolioAnalyticsSourceMode
  source_ref: string
  source_version: string
  source_generation: string
  facts_snapshot_ref: string
  spot: Record<string, unknown>
  nav_history: Record<string, unknown>
  loss_history: Record<string, unknown>
  scenario: Record<string, unknown>
}

export interface PortfolioAnalyticsRequestV2 {
  version: 2
  portfolio_ref: string
  reporting_currency: string
  loss_horizon_ref: string
  confidence: string
  scenario_ref: string
  scenario_version: string
}

export interface PortfolioAnalyticsTaskCreate {
  idempotency_key: string
  facts: PortfolioAnalyticsFactsV2
  request: PortfolioAnalyticsRequestV2
}

export interface PortfolioAnalyticsTask {
  task_ref: string
  portfolio_ref: string
  membership_version: number
  membership_sha256: string
  input_snapshot_id: string
  input_sha256: string
  state: PortfolioAnalyticsTaskState
  detail_code?: string | null
  created_ns: string
  state_ns: string
  result?: Record<string, unknown> | null
}

function membershipPath(portfolioRef: string, membershipVersion: number) {
  return `/portfolio/compositions/${encodeURIComponent(portfolioRef)}`
    + `/versions/${membershipVersion}/analytics-tasks`
}

export const portfolioAnalyticsTasksApi = {
  createTask(
    portfolioRef: string,
    membershipVersion: number,
    data: PortfolioAnalyticsTaskCreate,
  ) {
    return api.post<PortfolioAnalyticsTask>(
      membershipPath(portfolioRef, membershipVersion),
      data,
    )
  },
  getTask(portfolioRef: string, membershipVersion: number, taskRef: string) {
    return api.get<PortfolioAnalyticsTask>(
      `${membershipPath(portfolioRef, membershipVersion)}/${encodeURIComponent(taskRef)}`,
    )
  },
  cancelTask(portfolioRef: string, membershipVersion: number, taskRef: string) {
    return api.post<PortfolioAnalyticsTask>(
      `${membershipPath(portfolioRef, membershipVersion)}/${encodeURIComponent(taskRef)}/cancel`,
    )
  },
}
