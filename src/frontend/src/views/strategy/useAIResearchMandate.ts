import { computed, ref, type Ref } from 'vue'
import { ElMessage } from 'element-plus'
import type { MarketAssetType } from '@/api/marketData'
import { strategyApi, type InvestmentMandateResponse } from '@/api/strategy'
import type { AIResearchFormState, AIResearchPromptGenerationMode } from './aiResearchConstants'
import {
  formatMetric,
  mandateQualityGateSummary,
  outOfSampleRatioPct,
} from './aiResearchFormatters'
import type {
  AIResearchAutoContinuationSource,
  AIResearchMandateInput,
  AIResearchMandateSnapshot,
  AIResearchRunnableInput,
} from './aiResearchTaskTypes'
import {
  isRecord,
  optionalNumber,
  stringArrayFromUnknown,
  stringFromUnknown,
} from './aiResearchValueAdapters'

export interface AIResearchMandateDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  aiResearchForm: AIResearchFormState
  aiResearchRunning: Ref<boolean>
  aiResearchResolvedMarketDataAssetType: (symbol: string) => MarketAssetType | undefined
  aiResearchAssetConstraintLine: () => string
  outOfSampleRatioValue: () => number
  requiredOutOfSampleValidationError: () => string
  aiResearchRunnableInput: () => AIResearchRunnableInput | null
}

export function useAIResearchMandate(deps: AIResearchMandateDeps) {
  const { t, aiResearchForm } = deps

  const aiResearchMandate = ref<InvestmentMandateResponse | null>(null)
  const aiResearchMandateConfirmed = ref(false)
  const aiResearchMandateLoading = ref(false)
  const aiResearchPromptGenerationDialogVisible = ref(false)
  const aiResearchPromptGenerationMode = ref<AIResearchPromptGenerationMode>('default')
  const aiResearchPromptGenerationLoading = ref(false)

  const aiResearchMandateDetails = computed(() => {
    const mandate = aiResearchMandate.value
    if (!mandate) return []
    const goal = mandate.structured_goal || {}
    const asset = mandate.asset_scope || {}
    return [
      { key: 'asset', label: t('strategy.aiResearchAsset'), value: stringFromUnknown(asset.asset_class, '-') },
      { key: 'symbol', label: t('strategy.aiResearchSymbol'), value: stringFromUnknown(asset.symbol, '-') },
      { key: 'timeframe', label: t('strategy.aiResearchTimeframe'), value: mandate.timeframe || stringFromUnknown(goal.timeframe, '-') },
      { key: 'objective', label: t('strategy.aiResearchObjective'), value: mandate.objective || stringFromUnknown(goal.objective, '-') },
      {
        key: 'risk',
        label: t('strategy.aiResearchRiskConstraints'),
        value: Object.keys(mandate.risk_constraints || {}).length
          ? Object.keys(mandate.risk_constraints).join('、')
          : '未显式约束',
      },
      {
        key: 'gates',
        label: t('strategy.aiResearchQualityGates'),
        value: mandateQualityGateSummary(mandate.quality_gates),
      },
    ]
  })

  function aiResearchSymbolLabel() {
    const symbol = aiResearchForm.symbol.trim() || '待研究标的'
    const symbolName = aiResearchForm.symbol_name.trim()
    return symbolName ? `${symbolName}（${symbol}）` : symbol
  }

  function aiResearchQualityGateLines() {
    const lines = [
      `目标 Sharpe 不低于 ${formatMetric(aiResearchForm.target_sharpe)}。`,
      `至少产生 ${formatMetric(aiResearchForm.min_total_trades, 0)} 笔有效交易，避免只靠少数交易达标。`,
    ]
    if (aiResearchForm.use_max_drawdown_limit) {
      lines.push(`最大回撤控制在 ${formatMetric(aiResearchForm.max_drawdown_limit, 0)}% 以内。`)
    }
    if (aiResearchForm.use_min_total_return) {
      lines.push(`总收益率不低于 ${formatMetric(aiResearchForm.min_total_return, 0)}%。`)
    }
    if (aiResearchForm.use_min_annual_return) {
      lines.push(`年化收益率不低于 ${formatMetric(aiResearchForm.min_annual_return, 0)}%。`)
    }
    if (aiResearchForm.use_min_win_rate) {
      lines.push(`胜率不低于 ${formatMetric(aiResearchForm.min_win_rate, 0)}%。`)
    }
    return lines
  }

  function aiResearchValidationLines() {
    const lines = [
      `回测区间：${aiResearchForm.start_date || '可用历史数据起点'} 至 ${aiResearchForm.end_date || '最新可得数据'}。`,
      `运行口径：年化天数 ${formatMetric(aiResearchForm.annual_days, 0)}，收益计算 ${aiResearchForm.calc_method}，组合权重 ${aiResearchForm.weight_mode}。`,
    ]
    if (aiResearchForm.out_of_sample_validation) {
      const requirements = [
        `保留 ${formatMetric(aiResearchForm.out_of_sample_ratio_pct, 0)}% 数据做样本外验证`,
      ]
      if (aiResearchForm.require_out_of_sample_validation) {
        requirements.push('达标后必须通过样本外验证才能进入模拟交易')
      }
      if (aiResearchForm.use_min_out_of_sample_sharpe) {
        requirements.push(`样本外 Sharpe 不低于 ${formatMetric(aiResearchForm.min_out_of_sample_sharpe)}`)
      }
      if (aiResearchForm.use_min_out_of_sample_trades) {
        requirements.push(`样本外交易数不少于 ${formatMetric(aiResearchForm.min_out_of_sample_trades, 0)}`)
      }
      lines.push(`${requirements.join('，')}。`)
    } else {
      lines.push('暂不启用样本外验证，但策略说明中必须提示过拟合风险。')
    }
    if (aiResearchForm.robustness_validation) {
      const methods = aiResearchForm.robustness_methods.length
        ? aiResearchForm.robustness_methods.join('、')
        : 'monte_carlo'
      const requirements = [
        `方法 ${methods}`,
        `稳健性得分不低于 ${formatMetric(aiResearchForm.min_robustness_score)}`,
      ]
      if (aiResearchForm.require_robustness_validation) {
        requirements.push('达标后必须通过稳健性验证才能进入模拟交易')
      }
      lines.push(`晋级前完成稳健性验证，${requirements.join('，')}。`)
    } else {
      lines.push('暂不启用稳健性验证，策略说明中必须显式提示参数敏感性和过拟合风险。')
    }
    if (aiResearchForm.start_paper_trading) {
      lines.push(
        `质量门槛达成后进入模拟交易，至少观察 ${formatMetric(aiResearchForm.min_paper_trading_days, 0)} 天，重点复核真实手续费、滑点、估值置信度、回撤和滚动 Sharpe。`,
      )
    } else {
      lines.push('本轮只完成研究和回测，不自动启动模拟交易。')
    }
    return lines
  }

  function buildGeneratedAIResearchPrompt() {
    const signalFamilies = '趋势跟随、均值回归、波动率过滤、突破确认和风险预算'
    const workflowModeLine = aiResearchForm.workflow_mode === 'prompt'
      ? '研究目标生成：使用用户提供的提示。'
      : '研究目标生成：根据当前控制项自动生成。'
    return [
      `请为 ${aiResearchSymbolLabel()} 生成一套 ${aiResearchForm.timeframe} 级别的可执行 Backtrader 策略，并自动迭代回测直到达到质量门槛。`,
      '',
      '专业流水线：',
      workflowModeLine,
      '说明：以下步骤仅用于组织研究提示与展示；实际服务端执行阶段和状态以运行记录为准。',
      '1. 策略构思：比较候选信号家族，明确入场、出场、仓位和风控假设。',
      '2. 策略生成：生成完整可运行的 Backtrader Strategy 脚本，next 方法必须包含真实 self.buy/self.sell/self.close 或 order_target_* 调用，不能留 pass、TODO 或伪代码。',
      '3. 策略回测：自动提交回测并记录 Sharpe、收益、回撤、交易次数和质量门槛差距。',
      '4. 策略审查：审查回测结果、失败原因、过拟合风险和实盘可执行性。',
      '5. 策略优化：根据审查意见继续优化代码、参数和风控，必要时进入下一轮回测。',
      '',
      '研究方向：',
      `1. 先比较 ${signalFamilies} 等候选逻辑，再选择最适合该标的的可执行方案。`,
      '2. 策略必须包含明确的入场、出场、止损/止盈、仓位 sizing 和异常行情保护。',
      `3. ${deps.aiResearchAssetConstraintLine()}`,
      '',
      '质量门槛：',
      ...aiResearchQualityGateLines().map((line, index) => `${index + 1}. ${line}`),
      '',
      '验证与晋级：',
      ...aiResearchValidationLines().map((line, index) => `${index + 1}. ${line}`),
      '',
      '输出要求：生成完整可运行的 Backtrader Strategy 脚本，参数默认值要便于自动改稿；每轮改进都应解释为什么可能改善 Sharpe、回撤、交易次数或实盘可执行性。',
    ].join('\n')
  }

  function generateAIResearchPrompt() {
    aiResearchForm.prompt = buildGeneratedAIResearchPrompt()
    clearAIResearchMandate()
    ElMessage.success(t('strategy.aiResearchPromptGenerated'))
  }

  function openAIResearchPromptGenerationDialog() {
    if (deps.aiResearchRunning.value) {
      ElMessage.warning(t('strategy.aiResearchPromptGenerationBusy'))
      return
    }
    aiResearchPromptGenerationMode.value = 'default'
    aiResearchPromptGenerationDialogVisible.value = true
  }

  function closeAIResearchPromptGenerationDialog() {
    if (!aiResearchPromptGenerationLoading.value) {
      aiResearchPromptGenerationDialogVisible.value = false
    }
  }

  function aiResearchObjectiveOptimizationConfig(): Record<string, unknown> {
    return {
      workflow_mode: aiResearchForm.workflow_mode,
      symbol: aiResearchForm.symbol.trim(),
      symbol_name: aiResearchForm.symbol_name.trim(),
      market_data_asset_type:
        deps.aiResearchResolvedMarketDataAssetType(aiResearchForm.symbol) ?? null,
      timeframe: aiResearchForm.timeframe,
      timeframe_n: aiResearchForm.timeframe_n,
      start_date: aiResearchForm.start_date || null,
      end_date: aiResearchForm.end_date || null,
      target_sharpe: aiResearchForm.target_sharpe,
      min_total_trades: aiResearchForm.min_total_trades,
      max_drawdown_limit: aiResearchForm.use_max_drawdown_limit
        ? aiResearchForm.max_drawdown_limit
        : null,
      min_total_return: aiResearchForm.use_min_total_return ? aiResearchForm.min_total_return : null,
      min_annual_return: aiResearchForm.use_min_annual_return
        ? aiResearchForm.min_annual_return
        : null,
      min_win_rate: aiResearchForm.use_min_win_rate ? aiResearchForm.min_win_rate : null,
      max_iterations: aiResearchForm.max_iterations,
      out_of_sample_validation: aiResearchForm.out_of_sample_validation,
      require_out_of_sample_validation: aiResearchForm.require_out_of_sample_validation,
      out_of_sample_ratio: deps.outOfSampleRatioValue(),
      min_out_of_sample_sharpe: aiResearchForm.use_min_out_of_sample_sharpe
        ? aiResearchForm.min_out_of_sample_sharpe
        : null,
      min_out_of_sample_trades: aiResearchForm.use_min_out_of_sample_trades
        ? aiResearchForm.min_out_of_sample_trades
        : null,
      robustness_validation: aiResearchForm.robustness_validation,
      require_robustness_validation: aiResearchForm.require_robustness_validation,
      robustness_methods: [...aiResearchForm.robustness_methods],
      min_robustness_score: aiResearchForm.min_robustness_score,
      robustness_monte_carlo_iterations: aiResearchForm.robustness_monte_carlo_iterations,
      initial_cash: aiResearchForm.initial_cash,
      commission: aiResearchForm.use_manual_commission ? aiResearchForm.commission : null,
      annual_days: aiResearchForm.annual_days,
      calc_method: aiResearchForm.calc_method,
      weight_mode: aiResearchForm.weight_mode,
      start_paper_trading: aiResearchForm.start_paper_trading,
      min_paper_trading_days: aiResearchForm.min_paper_trading_days,
    }
  }

  async function confirmAIResearchPromptGeneration() {
    const defaultPrompt = buildGeneratedAIResearchPrompt()
    if (aiResearchPromptGenerationMode.value === 'default') {
      generateAIResearchPrompt()
      aiResearchPromptGenerationDialogVisible.value = false
      return
    }

    aiResearchPromptGenerationLoading.value = true
    try {
      const optimized = await strategyApi.optimizeAIResearchObjective({
        prompt: defaultPrompt,
        research_config: aiResearchObjectiveOptimizationConfig(),
      })
      const optimizedPrompt = optimized.prompt.trim()
      if (!optimizedPrompt) throw new Error('empty optimized prompt')
      aiResearchForm.prompt = optimizedPrompt
      clearAIResearchMandate()
      ElMessage.success(t('strategy.aiResearchPromptOptimized', { model: optimized.model }))
    } catch {
      aiResearchForm.prompt = defaultPrompt
      clearAIResearchMandate()
      ElMessage.warning(t('strategy.aiResearchPromptOptimizationFailed'))
    } finally {
      aiResearchPromptGenerationLoading.value = false
      aiResearchPromptGenerationDialogVisible.value = false
    }
  }

  function aiResearchMandateQualityGatesFromForm(): Record<string, unknown> {
    return {
      target_sharpe: aiResearchForm.target_sharpe,
      min_total_trades: aiResearchForm.min_total_trades,
      max_drawdown_limit: aiResearchForm.use_max_drawdown_limit
        ? aiResearchForm.max_drawdown_limit
        : null,
      min_total_return: aiResearchForm.use_min_total_return
        ? aiResearchForm.min_total_return
        : null,
      min_annual_return: aiResearchForm.use_min_annual_return
        ? aiResearchForm.min_annual_return
        : null,
      min_win_rate: aiResearchForm.use_min_win_rate ? aiResearchForm.min_win_rate : null,
      out_of_sample_validation: aiResearchForm.out_of_sample_validation,
      require_out_of_sample_validation: aiResearchForm.require_out_of_sample_validation,
      out_of_sample_ratio: deps.outOfSampleRatioValue(),
      min_out_of_sample_sharpe:
        aiResearchForm.out_of_sample_validation && aiResearchForm.use_min_out_of_sample_sharpe
          ? aiResearchForm.min_out_of_sample_sharpe
          : null,
      min_out_of_sample_trades:
        aiResearchForm.out_of_sample_validation && aiResearchForm.use_min_out_of_sample_trades
          ? aiResearchForm.min_out_of_sample_trades
          : null,
      robustness_validation: aiResearchForm.robustness_validation,
      require_robustness_validation: aiResearchForm.require_robustness_validation,
      robustness_methods: aiResearchForm.robustness_methods,
      min_robustness_score: aiResearchForm.min_robustness_score,
      robustness_monte_carlo_iterations: aiResearchForm.robustness_monte_carlo_iterations,
      robustness_random_seed: aiResearchForm.robustness_random_seed,
    }
  }

  function aiResearchMandateInputPrompt(input?: AIResearchMandateInput | null) {
    return input?.prompt || aiResearchForm.prompt.trim() || buildGeneratedAIResearchPrompt()
  }

  function aiResearchContinuationRunnableInput(
    source: AIResearchAutoContinuationSource | null,
  ): AIResearchRunnableInput | null {
    const displayedPrompt = aiResearchForm.prompt.trim()
    if (
      source
      && aiResearchForm.workflow_mode === 'auto'
      && displayedPrompt === source.prompt
    ) {
      const symbol = aiResearchForm.symbol.trim()
      if (!symbol) {
        ElMessage.warning(t('strategy.aiResearchSymbolRequired'))
        return null
      }
      const outOfSampleError = deps.requiredOutOfSampleValidationError()
      if (outOfSampleError) {
        ElMessage.warning(outOfSampleError)
        return null
      }
      return { prompt: '', symbol, shouldUseServerGeneratedPrompt: true }
    }
    return deps.aiResearchRunnableInput()
  }

  function aiResearchMandateSnapshot(
    input?: AIResearchMandateInput | null,
  ): AIResearchMandateSnapshot {
    const prompt = aiResearchMandateInputPrompt(input)
    const symbol = input?.symbol || aiResearchForm.symbol.trim() || null
    return {
      rawPrompt: prompt,
      promptOrigin: input?.shouldUseServerGeneratedPrompt ? 'auto_generated' : 'explicit',
      symbol,
      symbolName: aiResearchForm.symbol_name.trim() || null,
      marketDataAssetType: deps.aiResearchResolvedMarketDataAssetType(symbol || ''),
      timeframe: aiResearchForm.timeframe || null,
      riskConstraints: {
        max_drawdown_limit: aiResearchForm.use_max_drawdown_limit
          ? aiResearchForm.max_drawdown_limit
          : null,
        min_win_rate: aiResearchForm.use_min_win_rate ? aiResearchForm.min_win_rate : null,
        out_of_sample_validation: aiResearchForm.out_of_sample_validation,
      },
      tradingConstraints: {
        initial_cash: aiResearchForm.initial_cash,
        annual_days: aiResearchForm.annual_days,
        calc_method: aiResearchForm.calc_method,
        weight_mode: aiResearchForm.weight_mode,
        start_paper_trading: aiResearchForm.start_paper_trading,
      },
      qualityGates: aiResearchMandateQualityGatesFromForm(),
    }
  }

  function aiResearchMandatePayloadFromSnapshot(snapshot: AIResearchMandateSnapshot) {
    return {
      raw_prompt: snapshot.rawPrompt,
      prompt_origin: snapshot.promptOrigin,
      symbol: snapshot.symbol,
      symbol_name: snapshot.symbolName,
      market_data_asset_type: snapshot.marketDataAssetType ?? null,
      timeframe: snapshot.timeframe,
      risk_constraints: snapshot.riskConstraints,
      trading_constraints: snapshot.tradingConstraints,
      quality_gates: snapshot.qualityGates,
    }
  }

  function aiResearchMandatePayload(input?: AIResearchMandateInput | null) {
    return aiResearchMandatePayloadFromSnapshot(aiResearchMandateSnapshot(input))
  }

  function applyAIResearchMandateSnapshotToForm(snapshot: AIResearchMandateSnapshot) {
    aiResearchForm.prompt = snapshot.rawPrompt
    if (snapshot.symbol) aiResearchForm.symbol = snapshot.symbol
    aiResearchForm.symbol_name = snapshot.symbolName || ''
    aiResearchForm.market_data_asset_type = snapshot.marketDataAssetType ?? ''
    if (snapshot.timeframe) aiResearchForm.timeframe = snapshot.timeframe

    const risk = snapshot.riskConstraints
    aiResearchForm.use_max_drawdown_limit = typeof risk.max_drawdown_limit === 'number'
    aiResearchForm.max_drawdown_limit = Number(risk.max_drawdown_limit ?? 20)
    aiResearchForm.use_min_win_rate = typeof risk.min_win_rate === 'number'
    aiResearchForm.min_win_rate = Number(risk.min_win_rate ?? 50)
    if (typeof risk.out_of_sample_validation === 'boolean') {
      aiResearchForm.out_of_sample_validation = risk.out_of_sample_validation
    }

    const trading = snapshot.tradingConstraints
    if (typeof trading.initial_cash === 'number') {
      aiResearchForm.initial_cash = trading.initial_cash
    }
    if (typeof trading.annual_days === 'number') {
      aiResearchForm.annual_days = trading.annual_days
    }
    if (typeof trading.calc_method === 'string') {
      aiResearchForm.calc_method = trading.calc_method
    }
    if (typeof trading.weight_mode === 'string') {
      aiResearchForm.weight_mode = trading.weight_mode
    }

    const gates = snapshot.qualityGates
    if (typeof gates.target_sharpe === 'number') {
      aiResearchForm.target_sharpe = gates.target_sharpe
    }
    if (typeof gates.min_total_trades === 'number') {
      aiResearchForm.min_total_trades = gates.min_total_trades
    }
    aiResearchForm.use_max_drawdown_limit = typeof gates.max_drawdown_limit === 'number'
    aiResearchForm.max_drawdown_limit = Number(gates.max_drawdown_limit ?? 20)
    aiResearchForm.use_min_total_return = typeof gates.min_total_return === 'number'
    aiResearchForm.min_total_return = Number(gates.min_total_return ?? 0)
    aiResearchForm.use_min_annual_return = typeof gates.min_annual_return === 'number'
    aiResearchForm.min_annual_return = Number(gates.min_annual_return ?? 0)
    aiResearchForm.use_min_win_rate = typeof gates.min_win_rate === 'number'
    aiResearchForm.min_win_rate = Number(gates.min_win_rate ?? 50)
    if (typeof gates.out_of_sample_validation === 'boolean') {
      aiResearchForm.out_of_sample_validation = gates.out_of_sample_validation
    }
    if (typeof gates.require_out_of_sample_validation === 'boolean') {
      aiResearchForm.require_out_of_sample_validation = gates.require_out_of_sample_validation
    }
    if (typeof gates.out_of_sample_ratio === 'number') {
      aiResearchForm.out_of_sample_ratio_pct = outOfSampleRatioPct(gates.out_of_sample_ratio)
    }
    aiResearchForm.use_min_out_of_sample_sharpe =
      typeof gates.min_out_of_sample_sharpe === 'number'
    aiResearchForm.min_out_of_sample_sharpe = Number(gates.min_out_of_sample_sharpe ?? 0.6)
    aiResearchForm.use_min_out_of_sample_trades =
      typeof gates.min_out_of_sample_trades === 'number'
    aiResearchForm.min_out_of_sample_trades = Number(gates.min_out_of_sample_trades ?? 1)
    if (typeof gates.robustness_validation === 'boolean') {
      aiResearchForm.robustness_validation = gates.robustness_validation
    }
    if (typeof gates.require_robustness_validation === 'boolean') {
      aiResearchForm.require_robustness_validation = gates.require_robustness_validation
    }
    const methods = stringArrayFromUnknown(gates.robustness_methods)
    if (methods.length) aiResearchForm.robustness_methods = methods
    if (typeof gates.min_robustness_score === 'number') {
      aiResearchForm.min_robustness_score = gates.min_robustness_score
    }
    if (typeof gates.robustness_monte_carlo_iterations === 'number') {
      aiResearchForm.robustness_monte_carlo_iterations = gates.robustness_monte_carlo_iterations
    }
    aiResearchForm.robustness_random_seed = optionalNumber(gates.robustness_random_seed)
  }

  async function createAIResearchMandateFromPayload(
    payload: ReturnType<typeof aiResearchMandatePayload>,
  ) {
    aiResearchMandateLoading.value = true
    try {
      aiResearchMandate.value = await strategyApi.createAIResearchMandate(payload)
      aiResearchMandateConfirmed.value = false
      ElMessage.success(t('strategy.aiResearchMandateStructured'))
      return aiResearchMandate.value
    } catch {
      ElMessage.error(t('strategy.aiResearchMandateStructureFailed'))
      return null
    } finally {
      aiResearchMandateLoading.value = false
    }
  }

  async function parseAIResearchMandate(input?: AIResearchMandateInput | null) {
    return createAIResearchMandateFromPayload(aiResearchMandatePayload(input))
  }

  function confirmAIResearchMandate() {
    if (!aiResearchMandate.value) return
    aiResearchMandateConfirmed.value = true
    ElMessage.success(t('strategy.aiResearchMandateConfirmed'))
  }

  function clearAIResearchMandate() {
    aiResearchMandate.value = null
    aiResearchMandateConfirmed.value = false
  }

  async function loadAIResearchMandate(mandateId: string | null | undefined) {
    const id = stringFromUnknown(mandateId)
    if (!id) {
      clearAIResearchMandate()
      return
    }
    try {
      aiResearchMandate.value = await strategyApi.getAIResearchMandate(id)
      aiResearchMandateConfirmed.value = true
    } catch {
      aiResearchMandate.value = null
      aiResearchMandateConfirmed.value = false
    }
  }

  async function ensureAIResearchMandateConfirmed(snapshot: AIResearchMandateSnapshot) {
    if (
      aiResearchMandate.value
      && aiResearchMandateConfirmed.value
      && aiResearchMandateMatchesSnapshot(aiResearchMandate.value, snapshot)
    ) {
      return aiResearchMandate.value
    }
    await createAIResearchMandateFromPayload(aiResearchMandatePayloadFromSnapshot(snapshot))
    ElMessage.warning(t('strategy.aiResearchMandateConfirmationRequired'))
    return null
  }

  function aiResearchMandateMarketDataAssetTypeMatches(
    actual: unknown,
    expected: MarketAssetType | undefined,
  ): boolean {
    if (expected) return actual === expected
    return actual === undefined || actual === null
  }

  function aiResearchMandateControlledTradingConstraints(
    constraints: Record<string, unknown>,
  ): Record<string, unknown> {
    const controlled = { ...constraints }
    delete controlled.start_paper_trading
    return controlled
  }

  function aiResearchMandateValueMatches(actual: unknown, expected: unknown): boolean {
    if (Array.isArray(expected)) {
      return Array.isArray(actual)
        && actual.length === expected.length
        && actual.every((value, index) => aiResearchMandateValueMatches(value, expected[index]))
    }
    if (isRecord(expected)) {
      return isRecord(actual) && aiResearchMandateRecordMatches(actual, expected)
    }
    return actual === expected || (actual == null && expected == null)
  }

  function aiResearchMandateRecordMatches(
    actual: Record<string, unknown> | null | undefined,
    expected: Record<string, unknown>,
  ): boolean {
    if (!actual) return false
    return Object.entries(expected).every(([key, value]) => (
      aiResearchMandateValueMatches(actual[key], value)
    ))
  }

  function aiResearchMandateMatchesSnapshot(
    mandate: InvestmentMandateResponse,
    snapshot: AIResearchMandateSnapshot,
  ) {
    const prompt = snapshot.rawPrompt.trim()
    const symbol = (snapshot.symbol || '').trim()
    const symbolName = (snapshot.symbolName || '').trim()
    const timeframe = snapshot.timeframe || ''
    const mandateSymbol = stringFromUnknown(mandate.asset_scope.symbol).trim()
    const mandateSymbolName = stringFromUnknown(mandate.asset_scope.symbol_name).trim()
    const mandateMarketDataAssetType = mandate.asset_scope.market_data_asset_type
    const mandateTimeframe = stringFromUnknown(mandate.timeframe || mandate.structured_goal.timeframe)
    const mandatePromptOrigin = stringFromUnknown(mandate.structured_goal.prompt_origin)
    return (
      mandatePromptOrigin === snapshot.promptOrigin
      && (snapshot.promptOrigin === 'auto_generated' || mandate.raw_prompt.trim() === prompt)
      && (!mandateSymbol || mandateSymbol === symbol)
      && (!mandateSymbolName || mandateSymbolName === symbolName)
      && aiResearchMandateMarketDataAssetTypeMatches(
        mandateMarketDataAssetType,
        snapshot.marketDataAssetType,
      )
      && (!mandateTimeframe || mandateTimeframe === timeframe)
      && aiResearchMandateRecordMatches(mandate.risk_constraints, snapshot.riskConstraints)
      && aiResearchMandateRecordMatches(
        mandate.trading_constraints,
        aiResearchMandateControlledTradingConstraints(snapshot.tradingConstraints),
      )
      && aiResearchMandateRecordMatches(mandate.quality_gates, snapshot.qualityGates)
    )
  }

  function aiResearchMandateMatchesInput(
    mandate: InvestmentMandateResponse,
    input: AIResearchMandateInput,
  ) {
    return aiResearchMandateMatchesSnapshot(mandate, aiResearchMandateSnapshot(input))
  }

  return {
    aiResearchMandate,
    aiResearchMandateConfirmed,
    aiResearchMandateLoading,
    aiResearchPromptGenerationDialogVisible,
    aiResearchPromptGenerationMode,
    aiResearchPromptGenerationLoading,
    aiResearchMandateDetails,
    aiResearchSymbolLabel,
    aiResearchQualityGateLines,
    aiResearchValidationLines,
    buildGeneratedAIResearchPrompt,
    generateAIResearchPrompt,
    openAIResearchPromptGenerationDialog,
    closeAIResearchPromptGenerationDialog,
    aiResearchObjectiveOptimizationConfig,
    confirmAIResearchPromptGeneration,
    aiResearchMandateQualityGatesFromForm,
    aiResearchMandateInputPrompt,
    aiResearchContinuationRunnableInput,
    aiResearchMandateSnapshot,
    aiResearchMandatePayloadFromSnapshot,
    aiResearchMandatePayload,
    applyAIResearchMandateSnapshotToForm,
    createAIResearchMandateFromPayload,
    parseAIResearchMandate,
    confirmAIResearchMandate,
    clearAIResearchMandate,
    loadAIResearchMandate,
    ensureAIResearchMandateConfirmed,
    aiResearchMandateMatchesSnapshot,
    aiResearchMandateMarketDataAssetTypeMatches,
    aiResearchMandateControlledTradingConstraints,
    aiResearchMandateRecordMatches,
    aiResearchMandateValueMatches,
    aiResearchMandateMatchesInput,
  }
}
