import { computed, ref, type Ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { MarketAssetType } from '@/api/marketData'
import {
  strategyApi,
  type AIStrategyResearchConfigProfile,
  type AIStrategyResearchRunRecord,
  type AIStrategyResearchRunResponse,
} from '@/api/strategy'
import type { AIResearchFormState } from './aiResearchConstants'
import {
  configStringValue,
  formatAIResearchConfigJson,
  formatMetric,
  hasConfigKey,
  outOfSampleRatioPct,
  researchRunTimestamp,
} from './aiResearchFormatters'
import {
  optionalBoolean,
  optionalNumber,
  stringArrayFromUnknown,
  stringFromUnknown,
} from './aiResearchValueAdapters'

export type AIResearchConfigProfileApi = typeof strategyApi & {
  listAIResearchConfigProfiles?: typeof strategyApi.listAIResearchConfigProfiles
  createAIResearchConfigProfile?: typeof strategyApi.createAIResearchConfigProfile
  updateAIResearchConfigProfile?: typeof strategyApi.updateAIResearchConfigProfile
  deleteAIResearchConfigProfile?: typeof strategyApi.deleteAIResearchConfigProfile
  importAIResearchConfigProfileYaml?: typeof strategyApi.importAIResearchConfigProfileYaml
}

export interface AIResearchConfigProfilesDeps {
  t: (key: string, params?: Record<string, unknown>) => string
  aiResearchForm: AIResearchFormState
  aiResearchRunning: Ref<boolean>
  aiResearchResult: Ref<AIStrategyResearchRunResponse | null>
  aiResearchActiveConfigProfile: Ref<AIStrategyResearchConfigProfile | null>
  aiResearchRuns: Ref<AIStrategyResearchRunRecord[]>
  isAIResearchMarketDataAssetType: (value: unknown) => value is MarketAssetType
  buildGeneratedAIResearchPrompt: () => string
  clearAIResearchMandate: () => void
  clearAIResearchArtifacts: () => void
  resetAIResearchTaskState: () => void
  selectAIResearchRunRecord: (
    record: AIStrategyResearchRunRecord,
    options?: { keepSelectedProfile?: boolean },
  ) => void
}

export function useAIResearchConfigProfiles(deps: AIResearchConfigProfilesDeps) {
  const { t, aiResearchForm } = deps

  const aiResearchConfigDialogVisible = ref(false)
  const aiResearchConfigProfiles = ref<AIStrategyResearchConfigProfile[]>([])
  const aiResearchConfigProfilesLoading = ref(false)
  const aiResearchConfigProfileSaving = ref(false)
  const aiResearchConfigProfileImporting = ref(false)
  const aiResearchConfigProfileDeletingId = ref('')
  const aiResearchSelectedConfigProfileId = ref('')
  const aiResearchConfigProfileName = ref('')
  const aiResearchConfigProfileDescription = ref('')
  const aiResearchConfigProfileFilePath = ref('')
  const aiResearchConfigProfileFileInput = ref<HTMLInputElement | null>(null)

  const aiResearchSelectedConfigProfile = computed(() =>
    aiResearchConfigProfiles.value.find(
      profile => profile.id === aiResearchSelectedConfigProfileId.value,
    ) ?? null,
  )

  function aiResearchConfigProfileApi(): AIResearchConfigProfileApi {
    return strategyApi as AIResearchConfigProfileApi
  }

  function snapshotAIResearchConfigForm(): Record<string, unknown> {
    return {
      ...JSON.parse(JSON.stringify(aiResearchForm)),
      seed_strategy_id: '',
      continue_from_run_id: '',
      continuation_source: '',
    }
  }

  function applyAIResearchConfigToForm(config: Record<string, unknown>) {
    aiResearchForm.prompt = stringFromUnknown(config.prompt)
    aiResearchForm.workflow_mode = config.workflow_mode === 'prompt' ? 'prompt' : 'auto'
    aiResearchForm.symbol = stringFromUnknown(config.symbol, aiResearchForm.symbol)
    aiResearchForm.symbol_name = stringFromUnknown(config.symbol_name)
    aiResearchForm.market_data_asset_type = deps.isAIResearchMarketDataAssetType(
      config.market_data_asset_type,
    )
      ? config.market_data_asset_type
      : ''
    aiResearchForm.timeframe = stringFromUnknown(config.timeframe, aiResearchForm.timeframe)
    aiResearchForm.timeframe_n = optionalNumber(config.timeframe_n) ?? aiResearchForm.timeframe_n
    aiResearchForm.start_date = configStringValue(config, 'start_date', aiResearchForm.start_date)
    aiResearchForm.end_date = configStringValue(config, 'end_date', aiResearchForm.end_date)
    aiResearchForm.knowledge_base_id = stringFromUnknown(config.knowledge_base_id)
    aiResearchForm.thinking_mode = optionalBoolean(config.thinking_mode, aiResearchForm.thinking_mode)
    aiResearchForm.target_sharpe = optionalNumber(config.target_sharpe) ?? aiResearchForm.target_sharpe
    aiResearchForm.min_total_trades =
      optionalNumber(config.min_total_trades) ?? aiResearchForm.min_total_trades

    const maxDrawdownLimit = optionalNumber(config.max_drawdown_limit)
    aiResearchForm.use_max_drawdown_limit = optionalBoolean(
      config.use_max_drawdown_limit,
      maxDrawdownLimit !== null,
    )
    aiResearchForm.max_drawdown_limit = maxDrawdownLimit ?? aiResearchForm.max_drawdown_limit
    const minTotalReturn = optionalNumber(config.min_total_return)
    aiResearchForm.use_min_total_return = optionalBoolean(
      config.use_min_total_return,
      minTotalReturn !== null,
    )
    aiResearchForm.min_total_return = minTotalReturn ?? aiResearchForm.min_total_return
    const minAnnualReturn = optionalNumber(config.min_annual_return)
    aiResearchForm.use_min_annual_return = optionalBoolean(
      config.use_min_annual_return,
      minAnnualReturn !== null,
    )
    aiResearchForm.min_annual_return = minAnnualReturn ?? aiResearchForm.min_annual_return
    const minWinRate = optionalNumber(config.min_win_rate)
    aiResearchForm.use_min_win_rate = optionalBoolean(
      config.use_min_win_rate,
      minWinRate !== null,
    )
    aiResearchForm.min_win_rate = minWinRate ?? aiResearchForm.min_win_rate

    aiResearchForm.max_iterations = optionalNumber(config.max_iterations) ?? aiResearchForm.max_iterations
    aiResearchForm.out_of_sample_validation = optionalBoolean(
      config.out_of_sample_validation,
      aiResearchForm.out_of_sample_validation,
    )
    aiResearchForm.require_out_of_sample_validation = optionalBoolean(
      config.require_out_of_sample_validation,
      aiResearchForm.require_out_of_sample_validation,
    )
    aiResearchForm.out_of_sample_ratio_pct =
      optionalNumber(config.out_of_sample_ratio_pct)
      ?? outOfSampleRatioPct(config.out_of_sample_ratio)
    const minOutOfSampleSharpe = optionalNumber(config.min_out_of_sample_sharpe)
    aiResearchForm.use_min_out_of_sample_sharpe = optionalBoolean(
      config.use_min_out_of_sample_sharpe,
      minOutOfSampleSharpe !== null,
    )
    aiResearchForm.min_out_of_sample_sharpe =
      minOutOfSampleSharpe ?? aiResearchForm.min_out_of_sample_sharpe
    const minOutOfSampleTrades = optionalNumber(config.min_out_of_sample_trades)
    aiResearchForm.use_min_out_of_sample_trades = optionalBoolean(
      config.use_min_out_of_sample_trades,
      minOutOfSampleTrades !== null,
    )
    aiResearchForm.min_out_of_sample_trades =
      minOutOfSampleTrades ?? aiResearchForm.min_out_of_sample_trades

    aiResearchForm.robustness_validation = optionalBoolean(
      config.robustness_validation,
      aiResearchForm.robustness_validation,
    )
    aiResearchForm.require_robustness_validation = optionalBoolean(
      config.require_robustness_validation,
      aiResearchForm.require_robustness_validation,
    )
    const robustnessMethods = stringArrayFromUnknown(config.robustness_methods)
    aiResearchForm.robustness_methods = robustnessMethods.length
      ? robustnessMethods
      : aiResearchForm.robustness_methods
    aiResearchForm.min_robustness_score =
      optionalNumber(config.min_robustness_score) ?? aiResearchForm.min_robustness_score
    aiResearchForm.robustness_monte_carlo_iterations =
      optionalNumber(config.robustness_monte_carlo_iterations)
      ?? aiResearchForm.robustness_monte_carlo_iterations
    aiResearchForm.robustness_random_seed = optionalNumber(config.robustness_random_seed)

    aiResearchForm.initial_cash = optionalNumber(config.initial_cash) ?? aiResearchForm.initial_cash
    aiResearchForm.use_manual_commission = optionalBoolean(
      config.use_manual_commission,
      hasConfigKey(config, 'commission'),
    )
    aiResearchForm.commission = optionalNumber(config.commission) ?? aiResearchForm.commission
    aiResearchForm.annual_days = optionalNumber(config.annual_days) ?? aiResearchForm.annual_days
    aiResearchForm.calc_method = stringFromUnknown(config.calc_method, aiResearchForm.calc_method)
    aiResearchForm.weight_mode = stringFromUnknown(config.weight_mode, aiResearchForm.weight_mode)
    aiResearchForm.group_name = stringFromUnknown(config.group_name)
    aiResearchForm.backtest_timeout_seconds =
      optionalNumber(config.backtest_timeout_seconds) ?? aiResearchForm.backtest_timeout_seconds
    aiResearchForm.poll_interval_seconds =
      optionalNumber(config.poll_interval_seconds) ?? aiResearchForm.poll_interval_seconds
    aiResearchForm.research_workspace_id = stringFromUnknown(config.research_workspace_id)
    aiResearchForm.seed_strategy_id = stringFromUnknown(config.seed_strategy_id)
    aiResearchForm.continue_from_run_id = stringFromUnknown(config.continue_from_run_id)
    aiResearchForm.continuation_source = stringFromUnknown(config.continuation_source)
    aiResearchForm.start_paper_trading = optionalBoolean(
      config.start_paper_trading,
      aiResearchForm.start_paper_trading,
    )
    aiResearchForm.min_paper_trading_days =
      optionalNumber(config.min_paper_trading_days) ?? aiResearchForm.min_paper_trading_days
    aiResearchForm.paper_workspace_name = stringFromUnknown(config.paper_workspace_name)
    aiResearchForm.trading_workspace_id = stringFromUnknown(config.trading_workspace_id)
    aiResearchForm.gateway_config_json =
      stringFromUnknown(config.gateway_config_json) || formatAIResearchConfigJson(config.gateway_config)
    aiResearchForm.live_workspace_name = stringFromUnknown(config.live_workspace_name)
    aiResearchForm.live_trading_workspace_id = stringFromUnknown(config.live_trading_workspace_id)
    aiResearchForm.live_gateway_config_json =
      stringFromUnknown(config.live_gateway_config_json)
      || formatAIResearchConfigJson(config.live_gateway_config)
  }

  function aiResearchConfigProfileValue(profile: AIStrategyResearchConfigProfile, key: string) {
    return stringFromUnknown(profile.config[key], '-')
  }

  function aiResearchConfigProfileMetric(
    profile: AIStrategyResearchConfigProfile,
    key: string,
    digits = 2,
  ) {
    const value = optionalNumber(profile.config[key])
    return value === null ? '-' : formatMetric(value, digits)
  }

  function aiResearchConfigProfileOos(profile: AIStrategyResearchConfigProfile) {
    if (!optionalBoolean(profile.config.out_of_sample_validation, false)) return '关闭'
    const ratioPct = optionalNumber(profile.config.out_of_sample_ratio_pct)
      ?? outOfSampleRatioPct(profile.config.out_of_sample_ratio)
    return `${formatMetric(ratioPct, 0)}%`
  }

  function aiResearchConfigProfileSummary(profile: AIStrategyResearchConfigProfile | null) {
    if (!profile) return '未选择方案'
    const parts = [
      aiResearchConfigProfileValue(profile, 'symbol'),
      aiResearchConfigProfileValue(profile, 'timeframe'),
      `Sharpe ${aiResearchConfigProfileMetric(profile, 'target_sharpe')}`,
      `最多 ${aiResearchConfigProfileMetric(profile, 'max_iterations', 0)} 轮`,
    ].filter(part => part && !String(part).includes('-'))
    return parts.length ? parts.join(' · ') : profile.name
  }

  function aiResearchProfileStringMatches(
    config: Record<string, unknown>,
    key: string,
    actual: unknown,
    collapseWhitespace = false,
  ) {
    if (!hasConfigKey(config, key)) return true
    const normalize = (value: unknown) => {
      const text = stringFromUnknown(value).trim()
      return collapseWhitespace ? text.replace(/\s+/g, ' ') : text
    }
    return normalize(config[key]) === normalize(actual)
  }

  function aiResearchProfileNumberMatches(
    config: Record<string, unknown>,
    key: string,
    actual: unknown,
  ) {
    if (!hasConfigKey(config, key)) return true
    const expected = optionalNumber(config[key])
    const actualNumber = optionalNumber(actual)
    if (expected === null || actualNumber === null) return expected === actualNumber
    return Math.abs(expected - actualNumber) < 1e-9
  }

  function aiResearchProfileBooleanMatches(
    config: Record<string, unknown>,
    gates: Record<string, unknown>,
    key: string,
  ) {
    if (!hasConfigKey(config, key)) return true
    return optionalBoolean(config[key], false) === optionalBoolean(gates[key], false)
  }

  function aiResearchProfileGateMatches(
    config: Record<string, unknown>,
    gates: Record<string, unknown>,
    key: string,
    enabledKey: string,
  ) {
    if (!hasConfigKey(config, key) && !hasConfigKey(config, enabledKey)) return true
    const enabled = hasConfigKey(config, enabledKey)
      ? optionalBoolean(config[enabledKey], false)
      : optionalNumber(config[key]) !== null
    if (!enabled) return optionalNumber(gates[key]) === null
    const expected = optionalNumber(config[key])
    const actual = optionalNumber(gates[key])
    if (expected === null || actual === null) return expected === actual
    return Math.abs(expected - actual) < 1e-9
  }

  function aiResearchProfileRatioMatches(
    config: Record<string, unknown>,
    gates: Record<string, unknown>,
  ) {
    if (!hasConfigKey(config, 'out_of_sample_ratio_pct') && !hasConfigKey(config, 'out_of_sample_ratio')) {
      return true
    }
    const expected = hasConfigKey(config, 'out_of_sample_ratio_pct')
      ? optionalNumber(config.out_of_sample_ratio_pct)
      : optionalNumber(config.out_of_sample_ratio)
    const expectedRatio = hasConfigKey(config, 'out_of_sample_ratio_pct')
      ? expected === null ? null : expected / 100
      : expected
    const actual = optionalNumber(gates.out_of_sample_ratio)
    if (expectedRatio === null || actual === null) return expectedRatio === actual
    return Math.abs(expectedRatio - actual) < 1e-9
  }

  function aiResearchProfileStringArrayMatches(
    config: Record<string, unknown>,
    gates: Record<string, unknown>,
    key: string,
  ) {
    if (!hasConfigKey(config, key)) return true
    const expected = stringArrayFromUnknown(config[key]).sort()
    const actual = stringArrayFromUnknown(gates[key]).sort()
    return expected.length === actual.length && expected.every((item, index) => item === actual[index])
  }

  function aiResearchRunMatchesConfigProfile(
    record: AIStrategyResearchRunRecord,
    profile: AIStrategyResearchConfigProfile,
  ) {
    const config = profile.config || {}
    const researchWorkspaceId = stringFromUnknown(config.research_workspace_id).trim()
    const symbol = stringFromUnknown(config.symbol).trim()
    const timeframe = stringFromUnknown(config.timeframe).trim().toLowerCase()
    const timeframeN = optionalNumber(config.timeframe_n)
    if (researchWorkspaceId && record.research_workspace_id.trim() !== researchWorkspaceId) {
      return false
    }
    if (!symbol && !timeframe && timeframeN === null) return false
    if (symbol && record.symbol.trim() !== symbol) return false
    if (timeframe && record.timeframe.trim().toLowerCase() !== timeframe) return false
    if (timeframeN !== null && Number(record.timeframe_n || 1) !== timeframeN) return false
    if (researchWorkspaceId) return true
    if (!aiResearchProfileStringMatches(config, 'symbol_name', record.symbol_name)) return false
    if (!aiResearchProfileStringMatches(config, 'prompt', record.prompt, true)) return false
    if (!aiResearchProfileStringMatches(config, 'workflow_mode', record.workflow_mode)) return false
    if (!aiResearchProfileStringMatches(config, 'start_date', record.start_date || '')) return false
    if (!aiResearchProfileStringMatches(config, 'end_date', record.end_date || '')) return false
    if (!aiResearchProfileStringMatches(config, 'group_name', record.group_name || '')) return false
    if (!aiResearchProfileNumberMatches(config, 'target_sharpe', record.target_sharpe)) return false
    if (!aiResearchProfileNumberMatches(config, 'min_total_trades', record.min_total_trades)) return false
    if (!aiResearchProfileNumberMatches(config, 'max_iterations', record.max_iterations)) return false
    if (!aiResearchProfileNumberMatches(config, 'initial_cash', record.initial_cash)) return false
    if (!aiResearchProfileNumberMatches(config, 'annual_days', record.annual_days)) return false
    if (!aiResearchProfileStringMatches(config, 'calc_method', record.calc_method)) return false
    if (!aiResearchProfileStringMatches(config, 'weight_mode', record.weight_mode)) return false
    if (
      optionalBoolean(config.use_manual_commission, false)
      && !aiResearchProfileNumberMatches(config, 'commission', record.commission)
    ) return false

    const gates = record.quality_gates || {}
    if (!aiResearchProfileGateMatches(config, gates, 'max_drawdown_limit', 'use_max_drawdown_limit')) return false
    if (!aiResearchProfileGateMatches(config, gates, 'min_total_return', 'use_min_total_return')) return false
    if (!aiResearchProfileGateMatches(config, gates, 'min_annual_return', 'use_min_annual_return')) return false
    if (!aiResearchProfileGateMatches(config, gates, 'min_win_rate', 'use_min_win_rate')) return false
    if (!aiResearchProfileBooleanMatches(config, gates, 'out_of_sample_validation')) return false
    if (!aiResearchProfileBooleanMatches(config, gates, 'require_out_of_sample_validation')) return false
    if (!aiResearchProfileRatioMatches(config, gates)) return false
    if (!aiResearchProfileGateMatches(
      config,
      gates,
      'min_out_of_sample_sharpe',
      'use_min_out_of_sample_sharpe',
    )) return false
    if (!aiResearchProfileGateMatches(
      config,
      gates,
      'min_out_of_sample_trades',
      'use_min_out_of_sample_trades',
    )) return false
    if (!aiResearchProfileBooleanMatches(config, gates, 'robustness_validation')) return false
    if (!aiResearchProfileBooleanMatches(config, gates, 'require_robustness_validation')) return false
    if (!aiResearchProfileStringArrayMatches(config, gates, 'robustness_methods')) return false
    if (!aiResearchProfileNumberMatches(config, 'min_robustness_score', gates.min_robustness_score)) return false
    if (!aiResearchProfileNumberMatches(
      config,
      'robustness_monte_carlo_iterations',
      gates.robustness_monte_carlo_iterations,
    )) return false
    return Boolean(symbol || timeframe || timeframeN !== null)
  }

  function upsertAIResearchConfigProfile(profile: AIStrategyResearchConfigProfile) {
    const index = aiResearchConfigProfiles.value.findIndex(item => item.id === profile.id)
    if (index < 0) {
      aiResearchConfigProfiles.value = [...aiResearchConfigProfiles.value, profile].sort(
        (left, right) => left.name.localeCompare(right.name),
      )
      return
    }
    aiResearchConfigProfiles.value = aiResearchConfigProfiles.value.map(item =>
      item.id === profile.id ? profile : item,
    )
  }

  function setAIResearchConfigProfileEditor(profile: AIStrategyResearchConfigProfile | null) {
    aiResearchSelectedConfigProfileId.value = profile?.id ?? ''
    aiResearchConfigProfileName.value = profile?.name ?? ''
    aiResearchConfigProfileDescription.value = profile?.description ?? ''
  }

  function ensureAIResearchVisiblePrompt() {
    if (aiResearchForm.prompt.trim()) return
    aiResearchForm.prompt = deps.buildGeneratedAIResearchPrompt()
  }

  function applyAIResearchConfigProfile(
    profile: AIStrategyResearchConfigProfile,
    options: { notify?: boolean; syncResult?: boolean } = {},
  ) {
    if (deps.aiResearchRunning.value) {
      ElMessage.warning(t('strategy.aiResearchConfigSwitchBusy'))
      return
    }
    setAIResearchConfigProfileEditor(profile)
    applyAIResearchConfigToForm(profile.config)
    ensureAIResearchVisiblePrompt()
    deps.clearAIResearchMandate()
    if (options.syncResult ?? true) {
      syncAIResearchDisplayedOutputWithSelectedProfile()
    }
    if (options.notify ?? true) ElMessage.success(t('strategy.aiResearchConfigLoaded', { name: profile.name }))
  }

  function openAIResearchConfigDialog() {
    aiResearchConfigDialogVisible.value = true
  }

  function selectAIResearchConfigProfile(profileId: string | number | boolean | undefined) {
    const selectedId = String(profileId || '')
    const profile = aiResearchConfigProfiles.value.find(item => item.id === selectedId)
    if (!profile) return
    applyAIResearchConfigProfile(profile)
  }

  function clearAIResearchDisplayedOutput() {
    deps.aiResearchResult.value = null
    deps.aiResearchActiveConfigProfile.value = null
    deps.clearAIResearchArtifacts()
    deps.clearAIResearchMandate()
    deps.resetAIResearchTaskState()
    aiResearchForm.seed_strategy_id = ''
    aiResearchForm.continue_from_run_id = ''
    aiResearchForm.continuation_source = ''
  }

  function currentAIResearchResultMatchesConfigProfile(profile: AIStrategyResearchConfigProfile) {
    const record = deps.aiResearchResult.value?.run_record
    return Boolean(record && aiResearchRunMatchesConfigProfile(record, profile))
  }

  function defaultAIResearchConfigProfile(
    profiles: AIStrategyResearchConfigProfile[],
  ): AIStrategyResearchConfigProfile | null {
    return profiles.find(profile => profile.name.trim() === '螺纹钢')
      ?? profiles.find(profile => (
        stringFromUnknown(profile.config?.symbol).trim() === 'RB0'
        && stringFromUnknown(profile.config?.timeframe).trim().toLowerCase() === '1h'
      ))
      ?? profiles[0]
      ?? null
  }

  function aiResearchConfigProfileForRunRecord(record: AIStrategyResearchRunRecord) {
    return aiResearchConfigProfiles.value.find(profile =>
      aiResearchRunMatchesConfigProfile(record, profile),
    ) ?? null
  }

  function setAIResearchConfigProfileFromRunRecord(record: AIStrategyResearchRunRecord) {
    const profile = aiResearchConfigProfileForRunRecord(record)
    if (profile) setAIResearchConfigProfileEditor(profile)
  }

  function latestAIResearchRunForConfigProfile(profile: AIStrategyResearchConfigProfile) {
    return deps.aiResearchRuns.value
      .filter(record => aiResearchRunMatchesConfigProfile(record, profile))
      .sort((left, right) => researchRunTimestamp(right) - researchRunTimestamp(left))[0]
      ?? null
  }

  function syncAIResearchDisplayedOutputWithSelectedProfile() {
    const profile = aiResearchSelectedConfigProfile.value
    if (!profile || deps.aiResearchRunning.value) return
    if (currentAIResearchResultMatchesConfigProfile(profile)) return
    const matchedRun = latestAIResearchRunForConfigProfile(profile)
    if (matchedRun) {
      deps.selectAIResearchRunRecord(matchedRun, { keepSelectedProfile: true })
    } else {
      clearAIResearchDisplayedOutput()
    }
  }

  async function loadAIResearchConfigProfiles(options: { showError?: boolean } = {}) {
    const api = aiResearchConfigProfileApi()
    if (typeof api.listAIResearchConfigProfiles !== 'function') return
    if (aiResearchConfigProfilesLoading.value) return
    aiResearchConfigProfilesLoading.value = true
    try {
      const response = await api.listAIResearchConfigProfiles()
      aiResearchConfigProfiles.value = response.items
      aiResearchConfigProfileFilePath.value = response.file_path
      const selected = aiResearchSelectedConfigProfile.value
      if (selected) applyAIResearchConfigProfile(selected, { notify: false })
      if (!selected) {
        const defaultProfile = defaultAIResearchConfigProfile(response.items)
        if (defaultProfile) applyAIResearchConfigProfile(defaultProfile, { notify: false })
      }
    } catch {
      if (options.showError) ElMessage.error(t('strategy.aiResearchConfigLoadFailed'))
    } finally {
      aiResearchConfigProfilesLoading.value = false
    }
  }

  async function createAIResearchConfigProfile() {
    const api = aiResearchConfigProfileApi()
    if (typeof api.createAIResearchConfigProfile !== 'function') return
    const name = aiResearchConfigProfileName.value.trim()
    if (!name) {
      ElMessage.warning(t('strategy.aiResearchConfigNameRequired'))
      return
    }
    aiResearchConfigProfileSaving.value = true
    try {
      const profile = await api.createAIResearchConfigProfile({
        name,
        description: aiResearchConfigProfileDescription.value.trim(),
        config: snapshotAIResearchConfigForm(),
      })
      upsertAIResearchConfigProfile(profile)
      setAIResearchConfigProfileEditor(profile)
      ElMessage.success(t('strategy.aiResearchConfigCreated'))
    } catch {
      ElMessage.error(t('strategy.aiResearchConfigCreateFailed'))
    } finally {
      aiResearchConfigProfileSaving.value = false
    }
  }

  async function saveAIResearchConfigProfile(profileId = aiResearchSelectedConfigProfileId.value) {
    const api = aiResearchConfigProfileApi()
    if (typeof api.updateAIResearchConfigProfile !== 'function') return
    const profile = aiResearchConfigProfiles.value.find(item => item.id === profileId)
    if (!profile) {
      ElMessage.warning(t('strategy.aiResearchConfigSelectionRequired'))
      return
    }
    const isEditingSelected = profile.id === aiResearchSelectedConfigProfileId.value
    const name = isEditingSelected
      ? aiResearchConfigProfileName.value.trim() || profile.name
      : profile.name
    const description = isEditingSelected
      ? aiResearchConfigProfileDescription.value.trim()
      : profile.description
    aiResearchConfigProfileSaving.value = true
    try {
      const updated = await api.updateAIResearchConfigProfile(profile.id, {
        name,
        description,
        config: snapshotAIResearchConfigForm(),
      })
      upsertAIResearchConfigProfile(updated)
      setAIResearchConfigProfileEditor(updated)
      ElMessage.success(t('strategy.aiResearchConfigSaved'))
    } catch {
      ElMessage.error(t('strategy.aiResearchConfigSaveFailed'))
    } finally {
      aiResearchConfigProfileSaving.value = false
    }
  }

  async function deleteAIResearchConfigProfile(profile: AIStrategyResearchConfigProfile) {
    const api = aiResearchConfigProfileApi()
    if (typeof api.deleteAIResearchConfigProfile !== 'function') return
    try {
      await ElMessageBox.confirm(
        t('strategy.aiResearchDeleteConfigConfirm', { name: profile.name }),
        t('strategy.aiResearchDeleteConfigTitle'),
        { type: 'warning' },
      )
    } catch {
      return
    }
    aiResearchConfigProfileDeletingId.value = profile.id
    try {
      await api.deleteAIResearchConfigProfile(profile.id)
      aiResearchConfigProfiles.value = aiResearchConfigProfiles.value.filter(
        item => item.id !== profile.id,
      )
      if (aiResearchSelectedConfigProfileId.value === profile.id) {
        setAIResearchConfigProfileEditor(null)
      }
      ElMessage.success(t('strategy.aiResearchConfigDeleted'))
    } catch {
      ElMessage.error(t('strategy.aiResearchConfigDeleteFailed'))
    } finally {
      aiResearchConfigProfileDeletingId.value = ''
    }
  }

  function triggerAIResearchConfigProfileImport() {
    aiResearchConfigProfileFileInput.value?.click()
  }

  function readSelectedAIResearchConfigFile(file: File) {
    return new Promise<string>((resolve, reject) => {
      const reader = new FileReader()
      reader.onload = () => resolve(String(reader.result || ''))
      reader.onerror = () => reject(reader.error ?? new Error('读取 YAML 文件失败'))
      reader.readAsText(file)
    })
  }

  async function importAIResearchConfigProfileFile(event: Event) {
    const api = aiResearchConfigProfileApi()
    if (typeof api.importAIResearchConfigProfileYaml !== 'function') return
    const input = event.target as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    aiResearchConfigProfileImporting.value = true
    try {
      const rawYaml = await readSelectedAIResearchConfigFile(file)
      const fallbackName = file.name.replace(/\.(ya?ml)$/i, '')
      const response = await api.importAIResearchConfigProfileYaml({
        raw_yaml: rawYaml,
        name: fallbackName,
      })
      aiResearchConfigProfileFilePath.value = response.file_path
      response.items.forEach(upsertAIResearchConfigProfile)
      if (response.items[0]) applyAIResearchConfigProfile(response.items[0])
      ElMessage.success(t('strategy.aiResearchConfigsImported', { count: response.total }))
    } catch {
      ElMessage.error(t('strategy.aiResearchConfigImportFailed'))
    } finally {
      aiResearchConfigProfileImporting.value = false
    }
  }

  async function bindAIResearchConfigProfileToRunRecord(
    profile: AIStrategyResearchConfigProfile,
    record: AIStrategyResearchRunRecord,
  ) {
    const workspaceId = record.research_workspace_id.trim()
    if (!workspaceId || stringFromUnknown(profile.config.research_workspace_id).trim()) return
    const api = aiResearchConfigProfileApi()
    if (typeof api.updateAIResearchConfigProfile !== 'function') return
    try {
      const updated = await api.updateAIResearchConfigProfile(profile.id, {
        config: { ...profile.config, research_workspace_id: workspaceId },
      })
      upsertAIResearchConfigProfile(updated)
      if (aiResearchSelectedConfigProfileId.value === updated.id) {
        aiResearchForm.research_workspace_id = workspaceId
      }
      if (deps.aiResearchActiveConfigProfile.value?.id === updated.id) {
        deps.aiResearchActiveConfigProfile.value = updated
      }
    } catch {
      // The completed research output remains usable even if its profile cannot be saved.
    }
  }

  const aiResearchSelectedProfileSummary = computed(() =>
    aiResearchConfigProfileSummary(aiResearchSelectedConfigProfile.value),
  )

  const aiResearchOutputConfigProfile = computed(() => {
    if (deps.aiResearchRunning.value) {
      return deps.aiResearchActiveConfigProfile.value ?? aiResearchSelectedConfigProfile.value
    }
    const record = deps.aiResearchResult.value?.run_record
    return record
      ? aiResearchConfigProfileForRunRecord(record) ?? aiResearchSelectedConfigProfile.value
      : aiResearchSelectedConfigProfile.value
  })

  const aiResearchOutputProfileSummary = computed(() =>
    aiResearchConfigProfileSummary(aiResearchOutputConfigProfile.value),
  )

  const aiResearchSelectedConfigDetails = computed(() => {
    const profile = aiResearchSelectedConfigProfile.value
    if (!profile) return []
    const config = profile.config
    const symbol = stringFromUnknown(config.symbol, '-')
    const symbolName = stringFromUnknown(config.symbol_name).trim()
    const timeframe = stringFromUnknown(config.timeframe, '-')
    const timeframeN = optionalNumber(config.timeframe_n)
    const startDate = stringFromUnknown(config.start_date, '-')
    const endDate = stringFromUnknown(config.end_date, '最新')
    const targetSharpe = aiResearchConfigProfileMetric(profile, 'target_sharpe')
    const minTrades = aiResearchConfigProfileMetric(profile, 'min_total_trades', 0)
    const oosRatio = aiResearchConfigProfileOos(profile)
    const oosSharpe = optionalBoolean(config.use_min_out_of_sample_sharpe, false)
      ? aiResearchConfigProfileMetric(profile, 'min_out_of_sample_sharpe')
      : '不限制'
    const initialCash = aiResearchConfigProfileMetric(profile, 'initial_cash', 0)
    const commission = aiResearchConfigProfileMetric(profile, 'commission', 6)
    const workflowMode = stringFromUnknown(config.workflow_mode) === 'prompt' ? '按提示执行' : '自动规划'
    return [
      {
        label: t('strategy.aiResearchSymbol'),
        value: symbolName ? `${symbol} · ${symbolName}` : symbol,
      },
      {
        label: t('strategy.aiResearchTimeframe'),
        value: timeframeN && timeframeN !== 1 ? `${timeframeN}${timeframe}` : timeframe,
      },
      {
        label: t('strategy.aiResearchPeriod'),
        value: `${startDate} 至 ${endDate}`,
      },
      {
        label: t('strategy.aiResearchQualityGates'),
        value: `Sharpe ${targetSharpe} · 交易 ${minTrades}`,
      },
      {
        label: t('strategy.aiResearchOutOfSample'),
        value: `${oosRatio} · Sharpe ${oosSharpe}`,
      },
      {
        label: t('strategy.aiResearchCapitalAndFees'),
        value: `${initialCash} · ${commission}`,
      },
      {
        label: t('strategy.aiResearchMaxIterations'),
        value: aiResearchConfigProfileMetric(profile, 'max_iterations', 0),
      },
      {
        label: t('strategy.aiResearchHeroWorkflow'),
        value: workflowMode,
      },
    ]
  })

  const aiResearchSelectedConfigPromptPreview = computed(() => {
    const profile = aiResearchSelectedConfigProfile.value
    if (!profile) return ''
    const prompt = stringFromUnknown(profile.config.prompt).trim().replace(/\n{3,}/g, '\n\n')
    if (!prompt) return ''
    return prompt.length > 900 ? `${prompt.slice(0, 900)}...` : prompt
  })

  const aiResearchVisibleRuns = computed(() => {
    const profile = aiResearchSelectedConfigProfile.value
    if (!profile) return deps.aiResearchRuns.value
    return deps.aiResearchRuns.value.filter(record => aiResearchRunMatchesConfigProfile(record, profile))
  })

  const aiResearchNoResultDescription = computed(() => {
    const profile = aiResearchSelectedConfigProfile.value
    if (!profile) return t('strategy.aiResearchNoResult')
    return `${profile.name} 暂无投研结果，运行该方案后会在这里显示。`
  })

  return {
    aiResearchConfigDialogVisible,
    aiResearchConfigProfiles,
    aiResearchConfigProfilesLoading,
    aiResearchConfigProfileSaving,
    aiResearchConfigProfileImporting,
    aiResearchConfigProfileDeletingId,
    aiResearchSelectedConfigProfileId,
    aiResearchConfigProfileName,
    aiResearchConfigProfileDescription,
    aiResearchConfigProfileFilePath,
    aiResearchConfigProfileFileInput,
    aiResearchSelectedConfigProfile,
    aiResearchSelectedProfileSummary,
    aiResearchOutputConfigProfile,
    aiResearchOutputProfileSummary,
    aiResearchSelectedConfigDetails,
    aiResearchSelectedConfigPromptPreview,
    aiResearchVisibleRuns,
    aiResearchNoResultDescription,
    aiResearchConfigProfileApi,
    snapshotAIResearchConfigForm,
    applyAIResearchConfigToForm,
    upsertAIResearchConfigProfile,
    setAIResearchConfigProfileEditor,
    ensureAIResearchVisiblePrompt,
    applyAIResearchConfigProfile,
    openAIResearchConfigDialog,
    selectAIResearchConfigProfile,
    clearAIResearchDisplayedOutput,
    currentAIResearchResultMatchesConfigProfile,
    defaultAIResearchConfigProfile,
    aiResearchConfigProfileForRunRecord,
    setAIResearchConfigProfileFromRunRecord,
    syncAIResearchDisplayedOutputWithSelectedProfile,
    latestAIResearchRunForConfigProfile,
    aiResearchRunMatchesConfigProfile,
    aiResearchConfigProfileValue,
    aiResearchConfigProfileMetric,
    aiResearchConfigProfileOos,
    loadAIResearchConfigProfiles,
    createAIResearchConfigProfile,
    saveAIResearchConfigProfile,
    deleteAIResearchConfigProfile,
    triggerAIResearchConfigProfileImport,
    readSelectedAIResearchConfigFile,
    importAIResearchConfigProfileFile,
    bindAIResearchConfigProfileToRunRecord,
  }
}
