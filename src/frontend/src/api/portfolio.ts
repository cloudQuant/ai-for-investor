/**
 * 组合管理 API
 */
import request from './index'

export interface StrategySummary {
  id: string
  strategy_id: string
  strategy_name: string
  status: string
  position_source?: string | null
  asset_spec_source?: string | null
  valuation_status?: string | null
  valuation_warnings?: string[]
  total_assets: number
  initial_capital: number
  pnl: number
  pnl_pct: number
  total_trades: number
  win_rate: number
}

export interface PortfolioOverview {
  total_assets: number
  total_cash: number
  total_position_value: number
  net_position_value?: number
  total_initial_capital: number
  total_pnl: number
  total_pnl_pct: number
  strategy_count: number
  running_count: number
  strategies: StrategySummary[]
}

export type PortfolioCompositionSource = 'research' | 'imported' | 'paper' | 'live'

export interface PortfolioCompositionVersionOption {
  portfolio_ref: string
  membership_version: number
  source_type: PortfolioCompositionSource
  base_currency: string
  created_at: string
}

export interface PortfolioCompositionVersionPage {
  items: PortfolioCompositionVersionOption[]
  total: number
  page: number
  page_size: number
  has_more: boolean
}

export interface PortfolioResearchSourceArtifact {
  status: string
  report_integrity_status: string
  task_status: string | null
  asset_type: string | null
  canonical_id: string | null
  report_version: string | null
  report_content_hash: string | null
  report_created_at: string | null
  decision_status: string
  published_decision: {
    asset_type: string
    market_view: string
    normalized_direction: string
    recommendation: string
    actionability: string
    quality_status: string
    horizon_code: string
    execution_disabled: true
  } | null
  freshness_status: string
  currency: string | null
  currency_status: string
  account_value_status: string
}

export interface PortfolioImportedSourceArtifact {
  status: string
  import_version_id?: string
  portfolio_name?: string
  import_format: string | null
  source_integrity_status?: string
  source_schema_version: number | null
  source_sha256: string | null
  source_as_of: string | null
  source_as_of_status: string
  source_currency: string | null
  currency_status: string
  freshness_status: string
  source_row_count: number | null
  trade_date_rows_present: number | null
  trade_date_coverage: string
  source_metadata_status: string
  source_rows_available: boolean
}

export type PortfolioCompositionSourceFacts = {
  kind: 'asset_research_reports'
  research_facts_available: boolean
  freshness_status: string
  currency_status: string
  artifacts: PortfolioResearchSourceArtifact[]
} | {
  kind: 'portfolio_ledger_import_versions'
  source_materials_verified: boolean
  freshness_status: string
  account_value_status: string
  artifacts: PortfolioImportedSourceArtifact[]
}

export interface PortfolioExecutionBookPosition {
  instrument: string
  net_quantity: string
}

export interface PortfolioExecutionBookFee {
  currency: string
  amount: string
}

export interface PortfolioFinancialAmount {
  currency: string
  amount: string
}

export interface PortfolioFinancialWatermark {
  source_kind: 'execution_outbox' | 'account_facts' | 'account_activity'
  source_ref: string
  generation: string
  cursor: number
  as_of_ns: string
}

export interface PortfolioFinancialLedgerCut {
  owner_directory_revision: string
  captured_at_ns: string
  watermarks: PortfolioFinancialWatermark[]
}

export interface PortfolioFinancialPosition {
  instrument: string
  quantity: string
  cost_basis: string | null
  cost_currency: string | null
  cost_method: 'AVERAGE_COST'
  product_model: 'SPOT'
  metadata_version: string
}

export interface PortfolioFinancialOwnerBook {
  owner: {
    kind: 'STRATEGY' | 'MANUAL_BOOK'
    owner_ref: string
  }
  cash: PortfolioFinancialAmount[]
  positions: PortfolioFinancialPosition[]
  cumulative_fees: PortfolioFinancialAmount[]
  realized_pnl: PortfolioFinancialAmount[]
  cost_basis_complete: boolean
}

export type PortfolioFinancialProjection = {
  status: 'absent'
} | {
  status: 'unavailable'
  code:
    | 'FINANCIAL_DIRECTORY_UNAVAILABLE'
    | 'FINANCIAL_DIRECTORY_MISMATCH'
    | 'PERSISTED_PROJECTION_UNAVAILABLE'
    | 'INCOMPLETE_PERSISTED_PROJECTION'
    | 'FINANCIAL_EXECUTION_CUT_MISMATCH'
  freshness: 'NOT_ESTABLISHED'
  cut_relationship: 'INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT'
} | {
  status: 'available'
  source: 'PERSISTED_EXECUTION_FINANCIAL_PROJECTION'
  freshness: 'PERSISTED_CUT_NOT_LIVE_SOURCE_VERIFIED'
  cut_relationship: 'INDEPENDENT_OF_LEGACY_ACCOUNT_BOOK_CUT'
  complete: boolean
  state: 'BALANCED' | 'RESIDUAL'
  ledger_cut: PortfolioFinancialLedgerCut
  books: PortfolioFinancialOwnerBook[]
  unallocated: {
    cash: PortfolioFinancialAmount[]
    positions: Array<{ instrument: string; quantity: string }>
    fees: PortfolioFinancialAmount[]
  }
}

export interface PortfolioProviderAccountResource {
  product_type: string
  margin_pool: string
}

export interface PortfolioProviderAccountBalance {
  resource: PortfolioProviderAccountResource
  currency: string
  total: string | null
  available: string | null
  locked: string | null
  observed_at_utc: string
}

export type PortfolioValuationInputStatus =
  | 'available'
  | 'coverage_incomplete'
  | 'error'
  | 'missing'
  | 'not_calculated'
  | 'not_required'
  | 'stale'
  | 'unavailable'
  | 'unsupported'

export interface PortfolioValuationSource {
  binding_ref: string
  binding_version: string
  provenance_ref: string
  canonical_id: string
  metadata_version: string
  family_id: string
  family_contract_version: string
  source_policy_id: string
  query_id: string | null
}

export interface PortfolioValuationCoverage {
  status: string
  expected_event_count: number
  accepted_event_count: number
  missing_event_count: number
  coverage_ratio: number | null
  rejection_counts: Record<string, number>
  next_page_available: boolean
}

export interface PortfolioValuationInput {
  status: PortfolioValuationInputStatus
  code?: string | null
  value: string | null
  currency?: string
  unit?: string
  price_basis?: string
  source?: PortfolioValuationSource
  observed_at_utc?: string
  available_at_utc?: string
  committed_at_utc?: string
  quality?: string
  revision_id?: string
  source_snapshot_id?: string
  revision_number?: number
  age_seconds?: number
  freshness_max_age_seconds?: number
  from_currency?: string
  to_currency?: string
  rate_convention?: 'to_per_from'
  binding_ref?: string
  binding_version?: string
  provenance_ref?: string
  metadata_version?: string
  quantity_unit?: string
  position_quantity_unit?: string
  valid_from_utc?: string
  valid_to_utc?: string | null
  coverage?: PortfolioValuationCoverage
  query_cut?: {
    knowledge_cutoff_utc: string
    identity_knowledge_cutoff_utc: string
    cursor_available: boolean
    fetches: Array<{
      route_id: string
      provider_id: string
      source_snapshot_id: string
    }>
    warnings: string[]
  }
}

export interface PortfolioMarketCut {
  cut_model: 'independent_account_and_market_data_cuts'
  atomic: false
  account_position_observed_at_utc: string | null
  market_event_at_utc: string | null
  market_available_at_utc: string | null
  market_committed_at_utc: string | null
  account_to_market_skew_ns: string | null
  query_id: string | null
  knowledge_cutoff_utc: string | null
  identity_metadata_version: string
  cursor_available: boolean
  coverage: PortfolioValuationCoverage | null
}

export interface PortfolioProviderAccountPosition {
  resource: PortfolioProviderAccountResource
  instrument: {
    provider: string
    venue: string
    environment: string
    product_type: string
    instrument_id: string
    native_symbol: string
  }
  side: 'net' | 'long' | 'short'
  quantity: string
  qty_unit: string
  average_price: string | null
  price_currency: string | null
  observed_at_utc: string
  valuation_binding?: {
    status: 'configured'
    binding_ref: string
    binding_version: string
    valid_from_utc: string | null
    valid_to_utc: string | null
  }
  valuation_inputs: {
    status?: PortfolioValuationInputStatus
    mark_price: PortfolioValuationInput
    contract_multiplier: PortfolioValuationInput
    fx_rate: PortfolioValuationInput
    market_value: PortfolioValuationInput
    market_cut?: PortfolioMarketCut
    fx_market_cut?: PortfolioMarketCut
  }
}

export interface PortfolioMarketValuationSummary {
  status: 'not_collected' | 'current' | 'incomplete'
  code: string | null
  position_count: number
  position_status_counts: Record<string, number>
  cut_model: 'independent_market_query_per_identity'
  atomic: false
  market_event_skew_ns: string | null
  reconciliation_status: 'not_established'
  account_total_included: false
  creditable: false
}

type PortfolioProviderAccountObservationDetails = {
  quality: 'fresh' | 'stale' | 'not_collected' | 'unavailable'
  source: 'AUTHORIZED_PROVIDER_ACCOUNT_OBSERVATION'
  observation_id: string
  session_generation: string | null
  cursor: number | null
  consistency: 'provider_atomic' | 'multi_query'
  cut: {
    started_at_utc: string
    completed_at_utc: string
    earliest_row_observed_at_utc: string | null
    latest_row_observed_at_utc: string | null
    row_skew_ns: string | null
    row_observed_at_count: number
    row_count: number
  }
  coverage: {
    resources: PortfolioProviderAccountResource[]
    balances_complete: boolean
    positions_complete: boolean
    state: 'complete' | 'incomplete'
  }
  valuation: {
    currency: string
    available_cash: string | null
    equity: string | null
    observed_at_utc: string
  } | null
  balances: PortfolioProviderAccountBalance[]
  positions: PortfolioProviderAccountPosition[]
}

export type PortfolioProviderAccountObservation = {
  status: 'absent'
  code: string
} | {
  status: 'unavailable'
  code: string
} | (PortfolioProviderAccountObservationDetails & {
  status: 'available'
}) | (PortfolioProviderAccountObservationDetails & {
  status: 'stale'
})

export interface PortfolioExecutionOwnerBook {
  owner_kind: 'STRATEGY' | 'MANUAL_BOOK' | 'UNALLOCATED'
  owner_ref: string
  current_positions: PortfolioExecutionBookPosition[]
  fees_since_baseline: PortfolioExecutionBookFee[]
}

export interface PortfolioAccountBookSource {
  account_ref: string
  state: string
  coverage: {
    scope_directory_revision: string
    journal_generation: string
    baseline_execution_cursor: number
    current_execution_cursor: number
    complete: boolean
    reasons: string[]
    scanned_outbox_events: number
    outbox_history_contiguous: boolean
    outbox_scan_complete: boolean
    continuations: unknown[]
    input_continuations: unknown[]
    quarantined_intents: unknown[]
  }
  provider_position_change: PortfolioExecutionBookPosition[]
  /** Optional for compatibility with projections written before this field was added. */
  unallocated_book?: PortfolioExecutionOwnerBook | null
  position_residual: PortfolioExecutionBookPosition[]
  fee_residual: PortfolioExecutionBookFee[]
  /** Persisted execution financial facts, kept separate from the provider account total. */
  financial?: PortfolioFinancialProjection
}

export interface PortfolioCompositionProjection {
  portfolio_ref: string
  membership_version: number
  source_type: PortfolioCompositionSource
  source_status: string
  base_currency: string
  projection_kind: 'display_only'
  creditable: false
  overlap_policy: 'non_additive_display_only'
  source_facts?: PortfolioCompositionSourceFacts
  account_total: {
    status: string
    currency: string | null
    value: string | null
  }
  accounts: Array<{
    member_ref: string
    currency: string
    quality: string
    cash: string | null
    value: string | null
    included_in_total: boolean
    duplicate_of_ref: string | null
    detail_code: string | null
    provider_observation?: PortfolioProviderAccountObservation
  }>
  provider_snapshot_consistency?: {
    cut_model: 'independent_provider_observation_per_account'
    atomic: false
    member_read_count: number
    observation_count: number
    consistency_modes: string[]
    coverage_status: string
    coverage_complete: boolean | null
    earliest_completed_at_utc: string | null
    latest_completed_at_utc: string | null
    skew_ns: string | null
    skew_policy: 'reported_without_threshold'
    status: string
  }
  market_valuation?: PortfolioMarketValuationSummary
  /** Optional so older servers remain readable while the live book projection rolls out. */
  account_book_sources?: PortfolioAccountBookSource[]
  strategies: Array<{
    strategy_ref: string
    attribution_status: string
    attributed_value: string | null
  }>
  strategy_attribution: {
    status: string
    strategy_count: number
    attributed_value: string | null
    unattributed_account_value: string | null
    residual_basis: string
  }
  coverage: {
    complete: boolean
    account_facts_complete?: boolean
    strategy_attribution_complete?: boolean
    research_facts_available?: boolean
    code: string | null
  }
}

export interface PositionItem {
  strategy_id: string
  strategy_name: string
  instance_id: string
  data_name: string
  size: number
  price: number
  latest_price?: number | null
  market_value: number
  signed_market_value?: number
  long_market_value?: number
  short_market_value?: number
  position_pnl?: number
  gross_pnl?: number
  commission?: number
  commission_source?: string | null
  multiplier?: number
  margin_rate?: number
  leverage?: number
  margin_value?: number
  direction: string
  long_position?: number
  short_position?: number
  trading_mode?: string
  updated_at?: string | null
  data_time?: string | null
  position_source?: string | null
  asset_spec_source?: string | null
  valuation_status?: string | null
  valuation_warnings?: string[]
}

export interface PositionSummary {
  total_long_value: number
  total_short_value: number
  gross_market_value: number
  net_market_value: number
  total_pnl: number
  long_count: number
  short_count: number
  flat_count: number
}

export interface TradeItem {
  strategy_id: string
  strategy_name: string
  instance_id: string
  workspace_id?: string
  ref: number
  datetime: string
  dtopen: string
  dtclose: string
  data_name: string
  direction: string
  size: number
  price: number
  value: number
  commission: number
  pnl: number
  pnlcomm: number
  barlen: number
}

export interface EquityStrategy {
  strategy_id: string
  strategy_name: string
  instance_id: string
  values: number[]
  pnl_values?: number[]
  value_source?: string
}

export interface PortfolioEquity {
  dates: string[]
  total_equity: number[]
  cumulative_pnl: number[]
  total_drawdown: number[]
  strategies: EquityStrategy[]
}

export interface AllocationItem {
  asset: string
  value: number
  weight: number
  long_value: number
  short_value: number
  net_value: number
  position_count: number
}

export const portfolioApi = {
  getOverview(summaryOnly = false): Promise<PortfolioOverview> {
    if (!summaryOnly) return request.get('/portfolio/overview')
    return request.get('/portfolio/overview/summary')
  },

  listCompositionVersions(page = 1, pageSize = 50): Promise<PortfolioCompositionVersionPage> {
    return request.get('/portfolio/compositions', {
      params: { page, page_size: pageSize },
    })
  },

  createCompositionVersion(payload: {
    portfolio_ref: string
    source_type: PortfolioCompositionSource
    base_currency: string
    members: Array<{
      kind: 'account' | 'strategy' | 'research_artifact' | 'imported_ledger' | 'paper_account'
      ref: string
    }>
  }): Promise<{
    portfolio_ref: string
    membership_version: number
    source_type: PortfolioCompositionSource
    base_currency: string
    created_at: string
    membership_sha256: string
    members: Array<{ kind: string; ref: string }>
    creditable: false
  }> {
    return request.post('/portfolio/compositions', payload)
  },

  getCompositionProjection(
    portfolioRef: string,
    membershipVersion: number,
  ): Promise<PortfolioCompositionProjection> {
    return request.get('/portfolio/overview', {
      params: { portfolio_ref: portfolioRef, membership_version: membershipVersion },
    })
  },

  getPositions(): Promise<{ total: number; positions: PositionItem[]; summary?: PositionSummary; warnings?: string[] }> {
    return request.get('/portfolio/positions')
  },

  getTrades(limit = 200, workspaceIds: string[] = [], includeInactive = false): Promise<{ total: number; trades: TradeItem[] }> {
    const ids = workspaceIds.filter(Boolean)
    const params: { limit: number; workspace_ids?: string; include_inactive?: boolean } = { limit }
    if (ids.length > 0) params.workspace_ids = ids.join(',')
    if (includeInactive) params.include_inactive = true
    return request.get('/portfolio/trades', { params })
  },

  getEquity(workspaceIds: string[] = [], includeInactive = false): Promise<PortfolioEquity> {
    const ids = workspaceIds.filter(Boolean)
    const params: { workspace_ids?: string; include_inactive?: boolean } = {}
    if (ids.length > 0) params.workspace_ids = ids.join(',')
    if (includeInactive) params.include_inactive = true
    return request.get('/portfolio/equity', { params })
  },

  getAllocation(workspaceIds: string[] = []): Promise<{ total: number; items: AllocationItem[] }> {
    const ids = workspaceIds.filter(Boolean)
    const params: { workspace_ids?: string } = {}
    if (ids.length > 0) params.workspace_ids = ids.join(',')
    return request.get('/portfolio/allocation', { params })
  },
}
