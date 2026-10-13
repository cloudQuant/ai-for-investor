import { describe, expect, it } from 'vitest'
import type {
  AIStrategyResearchRunRecord,
  AIStrategyResearchRunResponse,
} from '@/api/strategy'
import { useAIResearchRuntimeProjections } from '@/views/strategy/useAIResearchRuntimeProjections'

function createProjections() {
  return useAIResearchRuntimeProjections({
    t: key => key,
    formatMetric: (value, digits = 2) => {
      const numeric = Number(value)
      return Number.isFinite(numeric) ? numeric.toFixed(digits) : '-'
    },
    aiResearchStageLabel: stage => `stage:${stage}`,
    outOfSampleRatioPct: value => Number(value) * 100,
  })
}

function asRunRecord(value: unknown) {
  return value as AIStrategyResearchRunRecord
}

function asIteration(value: unknown) {
  return value as AIStrategyResearchRunResponse['iterations'][number]
}

describe('useAIResearchRuntimeProjections', () => {
  it('normalizes valid validation payloads and ignores malformed values', () => {
    const projections = createProjections()

    expect(projections.validationWindowFromUnknown(null)).toBeNull()
    expect(projections.validationWindowFromUnknown({ start: '2024-01-01', count: 2 })).toEqual({
      start: '2024-01-01',
    })
    expect(projections.outOfSampleValidationFromHandoff(null)).toBeNull()
    expect(projections.outOfSampleValidationFromHandoff({ out_of_sample_validation: [] })).toBeNull()
    expect(projections.outOfSampleValidationFromHandoff({
      out_of_sample_validation: {
        status: 7,
        window: { train_start: '2024-01-01', samples: 12 },
        metrics: null,
        gate_evaluations: {},
        failures: ['coverage gap', 2, null],
        failure_reason: false,
      },
    })).toEqual({
      status: null,
      window: { train_start: '2024-01-01' },
      metrics: {},
      gate_evaluations: [],
      failures: ['coverage gap'],
      failure_reason: null,
    })
  })

  it('merges runtime environment and asset specs while preserving gateway fallbacks', () => {
    const projections = createProjections()
    const record = asRunRecord({
      run_id: 'runtime-run',
      backtest_environment: { start_date: '2024-01-01', initial_cash: 1000 },
      asset_specs: { IF2406: { multiplier: 10, source: 'record-source' } },
      paper_handoff: {
        backtest_environment: { end_date: '2024-12-31', initial_cash: 3000 },
        asset_specs: { IF2406: { multiplier: 20, source: 'nested-source' } },
      },
    })
    const handoff = {
      backtest_environment: { initial_cash: 2000, commission: 0.0001 },
      asset_specs: { IF2406: { margin: 5000 } },
    }

    expect(projections.runtimeEnvironmentPayload(record, handoff)).toEqual({
      start_date: '2024-01-01',
      initial_cash: 3000,
      commission: 0.0001,
      end_date: '2024-12-31',
    })
    expect(projections.runtimeAssetSpecsPayload(record, handoff)).toEqual({
      IF2406: { multiplier: 20, source: 'nested-source' },
    })
    expect(projections.firstRuntimeAssetSpecFromPayload({ invalid: 3, IF2406: { multiplier: 20 } }))
      .toEqual({ symbol: 'IF2406', spec: { multiplier: 20 } })
    expect(projections.firstRuntimeAssetSpecFromPayload({ invalid: null })).toBeNull()

    expect(projections.gatewayRuntimeItemsFromSnapshot(null)).toEqual([])
    expect(projections.gatewayRuntimeItemsFromSnapshot({
      gateway_config: {
        preset_id: 'ctp-paper',
        exchange_type: 'futures',
        trading_mode: 'paper',
        params: { ctp: { broker_id: 'broker-7' } },
      },
    })).toEqual([
      { key: 'gateway_name', label: '网关', value: 'ctp-paper' },
      { key: 'gateway_exchange', label: '交易所', value: 'futures' },
      { key: 'gateway_mode', label: '模式', value: 'paper' },
      { key: 'gateway_broker', label: '经纪商', value: 'broker-7' },
    ])

    const specItems = projections.runtimeItemsFromPayloads({}, {
      IF2406: {
        multiplier: 10,
        margin: 5000,
        margin_rate: 0.12,
        leverage: 8,
        max_leverage: 10,
        commission: 2,
        commission_rate: 0.0002,
        source: 'local-catalog',
        fee_source: 'exchange-fees',
      },
    })
    expect(specItems).toEqual([
      { key: 'asset_symbol', label: 'strategy.aiResearchAsset', value: 'IF2406' },
      { key: 'multiplier', label: '合约乘数', value: '10.00' },
      { key: 'margin', label: '保证金', value: '5000.0000' },
      { key: 'margin_rate', label: '保证金率', value: '0.1200' },
      { key: 'leverage', label: '杠杆', value: '8.00' },
      { key: 'max_leverage', label: '最大杠杆', value: '10.00' },
      { key: 'commission', label: '手续费', value: '2.000000' },
      { key: 'commission_rate', label: '手续费率', value: '0.000200' },
      { key: 'source', label: '资产来源', value: 'local-catalog' },
      { key: 'fee_source', label: '费用来源', value: 'exchange-fees' },
    ])
    expect(projections.runtimeItemsFromPayloads({ asset_spec_source: 'record-source' }, {
      IF2406: { source: 'duplicate-source' },
    }).filter(item => item.label === '资产来源')).toHaveLength(1)
    expect(projections.hasResearchRuntimeEnvironment(record)).toBe(true)
    expect(projections.hasResearchRuntimeEnvironment(asRunRecord({ run_id: 'empty' }))).toBe(false)
  })

  it('projects paper environments, iteration metrics, and validation status branches', () => {
    const projections = createProjections()

    expect(projections.hasPaperEnvironment(null)).toBe(false)
    expect(projections.paperEnvironmentItems({ backtest_environment: {
      start_date: '2024-01-01', initial_cash: 0, calc_method: 'fifo',
    } })).toEqual([
      { key: 'date_range', label: 'strategy.aiResearchPeriod', value: '2024-01-01 至 -' },
      { key: 'initial_cash', label: '初始资金', value: '0.00' },
      { key: 'calc_method', label: '收益', value: 'fifo' },
    ])
    expect(projections.hasPaperEnvironment({ backtest_environment: { calc_method: 'fifo' } })).toBe(true)
    expect(projections.iterationOutOfSampleValidation(asIteration({
      validation_status: null,
      validation_window: null,
      validation_metrics: {},
      validation_gate_evaluations: [],
      validation_failures: [],
    }))).toBeNull()
    expect(projections.iterationOutOfSampleValidation(asIteration({
      validation_status: 'failed',
      validation_window: { train_start: '2024-01-01' },
      validation_metrics: { sharpe: 0.8 },
      validation_gate_evaluations: [{ key: 'coverage' }],
      validation_failures: ['gap'],
      validation_failure_reason: 'missing bars',
    }))).toEqual({
      status: 'failed',
      window: { train_start: '2024-01-01' },
      metrics: { sharpe: 0.8 },
      gate_evaluations: [{ key: 'coverage' }],
      failures: ['gap'],
      failure_reason: 'missing bars',
    })

    expect(projections.formatBacktestPercent('not-a-number')).toBe('')
    expect(projections.formatBacktestPercent(-0.25, { absolute: true })).toBe('0.25%')
    expect(projections.formatOutOfSampleWindow({ train_start: '2024-01-01' })).toBe('')
    expect(projections.formatOutOfSampleWindow({
      train_start: '2024-01-01',
      train_end: '2024-03-31',
      validation_start: '2024-04-01',
      validation_end: '2024-06-30',
    })).toBe('训练 2024-01-01 - 2024-03-31；样本外 2024-04-01 - 2024-06-30')
    expect(projections.outOfSampleTagType('passed')).toBe('success')
    expect(projections.outOfSampleTagType('failed')).toBe('danger')
    expect(projections.outOfSampleTagType('skipped')).toBe('info')
    expect(projections.outOfSampleTagType('pending')).toBe('warning')
    expect(projections.outOfSampleStatusLabel('pending')).toBe('待验证')
    expect(projections.outOfSampleStatusLabel('custom-stage')).toBe('stage:custom-stage')

    const summary = projections.researchIterationBacktestSummary(asIteration({
      metrics: {
        total_return: 12,
        annualized_return: 8,
        max_drawdown_rate: -20,
        win_rate: 50,
        total_pnl: 12,
        portfolio_value: 1000,
        commission: 3,
      },
      run_result: { status: 'completed', task_id: 'task-7' },
      unit_status: { run_status: 'finished', bar_count: 20 },
    }))
    expect(summary.map(item => [item.key, item.value])).toEqual([
      ['run_status', 'finished'],
      ['task_id', 'task-7'],
      ['total_return', '12.00%'],
      ['annual_return', '8.00%'],
      ['max_drawdown', '20.00%'],
      ['win_rate', '50.00%'],
      ['net_profit', '12.00'],
      ['final_value', '1000.00'],
      ['trading_cost', '3.00'],
      ['bar_count', '20'],
    ])
    expect(projections.researchIterationBacktestSummary(asIteration({
      metrics: { total_return: 'invalid' },
      run_result: { status: '' },
      unit_status: { bar_count: 0 },
    }))).toEqual([])

    expect(projections.recordOutOfSampleSummary(asRunRecord({
      run_id: 'ratio-run',
      quality_gates: { out_of_sample_validation: true, out_of_sample_ratio: 0.25 },
    }))).toBe('样本外 25%')
    expect(projections.recordOutOfSampleSummary(asRunRecord({
      run_id: 'empty-run',
      quality_gates: { out_of_sample_validation: false },
    }))).toBe('')
    expect(projections.recordOutOfSampleSummary(asRunRecord({
      run_id: 'handoff-run',
      paper_handoff: { out_of_sample_validation: { status: 'failed' } },
      quality_gates: { out_of_sample_validation: true, out_of_sample_ratio: 0.9 },
    }))).toBe('样本外 未通过')
  })

  it('selects best strategy snapshots and keeps redacted gateway settings out of the view', () => {
    const projections = createProjections()
    const rankingRecord = asRunRecord({
      run_id: 'ranking-run',
      iterations: [
        { iteration: 1, passed: true, quality_score: 10, strategy_snapshot: { id: 'passed' } },
        { iteration: 2, passed: false, quality_score: 100, strategy: { id: 'higher-score' } },
      ],
    })

    expect(projections.bestIterationPayloadForRecord(asRunRecord({ run_id: 'empty', iterations: [] }))).toBeNull()
    expect(projections.bestIterationPayloadForRecord(rankingRecord)).toMatchObject({ iteration: 1 })
    expect(projections.bestIterationPayloadForRecord(asRunRecord({
      ...rankingRecord,
      best_iteration: 2,
    }))).toMatchObject({ iteration: 2 })
    expect(projections.bestStrategyIdForRecord(rankingRecord)).toBe('passed')
    expect(projections.bestStrategyIdForRecord(asRunRecord({
      run_id: 'fallback-run',
      iterations: [{ iteration: 1, strategy_snapshot: { code: 'class Candidate: pass' } }],
    }))).toBe('fallback-run-strategy')
    expect(projections.bestStrategyIdForRecord(asRunRecord({
      run_id: 'direct-run',
      best_strategy_id: 'direct-id',
      iterations: [],
    }))).toBe('direct-id')
    expect(projections.iterationPayloadHasStrategy({ strategy_code: 'class A: pass' })).toBe(true)
    expect(projections.iterationPayloadHasStrategy({ strategy_snapshot: {}, strategy: { id: 'nested' } })).toBe(true)
    expect(projections.iterationPayloadHasStrategy({})).toBe(false)
    expect(projections.fallbackSnapshotStrategyId(asRunRecord({ run_id: 'snapshot-run' }))).toBe('snapshot-run-strategy')
    expect(projections.iterationStrategyPayload({ strategy_snapshot: {}, strategy: { id: 'fallback' } })).toEqual({ id: 'fallback' })
    expect(projections.iterationUnitPayload({ unit_snapshot: {}, unit: { id: 'unit-1' } })).toEqual({ id: 'unit-1' })
    expect(projections.iterationRunResultPayload({ run_result: 'invalid' })).toEqual({})
    expect(projections.iterationUnitStatusPayload({ unit_status: { run_status: 'done' } })).toEqual({ run_status: 'done' })

    const gatewayRecord = asRunRecord({
      run_id: 'gateway-run',
      best_iteration: 1,
      iterations: [{ iteration: 1, unit_snapshot: { gateway_config: { provider: 'ctp' } } }],
      paper_handoff: { gateway_config: { provider: 'fallback' } },
      live_handoff: { handoff: { gateway_config: { provider: 'live' } } },
    })
    expect(projections.gatewayConfigJsonFromRunRecord(gatewayRecord)).toBe('{"provider":"ctp"}')
    expect(projections.liveGatewayConfigJsonFromRunRecord(gatewayRecord)).toBe('{"provider":"live"}')
    expect(projections.gatewayConfigJsonFromTaskSnapshot({ gateway_config: { provider: 'ctp' } }))
      .toBe('{"provider":"ctp"}')
    expect(projections.gatewayConfigJsonFromTaskSnapshot({ gateway_config: { password: '***' } })).toBe('')
    expect(projections.gatewayConfigJsonFromRunRecord(asRunRecord({
      run_id: 'redacted-run',
      iterations: [{ iteration: 1, unit_snapshot: { gateway_config: { password: '***' } } }],
      paper_handoff: { gateway_config: { password: '***' } },
    }))).toBe('')
  })
})
