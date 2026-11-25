import type { StockAnalysisModule } from '@/api/stockAnalysis'

export interface AnalysisModuleOption {
  value: StockAnalysisModule
  label: string
  description: string
}

export interface ResearchDepthOption {
  value: string
  label: string
  description: string
  time: string
  modules: StockAnalysisModule[]
  debateRounds: number
  riskRounds: number
  memoryEnabled: boolean
}

export interface ReportMeta {
  symbol?: string
  symbol_name?: string
  market_type?: string
  analysis_date?: string
  research_depth?: string
}

export interface ReportDecision {
  label?: string
  target_price?: string | number | null
  confidence_score?: number | null
  risk_score?: number | null
  risk_level?: string
  reasoning?: string
  signal_action?: string
  eligibility_status?: string
  quality_reasons?: string[]
  feature_version?: string | null
  decision_policy_version?: string | null
  model_version?: string | null
}

export interface ReportSection {
  id: string
  title: string
  summary: string
  findings: string[]
  score?: number | null
}

export interface StockAnalysisReport {
  meta?: ReportMeta
  executive_summary?: string
  decision?: ReportDecision
  sections?: ReportSection[]
  disclaimer?: string
}
