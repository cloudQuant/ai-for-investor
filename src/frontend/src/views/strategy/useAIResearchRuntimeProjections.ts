import {
  containsRedactedSecret,
  isRecord,
  optionalBoolean,
  optionalNumber,
  stringFromUnknown,
} from './aiResearchValueAdapters'
import type {
  AIStrategyOutOfSampleValidation,
  AIStrategyQualityGateEvaluation,
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
} from '@/api/strategy'

export function useAIResearchRuntimeProjections({ t, formatMetric, aiResearchStageLabel, outOfSampleRatioPct }: {
  t: (key: string) => string
  formatMetric: (value: unknown, digits?: number) => string
  aiResearchStageLabel: (stage?: string | null) => string
  outOfSampleRatioPct: (value: unknown) => number
}) {

  function validationWindowFromUnknown(value: unknown): Record<string, string> | null {
    if (!isRecord(value)) return null
    const entries = Object.entries(value)
      .filter((entry): entry is [string, string] => typeof entry[1] === 'string')
    return entries.length ? Object.fromEntries(entries) : null
  }

  function outOfSampleValidationFromHandoff(
    handoff: Record<string, unknown> | null | undefined
  ): AIStrategyOutOfSampleValidation | null {
    if (!isRecord(handoff)) return null
    const payload = handoff.out_of_sample_validation
    if (!isRecord(payload)) return null
    return {
      status: typeof payload.status === 'string' ? payload.status : null,
      window: validationWindowFromUnknown(payload.window),
      metrics: isRecord(payload.metrics) ? payload.metrics : {},
      gate_evaluations: Array.isArray(payload.gate_evaluations)
        ? payload.gate_evaluations as AIStrategyQualityGateEvaluation[]
        : [],
      failures: Array.isArray(payload.failures)
        ? payload.failures.filter((item): item is string => typeof item === 'string')
        : [],
      failure_reason: typeof payload.failure_reason === 'string' ? payload.failure_reason : null,
    }
  }

  type PaperEnvironmentItem = {
    key: string
    label: string
    value: string
  }

  function hasResearchRuntimeEnvironment(record: AIStrategyResearchRunRecord) {
    return researchRuntimeItems(record).length > 0
  }

  function researchRuntimeItems(
    record: AIStrategyResearchRunRecord | null | undefined,
    handoff?: Record<string, unknown> | null
  ): PaperEnvironmentItem[] {
    const environment = runtimeEnvironmentPayload(record, handoff)
    const specs = runtimeAssetSpecsPayload(record, handoff)
    return runtimeItemsFromPayloads(environment, specs)
  }

  function runtimeItemsFromPayloads(
    environment: Record<string, unknown>,
    assetSpecs: Record<string, unknown>,
    requestSnapshot?: Record<string, unknown> | null
  ): PaperEnvironmentItem[] {
    const items = environmentItemsFromPayload(environment)
    const existing = new Set(items.map(item => item.key))
    const appendItem = (item: PaperEnvironmentItem) => {
      if (existing.has(item.key) || !item.value) return
      items.push(item)
      existing.add(item.key)
    }
    for (const item of gatewayRuntimeItemsFromSnapshot(requestSnapshot)) {
      appendItem(item)
    }
    const asset = firstRuntimeAssetSpecFromPayload(assetSpecs)
    if (!asset) return items

    if (!existing.has('asset_symbol')) {
      items.unshift({ key: 'asset_symbol', label: t('strategy.aiResearchAsset'), value: asset.symbol })
      existing.add('asset_symbol')
    }
    const appendSpecNumber = (key: string, label: string, digits = 2) => {
      if (existing.has(key)) return
      const value = asset.spec[key]
      if (value === undefined || value === null || value === '') return
      items.push({ key, label, value: formatMetric(value, digits) })
      existing.add(key)
    }
    const appendSpecText = (key: string, label: string) => {
      if (existing.has(key)) return
      const value = asset.spec[key]
      if (value === undefined || value === null || value === '') return
      items.push({ key, label, value: String(value) })
      existing.add(key)
    }
    appendSpecNumber('multiplier', '合约乘数', 2)
    appendSpecNumber('margin', '保证金', 4)
    appendSpecNumber('margin_rate', '保证金率', 4)
    appendSpecNumber('leverage', '杠杆', 2)
    appendSpecNumber('max_leverage', '最大杠杆', 2)
    appendSpecNumber('commission', '手续费', 6)
    appendSpecNumber('commission_rate', '手续费率', 6)
    if (!items.some(item => item.label === '资产来源')) appendSpecText('asset_spec_source', '资产来源')
    if (!items.some(item => item.label === '资产来源')) appendSpecText('source', '资产来源')
    if (!items.some(item => item.label === '费用来源')) appendSpecText('fee_source', '费用来源')
    return items.slice(0, 10)
  }

  function gatewayRuntimeItemsFromSnapshot(
    requestSnapshot?: Record<string, unknown> | null
  ): PaperEnvironmentItem[] {
    if (!isRecord(requestSnapshot) || !isRecord(requestSnapshot.gateway_config)) return []
    const gatewayConfig = requestSnapshot.gateway_config
    const params = isRecord(gatewayConfig.params) ? gatewayConfig.params : {}
    const gatewayParams = isRecord(params.gateway) ? params.gateway : {}
    const ctpParams = isRecord(params.ctp) ? params.ctp : {}
    const ibParams = isRecord(params.ib) ? params.ib : {}
    const mt5Params = isRecord(params.mt5) ? params.mt5 : {}
    const text = (...values: unknown[]) => {
      for (const value of values) {
        if (typeof value === 'number' && Number.isFinite(value)) return String(value)
        const parsed = stringFromUnknown(value)
        if (parsed) return parsed
      }
      return ''
    }
    const items: PaperEnvironmentItem[] = []
    const appendText = (key: string, label: string, value: string) => {
      if (!value) return
      items.push({ key, label, value })
    }
    appendText(
      'gateway_name',
      '网关',
      text(
        gatewayConfig.name,
        gatewayConfig.preset_id,
        params.name,
        params.preset_id,
        gatewayParams.provider
      )
    )
    appendText(
      'gateway_exchange',
      '交易所',
      text(
        gatewayConfig.exchange,
        gatewayConfig.exchange_id,
        gatewayConfig.exchange_type,
        params.exchange,
        params.exchange_id,
        params.exchange_type,
        gatewayParams.exchange,
        gatewayParams.exchange_id,
        gatewayParams.exchange_type
      )
    )
    appendText(
      'gateway_mode',
      '模式',
      text(
        gatewayConfig.mode,
        gatewayConfig.trading_mode,
        params.mode,
        params.trading_mode,
        gatewayParams.mode,
        gatewayParams.trading_mode
      )
    )
    appendText(
      'gateway_broker',
      '经纪商',
      text(
        gatewayConfig.broker_id,
        params.broker_id,
        ctpParams.broker_id,
        ibParams.broker_id,
        mt5Params.broker_id,
        gatewayParams.broker_id
      )
    )
    return items
  }

  function hasPaperEnvironment(handoff: Record<string, unknown> | null | undefined) {
    return paperEnvironmentItems(handoff).length > 0
  }

  function paperEnvironmentItems(
    handoff: Record<string, unknown> | null | undefined
  ): PaperEnvironmentItem[] {
    if (!isRecord(handoff) || !isRecord(handoff.backtest_environment)) return []
    return environmentItemsFromPayload(handoff.backtest_environment)
  }

  function environmentItemsFromPayload(environment: Record<string, unknown>): PaperEnvironmentItem[] {
    const items: PaperEnvironmentItem[] = []
    const appendNumber = (key: string, label: string, digits = 2) => {
      const value = environment[key]
      if (value === undefined || value === null || value === '') return
      items.push({ key, label, value: formatMetric(value, digits) })
    }
    const appendText = (key: string, label: string) => {
      const value = environment[key]
      if (value === undefined || value === null || value === '') return
      items.push({ key, label, value: String(value) })
    }
    const startDate = environment.start_date
    const endDate = environment.end_date
    if (startDate || endDate) {
      items.push({
        key: 'date_range',
        label: t('strategy.aiResearchPeriod'),
        value: `${startDate || '-'} 至 ${endDate || '-'}`,
      })
    }
    appendNumber('initial_cash', '初始资金', 2)
    appendNumber('commission', '手续费', 6)
    appendNumber('multiplier', '合约乘数', 2)
    appendNumber('margin', '保证金', 4)
    appendNumber('annual_days', '年化天数', 0)
    appendText('calc_method', '收益')
    appendText('weight_mode', '权重')
    appendText('asset_spec_source', '资产来源')
    return items
  }

  function runtimeEnvironmentPayload(
    record: AIStrategyResearchRunRecord | null | undefined,
    handoff?: Record<string, unknown> | null
  ): Record<string, unknown> {
    const environment: Record<string, unknown> = {}
    const merge = (source: unknown) => {
      if (isRecord(source)) Object.assign(environment, source)
    }
    merge(record?.backtest_environment)
    merge(handoff?.backtest_environment)
    if (handoff !== undefined && isRecord(record?.paper_handoff)) {
      merge(record.paper_handoff.backtest_environment)
    }
    return environment
  }

  function firstRuntimeAssetSpecFromPayload(
    specs: Record<string, unknown>
  ): { symbol: string; spec: Record<string, unknown> } | null {
    for (const [symbol, spec] of Object.entries(specs)) {
      if (!isRecord(spec)) continue
      return { symbol, spec }
    }
    return null
  }

  function iterationOutOfSampleValidation(
    item: AIStrategyResearchRunResponse['iterations'][number]
  ): AIStrategyOutOfSampleValidation | null {
    const hasWindow = Boolean(item.validation_window)
    const hasMetrics = Boolean(Object.keys(item.validation_metrics || {}).length)
    const hasGates = Boolean((item.validation_gate_evaluations || []).length)
    const hasFailures = Boolean((item.validation_failures || []).length)
    if (!item.validation_status && !hasWindow && !hasMetrics && !hasGates && !hasFailures) {
      return null
    }
    return {
      status: item.validation_status ?? null,
      window: item.validation_window ?? null,
      metrics: item.validation_metrics ?? {},
      gate_evaluations: item.validation_gate_evaluations ?? [],
      failures: item.validation_failures ?? [],
      failure_reason: item.validation_failure_reason ?? null,
    }
  }

  function formatBacktestPercent(value: unknown, { absolute = false } = {}) {
    const number = optionalNumber(value)
    if (number === null) return ''
    return `${formatMetric(absolute ? Math.abs(number) : number)}%`
  }

  function researchIterationBacktestSummary(
    item: AIStrategyResearchRunResponse['iterations'][number]
  ) {
    const metrics = isRecord(item.metrics) ? item.metrics : {}
    const rows: { key: string; label: string; value: string }[] = []
    const appendMetric = (
      key: string,
      label: string,
      keys: string[],
      formatter: (value: unknown) => string = value => formatMetric(value)
    ) => {
      const value = keys
        .map(metricKey => metrics[metricKey])
        .find(metricValue => optionalNumber(metricValue) !== null)
      if (value === undefined || value === null || value === '') return
      const formatted = formatter(value)
      if (!formatted || formatted === '-') return
      rows.push({ key, label, value: formatted })
    }
    const runStatus = stringFromUnknown(item.unit_status?.run_status, item.run_result.status)
    if (runStatus) rows.push({ key: 'run_status', label: t('common.status'), value: runStatus })
    if (item.run_result.task_id) {
      rows.push({ key: 'task_id', label: t('strategy.aiResearchTask'), value: item.run_result.task_id })
    }
    appendMetric('total_return', '总收益', ['total_return', 'return'], value =>
      formatBacktestPercent(value)
    )
    appendMetric('annual_return', '年化', ['annual_return', 'annualized_return'], value =>
      formatBacktestPercent(value)
    )
    appendMetric('max_drawdown', '最大回撤', ['max_drawdown', 'max_drawdown_rate'], value =>
      formatBacktestPercent(value, { absolute: true })
    )
    appendMetric('win_rate', '胜率', ['win_rate'], value => formatBacktestPercent(value))
    appendMetric('net_profit', '净利润', ['net_profit', 'total_pnl', 'pnl'])
    appendMetric('final_value', '最终权益', ['final_value', 'portfolio_value'])
    appendMetric('trading_cost', '交易成本', ['trading_cost', 'commission'])
    if (item.unit_status?.bar_count) {
      rows.push({ key: 'bar_count', label: t('strategy.aiResearchKline'), value: formatMetric(item.unit_status.bar_count, 0) })
    }
    return rows
  }

  function formatOutOfSampleWindow(window: Record<string, string> | null | undefined) {
    if (!window) return ''
    const trainStart = window.train_start
    const trainEnd = window.train_end
    const validationStart = window.validation_start
    const validationEnd = window.validation_end
    if (!trainStart || !trainEnd || !validationStart || !validationEnd) return ''
    return `训练 ${trainStart} - ${trainEnd}；样本外 ${validationStart} - ${validationEnd}`
  }

  function outOfSampleTagType(status: string | null | undefined) {
    if (status === 'passed') return 'success'
    if (status === 'failed') return 'danger'
    if (status === 'skipped') return 'info'
    return 'warning'
  }

  function outOfSampleStatusLabel(status: string | null | undefined) {
    const normalized = String(status || '').trim()
    const labels: Record<string, string> = {
      passed: '已通过',
      failed: '未通过',
      skipped: '已跳过',
      not_required: '无需验证',
      pending: '待验证',
      running: '验证中',
    }
    return labels[normalized] ?? aiResearchStageLabel(normalized || 'not_required')
  }

  function recordOutOfSampleSummary(record: AIStrategyResearchRunRecord) {
    const handoffValidation = outOfSampleValidationFromHandoff(record.paper_handoff)
    if (handoffValidation?.status) return `样本外 ${outOfSampleStatusLabel(handoffValidation.status)}`
    const gates = record.quality_gates || {}
    if (optionalBoolean(gates.out_of_sample_validation, false)) {
      return `样本外 ${formatMetric(outOfSampleRatioPct(gates.out_of_sample_ratio), 0)}%`
    }
    return ''
  }

  function strategyIdFromIterationPayload(payload: Record<string, unknown>) {
    const strategySnapshot = iterationStrategyPayload(payload)
    return stringFromUnknown(strategySnapshot.id ?? payload.strategy_id, '').trim()
  }

  function iterationPayloadHasStrategy(payload: Record<string, unknown>) {
    const strategySnapshot = iterationStrategyPayload(payload)
    return Boolean(
      strategyIdFromIterationPayload(payload)
      || stringFromUnknown(strategySnapshot.code, '')
      || stringFromUnknown(payload.strategy_code, '')
      || stringFromUnknown(payload.code, '')
    )
  }

  function iterationPayloadRank(payload: Record<string, unknown>) {
    const metrics = isRecord(payload.metrics) ? payload.metrics : {}
    return [
      optionalBoolean(payload.passed, false) ? 1 : 0,
      optionalNumber(payload.quality_score) ?? 0,
      optionalNumber(payload.sharpe_ratio)
        ?? optionalNumber(metrics.sharpe_ratio)
        ?? optionalNumber(metrics.sharpe)
        ?? optionalNumber(metrics.sharpeRatio)
        ?? 0,
      optionalNumber(payload.total_trades)
        ?? optionalNumber(metrics.total_trades)
        ?? optionalNumber(metrics.totalTrades)
        ?? optionalNumber(metrics.trades)
        ?? 0,
      -(optionalNumber(payload.iteration) ?? 0),
    ]
  }

  function compareIterationPayloads(
    candidate: Record<string, unknown>,
    current: Record<string, unknown>
  ) {
    const candidateRank = iterationPayloadRank(candidate)
    const currentRank = iterationPayloadRank(current)
    for (let index = 0; index < candidateRank.length; index += 1) {
      const delta = candidateRank[index] - currentRank[index]
      if (delta !== 0) return delta
    }
    return 0
  }

  function bestIterationPayloadForRecord(record: AIStrategyResearchRunRecord) {
    const iterations = (record.iterations || []).filter(isRecord)
    if (!iterations.length) return null
    const bestIteration = optionalNumber(record.best_iteration)
    if (bestIteration !== null) {
      const matched = iterations.find(
        payload => optionalNumber(payload.iteration) === bestIteration
      )
      if (matched) return matched
    }
    const candidates = iterations.filter(iterationPayloadHasStrategy)
    const pool = candidates.length ? candidates : iterations
    return pool.reduce(
      (best, payload) => (compareIterationPayloads(payload, best) > 0 ? payload : best),
      pool[0]
    )
  }

  function bestStrategyIdForRecord(record: AIStrategyResearchRunRecord) {
    const direct = stringFromUnknown(record.best_strategy_id, '').trim()
    if (direct) return direct
    const payload = bestIterationPayloadForRecord(record)
    if (!payload) return ''
    const payloadStrategyId = strategyIdFromIterationPayload(payload)
    if (payloadStrategyId) return payloadStrategyId
    return iterationPayloadHasStrategy(payload) ? fallbackSnapshotStrategyId(record) : ''
  }

  function fallbackSnapshotStrategyId(record: AIStrategyResearchRunRecord) {
    return `${record.run_id}-strategy`
  }

  function gatewayConfigJsonFromRunRecord(record: AIStrategyResearchRunRecord) {
    const payload = bestIterationPayloadForRecord(record)
    const snapshot = payload && isRecord(payload.unit_snapshot) ? payload.unit_snapshot : {}
    const handoff = isRecord(record.paper_handoff) ? record.paper_handoff : {}
    const candidates = [snapshot.gateway_config, handoff.gateway_config]
    const gatewayConfig = candidates.find(
      item => isRecord(item) && Object.keys(item).length > 0 && !containsRedactedSecret(item)
    )
    return isRecord(gatewayConfig) ? JSON.stringify(gatewayConfig) : ''
  }

  function gatewayConfigJsonFromTaskSnapshot(snapshot: Record<string, unknown>) {
    const gatewayConfig = snapshot.gateway_config
    if (!isRecord(gatewayConfig) || containsRedactedSecret(gatewayConfig)) return ''
    return JSON.stringify(gatewayConfig)
  }

  function liveGatewayConfigJsonFromRunRecord(record: AIStrategyResearchRunRecord) {
    const handoffPayload = record.live_handoff?.handoff
    const gatewayConfig = isRecord(handoffPayload?.gateway_config)
      ? handoffPayload.gateway_config
      : null
    if (!isRecord(gatewayConfig) || containsRedactedSecret(gatewayConfig)) return ''
    return JSON.stringify(gatewayConfig)
  }

  function runtimeAssetSpecsPayload(
    record: AIStrategyResearchRunRecord | null | undefined,
    handoff?: Record<string, unknown> | null
  ) {
    const specs: Record<string, unknown> = {}
    const merge = (source: unknown) => {
      if (!isRecord(source)) return
      for (const [symbol, spec] of Object.entries(source)) {
        if (isRecord(spec)) specs[symbol] = spec
      }
    }
    merge(record?.asset_specs)
    merge(handoff?.asset_specs)
    if (handoff !== undefined && isRecord(record?.paper_handoff)) {
      merge(record.paper_handoff.asset_specs)
    }
    return specs
  }

  function iterationStrategyPayload(payload: Record<string, unknown>) {
    if (isRecord(payload.strategy_snapshot) && Object.keys(payload.strategy_snapshot).length) {
      return payload.strategy_snapshot
    }
    return isRecord(payload.strategy) ? payload.strategy : {}
  }

  function iterationUnitPayload(payload: Record<string, unknown>) {
    if (isRecord(payload.unit_snapshot) && Object.keys(payload.unit_snapshot).length) {
      return payload.unit_snapshot
    }
    return isRecord(payload.unit) ? payload.unit : {}
  }

  function iterationRunResultPayload(payload: Record<string, unknown>) {
    return isRecord(payload.run_result) ? payload.run_result : {}
  }

  function iterationUnitStatusPayload(payload: Record<string, unknown>) {
    return isRecord(payload.unit_status) ? payload.unit_status : {}
  }

  return {
    validationWindowFromUnknown,
    outOfSampleValidationFromHandoff,
    hasResearchRuntimeEnvironment,
    researchRuntimeItems,
    runtimeItemsFromPayloads,
    gatewayRuntimeItemsFromSnapshot,
    hasPaperEnvironment,
    paperEnvironmentItems,
    environmentItemsFromPayload,
    runtimeEnvironmentPayload,
    firstRuntimeAssetSpecFromPayload,
    iterationOutOfSampleValidation,
    formatBacktestPercent,
    researchIterationBacktestSummary,
    formatOutOfSampleWindow,
    outOfSampleTagType,
    outOfSampleStatusLabel,
    recordOutOfSampleSummary,
    strategyIdFromIterationPayload,
    iterationPayloadHasStrategy,
    iterationPayloadRank,
    compareIterationPayloads,
    bestIterationPayloadForRecord,
    bestStrategyIdForRecord,
    fallbackSnapshotStrategyId,
    gatewayConfigJsonFromRunRecord,
    gatewayConfigJsonFromTaskSnapshot,
    liveGatewayConfigJsonFromRunRecord,
    runtimeAssetSpecsPayload,
    iterationStrategyPayload,
    iterationUnitPayload,
    iterationRunResultPayload,
    iterationUnitStatusPayload,
  }
}
