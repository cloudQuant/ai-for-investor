import type {
  AIStrategyGateGap,
  AIStrategyIterationProgress,
  AIStrategyLiveHandoffPackage,
  AIStrategyLiveReadinessItem,
  AIStrategyPaperMonitoringRule,
  AIStrategyPaperReviewLock,
  AIStrategyPaperTradingReview,
  AIStrategyPaperTradingRuleEvaluation,
  AIStrategyPaperTradingStart,
  AIStrategyPipelineStep,
  AIStrategyPipelineSummary,
  AIStrategyPromotionAuditItem,
  AIStrategyResearchIteration,
  AIStrategyResearchRunRecord,
  AIStrategyResearchTaskResponse,
  AIStrategyResearchVersion,
} from '@/api/strategy'
import {
  AI_RESEARCH_LIVE_HANDOFF_STATUS_LABELS,
  AI_RESEARCH_LIVE_READINESS_STATUS_LABELS,
  AI_RESEARCH_PAPER_REVIEW_STATUS_LABELS,
  AI_RESEARCH_PAPER_RULE_STATUS_LABELS,
  AI_RESEARCH_PIPELINE_STEP_STATUS_LABELS,
  AI_RESEARCH_RUN_STATUS_LABELS,
  AI_RESEARCH_STAGE_LABELS,
} from './aiResearchConstants'
import type { AIResearchAutoContinuationSource } from './aiResearchTaskTypes'
import {
  arrayFromUnknown,
  isRecord,
  optionalNumber,
  stringArrayFromUnknown,
  stringFromUnknown,
  uniqueTextItems,
} from './aiResearchValueAdapters'

export function formatMetric(value: unknown, digits = 2) {
  if (value === null || value === undefined || value === '') return '-'
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number)) return '-'
  return number.toFixed(digits)
}

export function formatComparisonValue(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? String(number) : '-'
}

export function gateGapListFromUnknown(value: unknown): AIStrategyGateGap[] {
  if (!Array.isArray(value)) return []
  return value
    .filter(isRecord)
    .map(item => ({
      key: stringFromUnknown(item.key),
      label: stringFromUnknown(item.label),
      actual: optionalNumber(item.actual),
      target: optionalNumber(item.target),
      direction: stringFromUnknown(item.direction),
      gap: optionalNumber(item.gap),
      gap_ratio: optionalNumber(item.gap_ratio),
      distance_to_pass: optionalNumber(item.distance_to_pass),
      score: optionalNumber(item.score),
      status: stringFromUnknown(item.status),
    }))
    .filter(item => item.key || item.label)
}

export function gateGapText(gap: AIStrategyGateGap) {
  const label = gap.label || gap.key || '质量门槛'
  const distance = gap.distance_to_pass ?? gap.gap
  const parts = [label]
  if (distance !== null && distance !== undefined) {
    parts.push(`还差 ${formatMetric(distance)}`)
  } else if (gap.status === 'unavailable') {
    parts.push('缺少指标')
  }
  const actual = gap.actual !== null && gap.actual !== undefined
    ? `当前 ${formatMetric(gap.actual)}`
    : ''
  const target = gap.target !== null && gap.target !== undefined
    ? `目标 ${formatMetric(gap.target)}`
    : ''
  const ratio = gap.gap_ratio !== null && gap.gap_ratio !== undefined
    ? `差距 ${formatMetric(Number(gap.gap_ratio) * 100, 0)}%`
    : ''
  return [parts.join(' '), actual, target, ratio].filter(Boolean).join('，')
}

export function formatTaskProgress(value: unknown) {
  const number = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(number) || number <= 0) return ''
  return `${Math.round(number)}%`
}

export function taskLatestIterationMetric(
  iteration: Record<string, unknown>,
  ...keys: string[]
) {
  for (const key of keys) {
    const value = optionalNumber(iteration[key])
    if (value !== null) return value
  }
  const metrics = iteration.metrics
  if (isRecord(metrics)) {
    for (const key of keys) {
      const value = optionalNumber(metrics[key])
      if (value !== null) return value
    }
  }
  return null
}

export function taskLatestIterationLabel(iteration: Record<string, unknown>) {
  const number = taskLatestIterationMetric(iteration, 'iteration')
  return number === null ? '一轮' : `第 ${formatMetric(number, 0)} 轮`
}

export function taskLatestIterationProgress(iteration: Record<string, unknown> | null) {
  if (!iteration) return null
  const diagnostics = isRecord(iteration.diagnostics) ? iteration.diagnostics : {}
  const progress = isRecord(diagnostics.iteration_progress)
    ? diagnostics.iteration_progress
    : iteration.iteration_progress
  return isRecord(progress) ? progress as AIStrategyIterationProgress : null
}

export function strategyGenerationText(value: unknown) {
  if (!isRecord(value)) return ''
  const source = stringFromUnknown(value.source)
  const model = stringFromUnknown(value.model_id)
  const provider = stringFromUnknown(value.provider)
  const fallbackReason = stringFromUnknown(value.fallback_reason)
  const sourceLabel: Record<string, string> = {
    ai_initial_draft: 'AI初稿',
    ai_model: 'AI改稿',
    local_rules: '本地规则改稿',
    local_fallback: '本地回退改稿',
    local_initial_fallback: '本地初稿回退',
    local_code_repair_fallback: '本地代码修复',
    seed_strategy: '种子策略',
    continued_run_seed: '历史记录种子',
    local_seed: '本地种子',
  }
  const label = sourceLabel[source] || source || '草案来源'
  const parts = [label]
  if (model) parts.push(`模型 ${model}`)
  else if (provider && provider !== 'local') parts.push(provider)
  if (fallbackReason) parts.push(`回退 ${fallbackReason}`)
  return parts.join(' · ')
}

export function taskLatestIterationDiagnostics(iteration: Record<string, unknown> | null) {
  if (!iteration) return null
  const diagnostics = isRecord(iteration.diagnostics) ? iteration.diagnostics : {}
  const summary = stringFromUnknown(diagnostics.summary)
  const failures = uniqueTextItems([
    stringFromUnknown(iteration.failure_reason),
    ...stringArrayFromUnknown(iteration.quality_gate_failures),
    ...stringArrayFromUnknown(iteration.validation_failures),
    ...stringArrayFromUnknown(diagnostics.weaknesses),
  ]).slice(0, 4)
  const improvementPlan = uniqueTextItems([
    ...stringArrayFromUnknown(iteration.improvement_plan),
    ...stringArrayFromUnknown(diagnostics.improvement_plan),
  ]).slice(0, 4)
  const gateGaps = gateGapListFromUnknown(diagnostics.gate_gaps).slice(0, 3)
  const nextActions = uniqueTextItems(stringArrayFromUnknown(iteration.next_actions)).slice(0, 3)
  const generationText = strategyGenerationText(diagnostics.strategy_generation)
  if (
    !summary
    && !failures.length
    && !gateGaps.length
    && !improvementPlan.length
    && !nextActions.length
    && !generationText
  ) {
    return null
  }
  return {
    summary,
    failures,
    gateGaps,
    improvementPlan,
    nextActions,
    generationText,
  }
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

export function outOfSampleRatioPct(value: unknown) {
  const ratio = optionalNumber(value)
  if (ratio === null) return 25
  return ratio <= 1 ? Math.round(ratio * 100) : ratio
}

export function aiResearchAutoContinuationSource(
  source: Pick<
    AIStrategyResearchRunRecord,
    | 'prompt'
    | 'workflow_mode'
    | 'mandate_id'
    | 'request_explicit_fields'
    | 'request_explicit_fields_persisted'
  >,
): AIResearchAutoContinuationSource | null {
  if (
    source.request_explicit_fields_persisted !== true
    || source.workflow_mode !== 'auto'
    || !Array.isArray(source.request_explicit_fields)
    || source.request_explicit_fields.some(field => String(field).trim() === 'prompt')
  ) {
    return null
  }
  const prompt = source.prompt.trim()
  const mandateId = stringFromUnknown(source.mandate_id)
  return prompt && mandateId ? { prompt, mandateId } : null
}

export function aiResearchTaskAutoContinuationSourceFromTask(
  task: AIStrategyResearchTaskResponse,
): AIResearchAutoContinuationSource | null {
  const snapshot = isRecord(task.request_snapshot) ? task.request_snapshot : null
  if (!snapshot || !Object.prototype.hasOwnProperty.call(task, 'request_explicit_fields')) {
    return null
  }
  const snapshotMandateId = stringFromUnknown(snapshot.mandate_id)
  const taskMandateId = stringFromUnknown(task.mandate_id)
  if (snapshotMandateId && taskMandateId && snapshotMandateId !== taskMandateId) return null
  return aiResearchAutoContinuationSource({
    prompt: stringFromUnknown(snapshot.prompt),
    workflow_mode: snapshot.workflow_mode === 'prompt' ? 'prompt' : 'auto',
    mandate_id: snapshotMandateId || taskMandateId,
    request_explicit_fields: task.request_explicit_fields,
    request_explicit_fields_persisted: task.request_explicit_fields_persisted,
  })
}

export function mandateQualityGateSummary(gates: Record<string, unknown>) {
  const parts = [
    `Sharpe ${formatMetric(gates.target_sharpe)}`,
    `交易 ${formatMetric(gates.min_total_trades, 0)}`,
  ]
  if (gates.max_drawdown_limit !== null && gates.max_drawdown_limit !== undefined) {
    parts.push(`回撤 ${formatMetric(gates.max_drawdown_limit)}`)
  }
  if (gates.min_win_rate !== null && gates.min_win_rate !== undefined) {
    parts.push(`胜率 ${formatMetric(gates.min_win_rate)}`)
  }
  return parts.join(' · ')
}

export function hasConfigKey(config: Record<string, unknown>, key: string) {
  return Object.prototype.hasOwnProperty.call(config, key)
}

export function configStringValue(config: Record<string, unknown>, key: string, fallback = '') {
  if (!hasConfigKey(config, key)) return fallback
  const value = config[key]
  return typeof value === 'string' ? value.trim() : fallback
}

export function formatAIResearchConfigJson(value: unknown) {
  return isRecord(value) && Object.keys(value).length ? JSON.stringify(value) : ''
}

export function researchRunTimestamp(record: AIStrategyResearchRunRecord) {
  const timestamp = Date.parse(record.completed_at || record.started_at)
  return Number.isNaN(timestamp) ? 0 : timestamp
}

export function aiResearchEventTagType(status?: string | null) {
  const normalized = stringFromUnknown(status)
  if (normalized === 'completed' || normalized === 'submitted') return 'success'
  if (normalized === 'failed') return 'danger'
  if (normalized === 'started' || normalized === 'running') return 'warning'
  return 'info'
}

export function aiResearchVersionStatusTagType(status?: string | null) {
  const normalized = stringFromUnknown(status)
  if (normalized === 'passed') return 'success'
  if (normalized === 'failed') return 'warning'
  return 'info'
}

export function aiResearchVersionMetric(version: AIStrategyResearchVersion, key: string) {
  return formatMetric(version.backtest_metrics?.[key])
}

export function aiResearchVersionMetricLabel(key: string) {
  const labels: Record<string, string> = {
    sharpe_ratio: 'Sharpe',
    sharpe: 'Sharpe',
    total_return: '总收益',
    annual_return: '年化收益',
    max_drawdown: '最大回撤',
    total_trades: '交易次数',
  }
  return labels[key] ?? key
}

export function researchRecordUsesManualCommission(record: AIStrategyResearchRunRecord) {
  const environment = record.backtest_environment
  if (!isRecord(environment)) return false
  return String(environment.commission_source || '').trim() === 'user_override'
}

export function resolvedAIResearchTaskBacktestEnvironment(
  task: AIStrategyResearchTaskResponse,
  snapshot: Record<string, unknown>,
) {
  if (isRecord(task.backtest_environment)) return task.backtest_environment
  if (isRecord(snapshot.backtest_environment)) return snapshot.backtest_environment
  return null
}

export function aiResearchTaskExplicitFields(task: AIStrategyResearchTaskResponse) {
  return Array.isArray(task.request_explicit_fields)
    ? task.request_explicit_fields.map(item => String(item).trim()).filter(Boolean)
    : []
}

export function aiResearchTaskUsesManualCommission(
  task: AIStrategyResearchTaskResponse,
  snapshot: Record<string, unknown>,
) {
  const environment = resolvedAIResearchTaskBacktestEnvironment(task, snapshot)
  if (environment) {
    const source = String(environment.commission_source || '').trim()
    if (source) return source === 'user_override'
  }
  const explicitFields = aiResearchTaskExplicitFields(task)
  if (explicitFields.length) return explicitFields.includes('commission')
  return optionalNumber(snapshot.commission) !== null
}

export function aiResearchTaskRestoredCommission(
  task: AIStrategyResearchTaskResponse,
  snapshot: Record<string, unknown>,
) {
  const environment = resolvedAIResearchTaskBacktestEnvironment(task, snapshot)
  const environmentCommission = environment ? optionalNumber(environment.commission) : null
  return environmentCommission ?? optionalNumber(snapshot.commission)
}

export function enabledQualityGate(enabled: boolean, value: number) {
  return enabled ? value : null
}

export function researchIterationNextActions(
  item: AIStrategyResearchIteration,
) {
  const nextActions = item.next_actions ?? []
  const improvementPlan = item.improvement_plan ?? item.diagnostics?.improvement_plan ?? []
  return [...new Set([...nextActions, ...improvementPlan])]
}

export function iterationProgress(item: AIStrategyResearchIteration) {
  const progress = item.diagnostics?.iteration_progress
  return isRecord(progress) ? progress as AIStrategyIterationProgress : null
}

export function aiResearchStageLabel(stage?: string | null) {
  const normalized = String(stage || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_STAGE_LABELS[normalized] ?? normalized.replace(/_/g, ' ')
}

export function iterationProgressLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  const labels: Record<string, string> = {
    baseline: '基准',
    improved: '改善',
    regressed: '退化',
    stalled: '停滞',
  }
  return labels[normalized] ?? aiResearchStageLabel(normalized || 'baseline')
}

export function iterationProgressTagType(status?: string | null) {
  const normalized = String(status || '').trim()
  if (normalized === 'improved') return 'success'
  if (normalized === 'regressed') return 'danger'
  if (normalized === 'stalled') return 'warning'
  return 'info'
}

export function iterationProgressDeltaText(
  progress: AIStrategyIterationProgress | null,
  key: 'sharpe_delta' | 'quality_score_delta',
) {
  const value = optionalNumber(progress?.[key])
  if (value === null) return ''
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatMetric(value)}`
}

export function canApproveLiveHandoff(handoff: AIStrategyLiveHandoffPackage | null | undefined) {
  return Boolean(
    handoff
    && handoff.ready_for_live
    && handoff.status === 'ready_for_approval'
    && !handoff.approval
    && !handoff.approval_status,
  )
}

export function isLiveTradingPreparedForRecord(
  record: AIStrategyResearchRunRecord | null | undefined,
) {
  return Boolean(
    record?.live_trading_prepared
    || record?.pipeline?.live_trading_prepared
    || record?.pipeline?.current_stage === 'live_trading_prepare',
  )
}

export function isLiveTradingActivatedForRecord(
  record: AIStrategyResearchRunRecord | null | undefined,
) {
  return Boolean(
    record?.pipeline?.live_handoff_activated
    || String(record?.pipeline?.live_handoff_activation_status || '').trim() === 'running',
  )
}

export function liveTradingPreparedAtFromPipeline(
  pipeline: AIStrategyPipelineSummary | null | undefined,
) {
  const step = [...(pipeline?.steps ?? [])]
    .reverse()
    .find(item => item.key === 'live_trading_prepare')
  return stringFromUnknown(step?.prepared_at)
}

export function liveHandoffApprovalLabel(handoff: AIStrategyLiveHandoffPackage | null | undefined) {
  const approval = handoff?.approval
  if (!approval) return ''
  if (approval.approved) return '已批准'
  if (approval.decision === 'rejected') return '已驳回'
  return approval.decision || ''
}

export function liveTradingPrepareSummary(
  record: AIStrategyResearchRunRecord | null | undefined,
) {
  if (!record) return ''
  const unitId = record.live_unit_id || record.pipeline?.live_unit_id || '实盘单元'
  const preparedAt = record.live_trading_prepared_at
    || record.pipeline?.live_trading_prepared_at
    || liveTradingPreparedAtFromPipeline(record.pipeline)
  if (isLiveTradingActivatedForRecord(record)) {
    const instanceId = record.pipeline?.live_handoff_activation_instance_id
    return `${unitId} 已由受控服务启动${instanceId ? `，实例 ${instanceId}` : ''}`
  }
  const lockText = record.pipeline?.live_unit_locked === false ? '待确认锁定' : '默认锁定'
  return `${unitId} 已准备，${lockText}${preparedAt ? `，${formatDateTime(preparedAt)}` : ''}`
}

export function isPaperTradingTargetMissing(record: AIStrategyResearchRunRecord) {
  const status = String(record.paper_review_status || '').trim()
  return Boolean(
    ['paper_workspace_missing', 'paper_unit_missing'].includes(status)
    || (
      record.paper_trading_started
      && (!record.paper_workspace_id || !record.paper_unit_id)
    ),
  )
}

export function isPaperTradingStartFailure(record: AIStrategyResearchRunRecord) {
  return Boolean(
    record.pipeline?.current_stage === 'paper_trading_failed'
    || record.pipeline?.paper_trading_error,
  )
}

export function paperStartButtonLabel(record: AIStrategyResearchRunRecord) {
  if (isPaperTradingTargetMissing(record)) return '重启模拟'
  if (isPaperTradingStartFailure(record)) return '重试模拟'
  return '启动模拟'
}

export function continuationSourceLabel(source?: string | null) {
  if (source === 'paper_review') return '从模拟复核反馈继续'
  if (source === 'paper_trading_failed') return '从模拟启动失败继续'
  if (source === 'live_handoff_rejected') return '从实盘交接驳回继续'
  if (source === 'research_cancelled') return '从已取消任务继续'
  if (source === 'research_interrupted') return '从中断任务继续'
  if (source === 'research_failure') return '从未达标结果继续'
  return '从历史最佳策略继续'
}

export function stringListFromUnknown(value: unknown) {
  if (!Array.isArray(value)) return []
  return value.map(item => stringFromUnknown(item)).filter(Boolean)
}

export function continuationIterationPayload(record: AIStrategyResearchRunRecord) {
  const iterations = record.iterations.filter(isRecord)
  if (!iterations.length) return null
  const bestIteration = optionalNumber(record.best_iteration)
  if (bestIteration !== null) {
    const bestPayload = iterations.find(item => optionalNumber(item.iteration) === bestIteration)
    if (bestPayload) return bestPayload
  }
  return iterations[iterations.length - 1]
}

export function paperReviewFailureText(item: AIStrategyPaperTradingRuleEvaluation) {
  const label = stringFromUnknown(item.label, stringFromUnknown(item.key, '模拟交易复核'))
  const actual = optionalNumber(item.actual)
  const threshold = optionalNumber(item.threshold)
  const actualText = actual === null ? '' : `实际 ${formatMetric(actual)}`
  const thresholdText = threshold === null ? '' : `阈值 ${formatMetric(threshold)}`
  const action = stringFromUnknown(item.action)
  const parts = [actualText, thresholdText].filter(Boolean).join('，')
  return `${label}未通过${parts ? `（${parts}）` : ''}${action ? `，${action}` : ''}`
}

export function pipelineStage(record: AIStrategyResearchRunRecord) {
  if (record.live_trading_prepared || record.pipeline?.current_stage === 'live_trading_prepare') {
    return 'live_trading_prepare'
  }
  if (record.live_handoff || record.pipeline?.current_stage === 'live_handoff') return 'live_handoff'
  if (record.paper_review_ready_for_live) return 'live_candidate'
  if (record.paper_review_status) return 'paper_review'
  if (record.paper_trading_started) return 'paper_trading'
  if (record.pipeline?.current_stage) return record.pipeline.current_stage
  if (record.achieved) return 'quality_achieved'
  if (record.status === 'timeout') return 'backtest_timeout'
  if (record.status === 'cancelled') return 'cancelled'
  return record.iteration_count > 0 ? 'research_iteration' : ''
}

export function pipelineStageLabel(record: AIStrategyResearchRunRecord) {
  return aiResearchStageLabel(pipelineStage(record))
}

export function aiResearchRunStatusLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_RUN_STATUS_LABELS[normalized] ?? aiResearchStageLabel(normalized)
}

export function paperReviewStatusLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_PAPER_REVIEW_STATUS_LABELS[normalized] ?? aiResearchStageLabel(normalized)
}

export function liveReadinessStatusLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_LIVE_READINESS_STATUS_LABELS[normalized] ?? aiResearchStageLabel(normalized)
}

export function paperReviewRuleStatusLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_PAPER_RULE_STATUS_LABELS[normalized] ?? liveReadinessStatusLabel(normalized)
}

export function paperReviewRuleGapText(rule: AIStrategyPaperTradingRuleEvaluation) {
  const distance = optionalNumber(rule.distance_to_pass ?? rule.gap)
  if (distance !== null && distance > 0) {
    return `差距 ${formatMetric(distance)}`
  }
  const margin = optionalNumber(rule.margin)
  if (margin !== null && margin > 0) {
    return `余量 ${formatMetric(margin)}`
  }
  return ''
}

export function paperReviewDispositionLabel(review: AIStrategyPaperTradingReview | null | undefined) {
  const status = String(review?.status || '').trim()
  if (review?.ready_for_live) return '实盘候选'
  if (status === 'live_readiness_expired') return '重新复核'
  if (status === 'needs_research_review') return '需要重新投研'
  if (['paper_workspace_missing', 'paper_unit_missing', 'monitoring_plan_missing'].includes(status)) {
    return '检查模拟'
  }
  if (status === 'monitoring') return '继续观察'
  return '待处理'
}

export function liveHandoffStatusLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_LIVE_HANDOFF_STATUS_LABELS[normalized] ?? aiResearchStageLabel(normalized)
}

export function pipelineStepStatusLabel(status?: string | null) {
  const normalized = String(status || '').trim()
  if (!normalized) return ''
  return AI_RESEARCH_PIPELINE_STEP_STATUS_LABELS[normalized] ?? aiResearchStageLabel(normalized)
}

export function pipelineStepTagType(status?: string | null) {
  const normalized = String(status || '').trim()
  if (normalized === 'completed') return 'success'
  if (normalized === 'failed') return 'danger'
  if (normalized === 'running') return 'warning'
  return 'info'
}

export function pipelineStepIterationText(step: AIStrategyPipelineStep) {
  const count = typeof step.iteration_count === 'number' ? step.iteration_count : null
  const max = typeof step.max_iterations === 'number' ? step.max_iterations : null
  if (count === null && max === null) return ''
  if (count !== null && max !== null) return `${count}/${max} 轮`
  if (count !== null) return `${count} 轮`
  return `最多 ${max} 轮`
}

export function liveReadinessChecklistFromPayload(
  payload: unknown,
): AIStrategyLiveReadinessItem[] {
  if (!Array.isArray(payload)) return []
  return payload.filter(isRecord).map((item, index) => ({
    key: String(item.key || `item-${index}`),
    label: String(item.label || item.key || `检查项 ${index + 1}`),
    status: String(item.status || 'pending'),
    evidence: String(item.evidence || ''),
    action: String(item.action || ''),
    details: isRecord(item.details) ? item.details : undefined,
  }))
}

export function promotionAuditFromPayload(payload: unknown): AIStrategyPromotionAuditItem[] {
  if (!Array.isArray(payload)) return []
  return payload.filter(isRecord).map((item, index) => ({
    key: String(item.key || `audit-${index}`),
    label: String(item.label || item.key || `审计项 ${index + 1}`),
    status: String(item.status || 'pending'),
    evidence: String(item.evidence || ''),
    action: String(item.action || ''),
    details: isRecord(item.details) ? item.details : undefined,
  }))
}

export function paperReviewLockFromPayload(payload: unknown): AIStrategyPaperReviewLock | null {
  if (!isRecord(payload)) return null
  if (!payload.status && !payload.paper_unit_id && !payload.stop_results) return null
  return {
    ...payload,
    failed_rules: arrayFromUnknown<AIStrategyPaperTradingRuleEvaluation>(payload.failed_rules),
    stop_results: arrayFromUnknown<Record<string, unknown>>(payload.stop_results),
    next_actions: stringArrayFromUnknown(payload.next_actions),
  } as AIStrategyPaperReviewLock
}

export function paperReviewLockSummary(lock: AIStrategyPaperReviewLock | null | undefined) {
  if (!lock) return ''
  const unitId = stringFromUnknown(lock.paper_unit_id, '模拟单元')
  const status = paperReviewStatusLabel(lock.status)
  return `${unitId} ${status || '复核未通过'}，已自动停止并锁定`
}

export function paperReviewLockStopResultText(lock: AIStrategyPaperReviewLock | null | undefined) {
  const results = lock?.stop_results ?? []
  if (!results.length) return ''
  return results
    .map(item => {
      const unitId = stringFromUnknown(item.unit_id, stringFromUnknown(lock?.paper_unit_id, '模拟单元'))
      if (item.cancelled === true) return `${unitId} 已取消`
      const status = stringFromUnknown(item.status)
      if (status) return `${unitId} ${status}`
      return unitId
    })
    .join('；')
}

export function paperMonitoringPlanFromHandoff(
  handoff: Record<string, unknown> | null | undefined,
): AIStrategyPaperMonitoringRule[] | undefined {
  const plan = handoff?.paper_monitoring_plan
  return Array.isArray(plan) ? (plan as AIStrategyPaperMonitoringRule[]) : undefined
}

export function paperTradingStartError(paper: AIStrategyPaperTradingStart) {
  const status = String(paper.run_result?.status || '').trim()
  if (status) return `Paper trading run finished with status ${status}`
  return 'Paper trading run did not return a runnable task'
}

export function paperHandoffRunRecordAssetSpecs(
  record: AIStrategyResearchRunRecord,
  handoff: Record<string, unknown>,
): Record<string, Record<string, unknown>> | undefined {
  const specs: Record<string, Record<string, unknown>> = {}
  const merge = (source: unknown) => {
    if (!isRecord(source)) return
    for (const [symbol, spec] of Object.entries(source)) {
      if (isRecord(spec)) specs[symbol] = { ...spec }
    }
  }
  merge(record.asset_specs)
  merge(handoff.asset_specs)
  return Object.keys(specs).length ? specs : record.asset_specs
}

export function paperHandoffRunRecordBacktestEnvironment(
  record: AIStrategyResearchRunRecord,
  handoff: Record<string, unknown>,
): Record<string, unknown> | undefined {
  const environment: Record<string, unknown> = {}
  if (isRecord(record.backtest_environment)) Object.assign(environment, record.backtest_environment)
  if (isRecord(handoff.backtest_environment)) Object.assign(environment, handoff.backtest_environment)
  return Object.keys(environment).length ? environment : record.backtest_environment
}

export function liveReadinessChecklistForReview(
  review: AIStrategyPaperTradingReview | null | undefined,
): AIStrategyLiveReadinessItem[] {
  if (!review) return []
  if (review.live_readiness_checklist?.length) return review.live_readiness_checklist
  return liveReadinessChecklistFromPayload(review.pipeline?.live_readiness_checklist)
}

export function liveReadinessChecklistForRecord(
  record: AIStrategyResearchRunRecord,
): AIStrategyLiveReadinessItem[] {
  if (record.live_readiness_checklist?.length) return record.live_readiness_checklist
  const pipelineChecklist = liveReadinessChecklistFromPayload(
    record.pipeline?.live_readiness_checklist,
  )
  if (pipelineChecklist.length) return pipelineChecklist
  if (isRecord(record.paper_handoff)) {
    return liveReadinessChecklistFromPayload(record.paper_handoff.live_readiness_checklist)
  }
  return []
}

export function liveReadinessExpiresAtForRecord(record: AIStrategyResearchRunRecord): string | null {
  if (record.live_readiness_expires_at) return record.live_readiness_expires_at
  if (typeof record.pipeline?.live_readiness_expires_at === 'string') {
    return record.pipeline.live_readiness_expires_at
  }
  if (isRecord(record.paper_handoff) && typeof record.paper_handoff.live_readiness_expires_at === 'string') {
    return record.paper_handoff.live_readiness_expires_at
  }
  return null
}

export function paperReviewLockForRecord(
  record: AIStrategyResearchRunRecord | null | undefined,
): AIStrategyPaperReviewLock | null {
  if (!record) return null
  return paperReviewLockFromPayload(record.pipeline?.paper_review_lock)
    ?? paperReviewLockFromPayload(
      isRecord(record.paper_handoff) ? record.paper_handoff.paper_review_lock : null,
    )
}
