<template>
  <section class="ai-research-panel ai-research-control-panel">
    <div class="ai-research-panel-head">
      <span class="ai-research-kicker">{{ t('strategy.aiResearchControlKicker') }}</span>
      <h2>{{ t('strategy.aiResearchControlTitle') }}</h2>
      <p>{{ t('strategy.aiResearchControlSubtitle') }}</p>
    </div>

    <div
      class="ai-research-plan-bar"
      data-test="ai-research-plan-bar"
    >
      <div class="ai-research-plan-select">
        <span>{{ t('strategy.aiResearchPlan') }}</span>
        <el-select
          v-model="aiResearchSelectedConfigProfileId"
          class="w-full"
          filterable
          :disabled="aiResearchRunning"
          :loading="aiResearchConfigProfilesLoading"
          :placeholder="t('strategy.aiResearchSelectConfig')"
          data-test="ai-research-profile-select"
          @change="selectAIResearchConfigProfile"
        >
          <el-option
            v-for="profile in aiResearchConfigProfiles"
            :key="profile.id"
            :label="profile.name"
            :value="profile.id"
          >
            <span>{{ profile.name }}</span>
            <span class="ai-research-plan-option">
              {{ aiResearchConfigProfileValue(profile, 'symbol') }}
              · {{ aiResearchConfigProfileValue(profile, 'timeframe') }}
            </span>
          </el-option>
        </el-select>
      </div>
      <div class="ai-research-plan-summary">
        <strong>{{ aiResearchSelectedProfileSummary }}</strong>
        <span>
          {{ aiResearchSelectedConfigProfile?.description || t('strategy.aiResearchConfigDescription') }}
        </span>
      </div>
      <el-button
        type="primary"
        plain
        data-test="ai-research-config-open"
        @click="openAIResearchConfigDialog"
      >
        <el-icon aria-hidden="true">
          <EditPen />
        </el-icon>
        {{ t('strategy.aiResearchConfigurePlan') }}
      </el-button>
    </div>

    <AIResearchConfigDialog />

    <el-form
      label-position="top"
      :model="aiResearchForm"
      class="ai-research-main-form"
    >
      <el-form-item :label="t('strategy.aiResearchPrompt')">
        <el-input
          v-model="aiResearchForm.prompt"
          type="textarea"
          :rows="7"
          :placeholder="t('strategy.aiResearchPromptPlaceholder')"
          data-test="ai-research-prompt"
        />
        <div class="ai-research-prompt-tools">
          <el-button
            size="small"
            type="primary"
            data-test="ai-research-generate-prompt"
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
    </el-form>

    <div
      class="ai-research-mandate"
      data-test="ai-research-mandate"
    >
      <div class="ai-research-mandate-head">
        <div>
          <span class="ai-research-kicker">投资需求</span>
          <strong>{{ aiResearchMandate?.objective || '待确认' }}</strong>
        </div>
        <el-tag
          size="small"
          :type="aiResearchMandateConfirmed ? 'success' : 'warning'"
        >
          {{ aiResearchMandateConfirmed ? '已确认' : '待确认' }}
        </el-tag>
      </div>
      <div class="ai-research-mandate-actions">
        <el-button
          size="small"
          plain
          :loading="aiResearchMandateLoading"
          data-test="ai-research-parse-mandate"
          @click="parseAIResearchMandate()"
        >
          解析需求
        </el-button>
        <el-button
          size="small"
          type="primary"
          :disabled="!aiResearchMandate"
          data-test="ai-research-confirm-mandate"
          @click="confirmAIResearchMandate"
        >
          确认需求
        </el-button>
      </div>
      <div
        v-if="aiResearchMandate"
        class="ai-research-mandate-grid"
      >
        <span
          v-for="item in aiResearchMandateDetails"
          :key="item.key"
        >
          <small>{{ item.label }}</small>
          <strong>{{ item.value }}</strong>
        </span>
      </div>
    </div>

    <div class="ai-research-actions">
      <div class="ai-research-action-options">
        <el-checkbox v-model="aiResearchForm.start_paper_trading">
          {{ t('strategy.aiResearchPaper') }}
        </el-checkbox>
        <el-tag
          v-if="aiResearchContinuationEnabled"
          closable
          type="info"
          @close="clearAIResearchContinuation"
        >
          {{ aiResearchContinuationLabel }}
        </el-tag>
      </div>
      <p
        v-if="aiResearchStrictMarketDataRunBlocked"
        class="text-sm text-red-600"
        data-test="ai-research-strict-market-data-block"
        role="alert"
      >
        {{ aiResearchStrictMarketDataRunBlockReason }}
      </p>
      <el-button
        type="primary"
        :loading="aiResearchRunning"
        :disabled="aiResearchStrictMarketDataRunBlocked"
        data-test="ai-research-run"
        @click="runAIResearchLoop"
      >
        <el-icon
          class="mr-1"
          aria-hidden="true"
        >
          <MagicStick />
        </el-icon>
        {{ aiResearchRunning ? t('strategy.aiResearchRunning') : t('strategy.aiResearchRun') }}
      </el-button>
      <el-button
        v-if="canCancelAIResearchTask"
        data-test="ai-research-cancel"
        :loading="aiResearchCancelling"
        @click="cancelAIResearchTask"
      >
        取消任务
      </el-button>
      <el-button
        v-if="canContinueAIResearchTask"
        type="warning"
        plain
        data-test="ai-research-continue-task"
        :loading="aiResearchRunning"
        @click="continueAIResearchFromTaskSnapshot"
      >
        从任务继续
      </el-button>
      <el-button
        v-if="canRetryAIResearchTask"
        type="warning"
        plain
        data-test="ai-research-retry-task"
        :loading="aiResearchRunning"
        @click="retryAIResearchFromTaskSnapshot"
      >
        重新启动任务
      </el-button>
      <el-tag
        v-if="aiResearchTaskId"
        size="small"
        type="info"
      >
        任务 {{ aiResearchTaskStageLabel }}
        {{ formatTaskProgress(aiResearchTaskProgress) }}
        <template v-if="aiResearchTaskIteration">
          {{ t('strategy.aiResearchTaskIterationLabel', { iteration: aiResearchTaskIteration }) }}
        </template>
        <template v-if="aiResearchBacktestTaskId">
          {{ t('strategy.aiResearchBacktestTaskLabel', { taskId: aiResearchBacktestTaskId }) }}
        </template>
        <template v-else-if="aiResearchCancelledBacktestTaskId">
          {{ t('strategy.aiResearchCancelledBacktestTaskLabel', { taskId: aiResearchCancelledBacktestTaskId }) }}
        </template>
      </el-tag>
    </div>
    <div
      v-if="aiResearchTaskId"
      class="ai-research-task-progress"
      data-test="ai-research-task-progress"
    >
      <strong>任务进度</strong>
      <span
        v-if="aiResearchTaskContinuationSummary"
        data-test="ai-research-task-continuation"
      >
        继续来源 {{ aiResearchTaskContinuationSummary }}
      </span>
      <span>阶段 {{ aiResearchTaskStageLabel }}</span>
      <span>{{ formatTaskProgress(aiResearchTaskProgress) }}</span>
      <span v-if="aiResearchTaskIteration">第 {{ aiResearchTaskIteration }} 轮</span>
      <span v-if="aiResearchBacktestTaskId">回测 {{ aiResearchBacktestTaskId }}</span>
      <span v-else-if="aiResearchCancelledBacktestTaskId">
        已取消回测 {{ aiResearchCancelledBacktestTaskId }}
      </span>
      <span v-if="aiResearchTaskPaperStatusText">{{ aiResearchTaskPaperStatusText }}</span>
      <span v-if="aiResearchTaskPaperUnitId">模拟单元 {{ aiResearchTaskPaperUnitId }}</span>
      <span v-if="aiResearchTaskLiveStatusText">{{ aiResearchTaskLiveStatusText }}</span>
      <span v-if="aiResearchTaskLiveUnitId">实盘单元 {{ aiResearchTaskLiveUnitId }}</span>
      <span v-if="aiResearchTaskMessage">{{ aiResearchTaskMessage }}</span>
      <span v-if="aiResearchTaskLatestIteration">
        最近{{ taskLatestIterationLabel(aiResearchTaskLatestIteration) }}
        Sharpe {{ formatMetric(taskLatestIterationMetric(aiResearchTaskLatestIteration, 'sharpe_ratio', 'sharpe')) }}
        交易 {{ formatMetric(taskLatestIterationMetric(aiResearchTaskLatestIteration, 'total_trades', 'trades')) }}
      </span>
      <span
        v-if="aiResearchTaskBestIterationDisplay"
        data-test="ai-research-task-best-iteration"
      >
        当前最佳{{ taskLatestIterationLabel(aiResearchTaskBestIterationDisplay) }}
        Sharpe {{ formatMetric(taskLatestIterationMetric(aiResearchTaskBestIterationDisplay, 'sharpe_ratio', 'sharpe')) }}
        交易 {{ formatMetric(taskLatestIterationMetric(aiResearchTaskBestIterationDisplay, 'total_trades', 'trades')) }}
      </span>
      <span
        v-if="taskLatestIterationProgress(aiResearchTaskLatestIteration)"
        class="ai-research-task-iteration-progress"
        data-test="ai-research-task-iteration-progress"
      >
        <el-tag
          size="small"
          :type="iterationProgressTagType(taskLatestIterationProgress(aiResearchTaskLatestIteration)?.status)"
        >
          {{ iterationProgressLabel(taskLatestIterationProgress(aiResearchTaskLatestIteration)?.status) }}
        </el-tag>
        <template v-if="taskLatestIterationProgress(aiResearchTaskLatestIteration)?.previous_iteration">
          {{ t('strategy.aiResearchCompareIteration', { iteration: taskLatestIterationProgress(aiResearchTaskLatestIteration)?.previous_iteration }) }}
        </template>
        <template v-if="iterationProgressDeltaText(taskLatestIterationProgress(aiResearchTaskLatestIteration), 'sharpe_delta')">
          Sharpe {{ iterationProgressDeltaText(taskLatestIterationProgress(aiResearchTaskLatestIteration), 'sharpe_delta') }}
        </template>
      </span>
      <span
        v-if="aiResearchTaskLatestDiagnostics"
        class="ai-research-task-diagnostics"
        data-test="ai-research-task-latest-diagnostics"
      >
        <strong>最近诊断</strong>
        <span v-if="aiResearchTaskLatestDiagnostics.summary">
          {{ aiResearchTaskLatestDiagnostics.summary }}
        </span>
        <span v-if="aiResearchTaskLatestDiagnostics.generationText">
          {{ aiResearchTaskLatestDiagnostics.generationText }}
        </span>
        <span
          v-for="gap in aiResearchTaskLatestDiagnostics.gateGaps"
          :key="`task-gap-${gap.key || gap.label}`"
          class="ai-research-warning-text"
        >
          差距 {{ gateGapText(gap) }}
        </span>
        <span
          v-for="failure in aiResearchTaskLatestDiagnostics.failures"
          :key="`task-failure-${failure}`"
          class="ai-research-warning-text"
        >
          {{ failure }}
        </span>
        <span
          v-for="plan in aiResearchTaskLatestDiagnostics.improvementPlan"
          :key="`task-plan-${plan}`"
        >
          改稿 {{ plan }}
        </span>
        <span
          v-for="action in aiResearchTaskLatestDiagnostics.nextActions"
          :key="`task-action-${action}`"
        >
          下一步 {{ action }}
        </span>
      </span>
      <span
        v-if="aiResearchTaskPipelineSteps.length"
        class="ai-research-task-pipeline"
        data-test="ai-research-task-pipeline"
      >
        <span
          v-for="step in aiResearchTaskPipelineSteps"
          :key="step.key"
        >
          {{ step.label || aiResearchStageLabel(step.key) }}
          {{ pipelineStepStatusLabel(step.status) }}
          <template v-if="pipelineStepDetailText(step, aiResearchTaskPipeline)">
            {{ pipelineStepDetailText(step, aiResearchTaskPipeline) }}
          </template>
        </span>
      </span>
      <span
        v-if="aiResearchTaskPromotionAudit.length"
        class="ai-research-task-promotion-audit"
        data-test="ai-research-task-promotion-audit"
      >
        <strong>晋级审计</strong>
        <span
          v-for="item in aiResearchTaskPromotionAudit"
          :key="item.key"
        >
          {{ item.label }} {{ pipelineStepStatusLabel(item.status) }}
          <template v-if="item.evidence">
            {{ item.evidence }}
          </template>
        </span>
      </span>
    </div>
    <div
      v-if="aiResearchTaskError"
      class="ai-research-task-error"
      data-test="ai-research-task-error"
    >
      <strong>任务异常</strong>
      <span>{{ aiResearchTaskError }}</span>
    </div>
  </section>
</template>

<script setup lang="ts">
import { EditPen, MagicStick } from '@element-plus/icons-vue'
import AIResearchConfigDialog from './AIResearchConfigDialog.vue'
import { useStrategyPageContext } from '../strategy/strategyPageContext'

const {
  t,
  aiResearchRunning,
  aiResearchTaskId,
  aiResearchTaskProgress,
  aiResearchTaskIteration,
  aiResearchBacktestTaskId,
  aiResearchCancelledBacktestTaskId,
  aiResearchTaskPaperUnitId,
  aiResearchTaskLiveUnitId,
  aiResearchTaskPipeline,
  aiResearchTaskError,
  aiResearchTaskMessage,
  aiResearchTaskLatestIteration,
  aiResearchTaskPromotionAudit,
  aiResearchCancelling,
  aiResearchConfigProfiles,
  aiResearchConfigProfilesLoading,
  aiResearchSelectedConfigProfileId,
  aiResearchMandate,
  aiResearchMandateConfirmed,
  aiResearchMandateLoading,
  aiResearchStrictMarketDataRunBlocked,
  aiResearchStrictMarketDataRunBlockReason,
  aiResearchForm,
  aiResearchSelectedConfigProfile,
  aiResearchSelectedProfileSummary,
  aiResearchMandateDetails,
  aiResearchTaskStageLabel,
  aiResearchTaskContinuationSummary,
  aiResearchTaskPaperStatusText,
  aiResearchTaskLiveStatusText,
  aiResearchTaskPipelineSteps,
  aiResearchTaskLatestDiagnostics,
  aiResearchTaskBestIterationDisplay,
  aiResearchContinuationEnabled,
  aiResearchContinuationLabel,
  canCancelAIResearchTask,
  canContinueAIResearchTask,
  canRetryAIResearchTask,
  formatMetric,
  gateGapText,
  formatTaskProgress,
  taskLatestIterationLabel,
  taskLatestIterationMetric,
  taskLatestIterationProgress,
  openAIResearchPromptGenerationDialog,
  parseAIResearchMandate,
  confirmAIResearchMandate,
  openAIResearchConfigDialog,
  selectAIResearchConfigProfile,
  aiResearchConfigProfileValue,
  iterationProgressLabel,
  iterationProgressTagType,
  iterationProgressDeltaText,
  pipelineStepStatusLabel,
  pipelineStepDetailText,
  aiResearchStageLabel,
  clearAIResearchContinuation,
  cancelAIResearchTask,
  continueAIResearchFromTaskSnapshot,
  retryAIResearchFromTaskSnapshot,
  runAIResearchLoop,
} = useStrategyPageContext()
</script>

<style scoped src="../StrategyPage.css" />
