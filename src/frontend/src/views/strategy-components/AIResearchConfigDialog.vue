<template>
  <el-dialog
    v-model="aiResearchConfigDialogVisible"
    :title="t('strategy.aiResearchConfigDialogTitle')"
    width="1100px"
    class="ai-research-config-dialog"
    destroy-on-close
  >
    <div
      class="ai-research-config-sheet"
      data-test="ai-research-config-profiles"
    >
      <div class="ai-research-config-head">
        <div>
          <strong>{{ t('strategy.aiResearchConfigTable') }}</strong>
          <span v-if="aiResearchConfigProfileFilePath">
            {{ aiResearchConfigProfileFilePath }}
          </span>
        </div>
        <div class="ai-research-config-head-actions">
          <el-button
            size="small"
            :loading="aiResearchConfigProfileImporting"
            data-test="ai-research-config-import"
            @click="triggerAIResearchConfigProfileImport"
          >
            <el-icon aria-hidden="true">
              <Upload />
            </el-icon>
            {{ t('strategy.aiResearchImportYaml') }}
          </el-button>
          <el-button
            size="small"
            :loading="aiResearchConfigProfilesLoading"
            data-test="ai-research-config-refresh"
            @click="loadAIResearchConfigProfiles({ showError: true })"
          >
            <el-icon aria-hidden="true">
              <RefreshRight />
            </el-icon>
            {{ t('common.refresh') }}
          </el-button>
        </div>
      </div>

      <input
        ref="aiResearchConfigProfileFileInput"
        class="ai-research-config-file-input"
        type="file"
        accept=".yaml,.yml,text/yaml,application/x-yaml"
        @change="importAIResearchConfigProfileFile"
      >

      <el-table
        v-loading="aiResearchConfigProfilesLoading"
        class="ai-research-config-table"
        :data="aiResearchConfigProfiles"
        size="small"
        row-key="id"
        highlight-current-row
        :empty-text="t('strategy.aiResearchConfigEmpty')"
        @row-click="(profile: Parameters<typeof applyAIResearchConfigProfile>[0]) => applyAIResearchConfigProfile(profile)"
      >
        <el-table-column
          :label="t('strategy.strategyName')"
          min-width="150"
        >
          <template #default="{ row }">
            <div class="ai-research-config-name">
              <strong>{{ row.name }}</strong>
              <span>{{ row.id }}</span>
            </div>
          </template>
        </el-table-column>
        <!-- @vue-generic {typeof aiResearchConfigProfiles.value[number]} -->
        <el-table-column
          label="标的"
          min-width="110"
        >
          <template #default="{ row }">
            {{ aiResearchConfigProfileValue(row, 'symbol') }}
          </template>
        </el-table-column>
        <!-- @vue-generic {typeof aiResearchConfigProfiles.value[number]} -->
        <el-table-column
          label="周期"
          width="76"
        >
          <template #default="{ row }">
            {{ aiResearchConfigProfileValue(row, 'timeframe') }}
          </template>
        </el-table-column>
        <!-- @vue-generic {typeof aiResearchConfigProfiles.value[number]} -->
        <el-table-column
          label="Sharpe"
          width="86"
        >
          <template #default="{ row }">
            {{ aiResearchConfigProfileMetric(row, 'target_sharpe') }}
          </template>
        </el-table-column>
        <!-- @vue-generic {typeof aiResearchConfigProfiles.value[number]} -->
        <el-table-column
          label="轮数"
          width="72"
        >
          <template #default="{ row }">
            {{ aiResearchConfigProfileMetric(row, 'max_iterations', 0) }}
          </template>
        </el-table-column>
        <!-- @vue-generic {typeof aiResearchConfigProfiles.value[number]} -->
        <el-table-column
          label="样本外"
          width="86"
        >
          <template #default="{ row }">
            {{ aiResearchConfigProfileOos(row) }}
          </template>
        </el-table-column>
        <!-- @vue-generic {typeof aiResearchConfigProfiles.value[number]} -->
        <el-table-column
          label="操作"
          width="174"
          fixed="right"
        >
          <template #default="{ row }">
            <el-button
              link
              size="small"
              type="primary"
              @click.stop="applyAIResearchConfigProfile(row)"
            >
              {{ t('strategy.aiResearchLoadConfig') }}
            </el-button>
            <el-button
              link
              size="small"
              type="warning"
              :loading="aiResearchConfigProfileSaving && aiResearchSelectedConfigProfileId === row.id"
              @click.stop="saveAIResearchConfigProfile(row.id)"
            >
              {{ t('common.save') }}
            </el-button>
            <el-button
              link
              size="small"
              type="danger"
              :loading="aiResearchConfigProfileDeletingId === row.id"
              @click.stop="deleteAIResearchConfigProfile(row)"
            >
              {{ t('common.delete') }}
            </el-button>
          </template>
        </el-table-column>
      </el-table>

      <div
        v-if="aiResearchSelectedConfigProfile"
        class="ai-research-config-detail"
        data-test="ai-research-config-detail"
      >
        <div class="ai-research-config-detail-head">
          <strong>{{ aiResearchSelectedConfigProfile.name }}</strong>
          <span>
            {{ aiResearchSelectedConfigProfile.description || '当前配置没有填写说明。' }}
          </span>
        </div>
        <div class="ai-research-config-detail-grid">
          <div
            v-for="item in aiResearchSelectedConfigDetails"
            :key="item.label"
            class="ai-research-config-detail-item"
          >
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>
        <pre
          v-if="aiResearchSelectedConfigPromptPreview"
          class="ai-research-config-prompt-preview"
        >{{ aiResearchSelectedConfigPromptPreview }}</pre>
      </div>

      <div class="ai-research-config-editor">
        <el-input
          v-model="aiResearchConfigProfileName"
          placeholder="配置名称"
          data-test="ai-research-config-name"
        />
        <el-input
          v-model="aiResearchConfigProfileDescription"
          placeholder="配置说明"
          data-test="ai-research-config-description"
        />
        <el-button
          type="primary"
          plain
          :disabled="!aiResearchSelectedConfigProfile"
          :loading="aiResearchConfigProfileSaving"
          data-test="ai-research-config-save"
          @click="saveAIResearchConfigProfile()"
        >
          <el-icon aria-hidden="true">
            <EditPen />
          </el-icon>
          保存修改
        </el-button>
        <el-button
          type="success"
          plain
          :loading="aiResearchConfigProfileSaving"
          data-test="ai-research-config-create"
          @click="createAIResearchConfigProfile"
        >
          <el-icon aria-hidden="true">
            <Plus />
          </el-icon>
          新建配置
        </el-button>
        <el-button
          type="danger"
          plain
          :disabled="!aiResearchSelectedConfigProfile"
          :loading="aiResearchConfigProfileDeletingId === aiResearchSelectedConfigProfileId"
          data-test="ai-research-config-delete"
          @click="aiResearchSelectedConfigProfile && deleteAIResearchConfigProfile(aiResearchSelectedConfigProfile)"
        >
          <el-icon aria-hidden="true">
            <Delete />
          </el-icon>
          删除配置
        </el-button>
      </div>
    </div>

    <el-form
      label-position="top"
      :model="aiResearchForm"
    >
      <el-form-item :label="t('strategy.aiResearchObjectiveMode')">
        <el-radio-group
          v-model="aiResearchForm.workflow_mode"
          data-test="ai-research-workflow-mode"
        >
          <el-radio-button value="auto">
            {{ t('strategy.aiResearchWorkflowAuto') }}
          </el-radio-button>
          <el-radio-button value="prompt">
            {{ t('strategy.aiResearchWorkflowPrompt') }}
          </el-radio-button>
        </el-radio-group>
        <p
          class="ai-research-workflow-semantics"
          data-test="ai-research-workflow-semantics"
        >
          {{ t('strategy.aiResearchWorkflowSemantics') }}
        </p>
      </el-form-item>

      <el-form-item :label="t('strategy.aiResearchPrompt')">
        <el-input
          v-model="aiResearchForm.prompt"
          type="textarea"
          :rows="5"
          :placeholder="t('strategy.aiResearchPromptPlaceholder')"
          data-test="ai-research-prompt-config"
        />
        <div class="ai-research-prompt-tools">
          <el-button
            size="small"
            type="primary"
            data-test="ai-research-generate-prompt-config"
            @click="openAIResearchPromptGenerationDialog"
          >
            <el-icon
              class="mr-1"
              aria-hidden="true"
            >
              <MagicStick />
            </el-icon>
            {{ t('strategy.aiResearchGeneratePrompt') }}
          </el-button>
        </div>
      </el-form-item>

      <div class="ai-research-form-grid">
        <el-form-item :label="t('strategy.aiResearchSymbol')">
          <el-input
            v-model="aiResearchForm.symbol"
            data-test="ai-research-symbol"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchSymbolName')">
          <el-input v-model="aiResearchForm.symbol_name" />
        </el-form-item>
        <el-form-item label="数据资产类型">
          <el-select
            v-model="aiResearchForm.market_data_asset_type"
            clearable
            placeholder="自动识别"
            class="w-full"
            data-test="ai-research-market-data-asset-type"
          >
            <el-option
              v-for="option in aiResearchMarketDataAssetTypeOptions"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="知识库 ID">
          <el-input
            v-model="aiResearchForm.knowledge_base_id"
            clearable
            placeholder="可选"
            data-test="ai-research-knowledge-base"
          />
        </el-form-item>
        <el-form-item label="生成模式">
          <el-checkbox
            v-model="aiResearchForm.thinking_mode"
            data-test="ai-research-thinking-mode"
          >
            深度思考
          </el-checkbox>
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchTimeframe')">
          <el-select
            v-model="aiResearchForm.timeframe"
            class="w-full"
          >
            <el-option
              label="1d"
              value="1d"
            />
            <el-option
              label="1h"
              value="1h"
            />
            <el-option
              label="30m"
              value="30m"
            />
            <el-option
              label="5m"
              value="5m"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchTargetSharpe')">
          <el-input-number
            v-model="aiResearchForm.target_sharpe"
            :min="-5"
            :max="10"
            :step="0.1"
            class="w-full"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchMaxIterations')">
          <el-input-number
            v-model="aiResearchForm.max_iterations"
            :min="1"
            :max="8"
            class="w-full"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchMinTrades')">
          <el-input-number
            v-model="aiResearchForm.min_total_trades"
            :min="0"
            :max="9999"
            class="w-full"
          />
        </el-form-item>
        <el-form-item label="最大回撤上限 %">
          <div class="ai-research-gate-control">
            <el-checkbox v-model="aiResearchForm.use_max_drawdown_limit" />
            <el-input-number
              v-model="aiResearchForm.max_drawdown_limit"
              :disabled="!aiResearchForm.use_max_drawdown_limit"
              :min="0"
              :max="100"
              :step="1"
              class="w-full"
              data-test="ai-research-max-drawdown"
            />
          </div>
        </el-form-item>
        <el-form-item label="最小总收益 %">
          <div class="ai-research-gate-control">
            <el-checkbox v-model="aiResearchForm.use_min_total_return" />
            <el-input-number
              v-model="aiResearchForm.min_total_return"
              :disabled="!aiResearchForm.use_min_total_return"
              :min="-100"
              :max="1000"
              :step="1"
              class="w-full"
            />
          </div>
        </el-form-item>
        <el-form-item label="最小年化收益 %">
          <div class="ai-research-gate-control">
            <el-checkbox v-model="aiResearchForm.use_min_annual_return" />
            <el-input-number
              v-model="aiResearchForm.min_annual_return"
              :disabled="!aiResearchForm.use_min_annual_return"
              :min="-100"
              :max="1000"
              :step="1"
              class="w-full"
            />
          </div>
        </el-form-item>
        <el-form-item label="最小胜率 %">
          <div class="ai-research-gate-control">
            <el-checkbox v-model="aiResearchForm.use_min_win_rate" />
            <el-input-number
              v-model="aiResearchForm.min_win_rate"
              :disabled="!aiResearchForm.use_min_win_rate"
              :min="0"
              :max="100"
              :step="1"
              class="w-full"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchInitialCash')">
          <el-input-number
            v-model="aiResearchForm.initial_cash"
            :min="1"
            :step="10000"
            class="w-full"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchCommission')">
          <div class="ai-research-gate-control">
            <el-checkbox
              v-model="aiResearchForm.use_manual_commission"
              data-test="ai-research-manual-commission"
            />
            <el-input-number
              v-model="aiResearchForm.commission"
              :disabled="!aiResearchForm.use_manual_commission"
              :min="0"
              :max="0.1"
              :step="0.0001"
              class="w-full"
              data-test="ai-research-commission"
            />
          </div>
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchAnnualDays')">
          <el-input-number
            v-model="aiResearchForm.annual_days"
            :min="1"
            :max="366"
            :step="1"
            class="w-full"
            data-test="ai-research-annual-days"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchCalcMethod')">
          <el-select
            v-model="aiResearchForm.calc_method"
            class="w-full"
            data-test="ai-research-calc-method"
          >
            <el-option
              label="simple"
              value="simple"
            />
            <el-option
              label="log"
              value="log"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchWeightMode')">
          <el-select
            v-model="aiResearchForm.weight_mode"
            class="w-full"
            data-test="ai-research-weight-mode"
          >
            <el-option
              label="equal"
              value="equal"
            />
            <el-option
              label="value"
              value="value"
            />
          </el-select>
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchGroupName')">
          <el-input
            v-model="aiResearchForm.group_name"
            data-test="ai-research-group-name"
          />
        </el-form-item>
        <el-form-item label="单轮回测超时(秒)">
          <el-input-number
            v-model="aiResearchForm.backtest_timeout_seconds"
            :min="1"
            :max="3600"
            :step="60"
            class="w-full"
            data-test="ai-research-backtest-timeout"
          />
        </el-form-item>
        <el-form-item label="回测轮询间隔(秒)">
          <el-input-number
            v-model="aiResearchForm.poll_interval_seconds"
            :min="0.1"
            :max="30"
            :step="0.5"
            class="w-full"
            data-test="ai-research-poll-interval"
          />
        </el-form-item>
        <el-form-item label="模拟工作区名称">
          <el-input
            v-model="aiResearchForm.paper_workspace_name"
            clearable
            placeholder="自动命名"
            data-test="ai-research-paper-workspace-name"
          />
        </el-form-item>
        <el-form-item label="模拟工作区 ID">
          <el-input
            v-model="aiResearchForm.trading_workspace_id"
            clearable
            placeholder="可选，复用已有模拟工作区"
            data-test="ai-research-trading-workspace-id"
          />
        </el-form-item>
        <el-form-item label="模拟网关配置 JSON">
          <el-input
            v-model="aiResearchForm.gateway_config_json"
            type="textarea"
            :rows="3"
            :placeholder="PAPER_GATEWAY_CONFIG_PLACEHOLDER"
            data-test="ai-research-gateway-config"
          />
        </el-form-item>
        <el-form-item label="实盘工作区名称">
          <el-input
            v-model="aiResearchForm.live_workspace_name"
            clearable
            placeholder="自动命名"
            data-test="ai-research-live-workspace-name"
          />
        </el-form-item>
        <el-form-item label="实盘工作区 ID">
          <el-input
            v-model="aiResearchForm.live_trading_workspace_id"
            clearable
            placeholder="可选，复用已有实盘工作区"
            data-test="ai-research-live-workspace-id"
          />
        </el-form-item>
        <el-form-item label="实盘网关配置 JSON">
          <el-input
            v-model="aiResearchForm.live_gateway_config_json"
            type="textarea"
            :rows="3"
            :placeholder="LIVE_GATEWAY_CONFIG_PLACEHOLDER"
            data-test="ai-research-live-gateway-config"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchStartDate')">
          <el-input
            v-model="aiResearchForm.start_date"
            placeholder="2020-01-01"
          />
        </el-form-item>
        <el-form-item :label="t('strategy.aiResearchEndDate')">
          <el-input
            v-model="aiResearchForm.end_date"
            placeholder="2026-01-01"
          />
        </el-form-item>
        <el-form-item label="样本外比例 %">
          <div class="ai-research-gate-control">
            <el-checkbox
              v-model="aiResearchForm.out_of_sample_validation"
              data-test="ai-research-oos-enabled"
            />
            <el-input-number
              v-model="aiResearchForm.out_of_sample_ratio_pct"
              :disabled="!aiResearchForm.out_of_sample_validation"
              :min="5"
              :max="50"
              :step="5"
              class="w-full"
              data-test="ai-research-oos-ratio"
            />
          </div>
        </el-form-item>
        <el-form-item label="晋级必须通过样本外">
          <el-checkbox
            v-model="aiResearchForm.require_out_of_sample_validation"
            :disabled="!aiResearchForm.out_of_sample_validation"
            data-test="ai-research-oos-required"
          >
            达标后先完成样本外验证
          </el-checkbox>
        </el-form-item>
        <el-form-item label="样本外最小 Sharpe">
          <div class="ai-research-gate-control">
            <el-checkbox
              v-model="aiResearchForm.use_min_out_of_sample_sharpe"
              :disabled="!aiResearchForm.out_of_sample_validation"
            />
            <el-input-number
              v-model="aiResearchForm.min_out_of_sample_sharpe"
              :disabled="
                !aiResearchForm.out_of_sample_validation
                  || !aiResearchForm.use_min_out_of_sample_sharpe
              "
              :min="-5"
              :max="10"
              :step="0.1"
              class="w-full"
              data-test="ai-research-oos-sharpe"
            />
          </div>
        </el-form-item>
        <el-form-item label="样本外最少交易">
          <div class="ai-research-gate-control">
            <el-checkbox
              v-model="aiResearchForm.use_min_out_of_sample_trades"
              :disabled="!aiResearchForm.out_of_sample_validation"
            />
            <el-input-number
              v-model="aiResearchForm.min_out_of_sample_trades"
              :disabled="
                !aiResearchForm.out_of_sample_validation
                  || !aiResearchForm.use_min_out_of_sample_trades
              "
              :min="0"
              :max="9999"
              class="w-full"
              data-test="ai-research-oos-trades"
            />
          </div>
        </el-form-item>
        <el-form-item label="数据预检">
          <div class="ai-research-precheck-control">
            <el-button
              size="small"
              :loading="aiResearchPrecheckLoading"
              data-test="ai-research-data-precheck"
              @click="() => runAIResearchDataPrecheck()"
            >
              <el-icon aria-hidden="true">
                <RefreshRight />
              </el-icon>
              运行预检
            </el-button>
            <el-button
              v-if="aiResearchMarketDataCacheFillEnabled"
              size="small"
              :loading="aiResearchCacheFillLoading"
              :disabled="aiResearchPrecheckLoading"
              data-test="ai-research-cache-fill"
              @click="() => warmAIResearchLocalCache()"
            >
              补齐本地缓存
            </el-button>
            <el-tag
              v-if="aiResearchPrecheckResult || aiResearchPrecheckError"
              size="small"
              :type="aiResearchPrecheckTagType"
            >
              {{ aiResearchPrecheckSummary }}
            </el-tag>
            <el-tag
              v-if="(aiResearchMarketDataPlatformBridgeEnabled || aiResearchMarketDataCacheFillEnabled) && (aiResearchPrecheckResult || aiResearchPrecheckError || aiResearchMarketDataPlatformStatus.path !== 'legacy')"
              size="small"
              data-test="ai-research-data-platform-status"
              :type="aiResearchMarketDataPlatformTagType"
            >
              {{ aiResearchMarketDataPlatformSummary }}
            </el-tag>
          </div>
          <p
            v-if="aiResearchMarketDataPlatformBridgeEnabled || aiResearchMarketDataCacheFillEnabled"
            class="text-gray-500"
            data-test="ai-research-cache-fill-boundary"
          >
            补齐仅保存可审计的本地市场数据，不会自动成为回测工件；严格/PIT 回测绑定须由服务端另行启用。
          </p>
          <div
            v-if="aiResearchPrecheckResult?.gate_evaluations?.length"
            class="ai-research-precheck-issues"
            data-test="ai-research-precheck-issues"
          >
            <div
              v-for="issue in aiResearchPrecheckResult.gate_evaluations.filter(item => !item.passed)"
              :key="issue.key"
              class="ai-research-precheck-issue"
            >
              <el-tag
                size="small"
                :type="issue.severity === 'error' ? 'danger' : 'warning'"
              >
                {{ issue.severity === 'error' ? '阻断' : '提示' }}
              </el-tag>
              <span>{{ issue.message || issue.label }}</span>
            </div>
          </div>
        </el-form-item>
        <el-form-item label="稳健性验证">
          <div class="ai-research-gate-control">
            <el-checkbox
              v-model="aiResearchForm.robustness_validation"
              data-test="ai-research-robustness-enabled"
            />
            <el-input-number
              v-model="aiResearchForm.min_robustness_score"
              :disabled="!aiResearchForm.robustness_validation"
              :min="0"
              :max="100"
              :step="5"
              class="w-full"
              data-test="ai-research-robustness-score"
            />
          </div>
        </el-form-item>
        <el-form-item label="晋级必须通过稳健性">
          <el-checkbox
            v-model="aiResearchForm.require_robustness_validation"
            :disabled="!aiResearchForm.robustness_validation"
            data-test="ai-research-robustness-required"
          >
            达标后先完成稳健性验证
          </el-checkbox>
        </el-form-item>
        <el-form-item label="稳健性方法">
          <el-checkbox-group
            v-model="aiResearchForm.robustness_methods"
            :disabled="!aiResearchForm.robustness_validation"
          >
            <el-checkbox label="monte_carlo">
              Monte Carlo
            </el-checkbox>
            <el-checkbox label="parameter_sensitivity">
              参数扰动
            </el-checkbox>
            <el-checkbox label="walk_forward">
              Walk Forward
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="Monte Carlo 次数">
          <el-input-number
            v-model="aiResearchForm.robustness_monte_carlo_iterations"
            :disabled="!aiResearchForm.robustness_validation"
            :min="50"
            :max="5000"
            :step="50"
            class="w-full"
          />
        </el-form-item>
        <el-form-item label="最少模拟观察天数">
          <el-input-number
            v-model="aiResearchForm.min_paper_trading_days"
            :min="0"
            :max="365"
            :step="1"
            class="w-full"
            data-test="ai-research-min-paper-days"
          />
        </el-form-item>
      </div>
    </el-form>
  </el-dialog>
</template>

<script setup lang="ts">
import { Delete, EditPen, MagicStick, Plus, RefreshRight, Upload } from '@element-plus/icons-vue'
import { useStrategyPageContext } from '../strategy/strategyPageContext'

const {
  t,
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
  aiResearchPrecheckLoading,
  aiResearchCacheFillLoading,
  aiResearchPrecheckResult,
  aiResearchPrecheckError,
  aiResearchMarketDataPlatformStatus,
  aiResearchMarketDataPlatformBridgeEnabled,
  aiResearchMarketDataCacheFillEnabled,
  PAPER_GATEWAY_CONFIG_PLACEHOLDER,
  LIVE_GATEWAY_CONFIG_PLACEHOLDER,
  aiResearchForm,
  aiResearchMarketDataAssetTypeOptions,
  aiResearchPrecheckTagType,
  aiResearchPrecheckSummary,
  aiResearchMarketDataPlatformTagType,
  aiResearchMarketDataPlatformSummary,
  aiResearchSelectedConfigProfile,
  aiResearchSelectedConfigDetails,
  aiResearchSelectedConfigPromptPreview,
  runAIResearchDataPrecheck,
  warmAIResearchLocalCache,
  openAIResearchPromptGenerationDialog,
  applyAIResearchConfigProfile,
  aiResearchConfigProfileValue,
  aiResearchConfigProfileMetric,
  aiResearchConfigProfileOos,
  loadAIResearchConfigProfiles,
  createAIResearchConfigProfile,
  saveAIResearchConfigProfile,
  deleteAIResearchConfigProfile,
  triggerAIResearchConfigProfileImport,
  importAIResearchConfigProfileFile,
} = useStrategyPageContext()
</script>

<style scoped src="../StrategyPage.css" />
