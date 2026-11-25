<template>
  <section class="ai-research-panel ai-research-result">
    <div class="ai-research-panel-head">
      <span class="ai-research-kicker">{{ t('strategy.aiResearchResultKicker') }}</span>
      <h2>{{ t('strategy.aiResearchResultTitle') }}</h2>
      <p>{{ t('strategy.aiResearchResultSubtitle') }}</p>
    </div>
    <div
      v-if="aiResearchOutputConfigProfile"
      class="ai-research-result-context"
      data-test="ai-research-result-context"
    >
      <strong>当前方案 {{ aiResearchOutputConfigProfile.name }}</strong>
      <span>{{ aiResearchOutputProfileSummary }}</span>
    </div>
    <div
      v-if="aiResearchResult"
      data-test="ai-research-result"
    >
      <div class="ai-research-summary">
        <div>
          <span class="ai-research-kicker">{{ t('strategy.aiResearchResult') }}</span>
          <h2 class="ai-research-title">
            {{ aiResearchResult.achieved ? t('strategy.aiResearchAchieved') : t('strategy.aiResearchNotAchieved') }}
          </h2>
        </div>
        <el-tag :type="aiResearchResult.achieved ? 'success' : 'warning'">
          {{ aiResearchResult.status }}
        </el-tag>
      </div>

      <div class="ai-research-metrics">
        <div>
          <span>{{ t('strategy.aiResearchBestSharpe') }}</span>
          <strong>{{ formatMetric(aiBestSharpe) }}</strong>
        </div>
        <div>
          <span>质量分</span>
          <strong>{{ formatMetric(aiResearchResult.best_quality_score) }}</strong>
        </div>
        <div>
          <span>{{ t('strategy.aiResearchBestIteration') }}</span>
          <strong>{{ aiResearchResult.best_iteration ?? '-' }}</strong>
        </div>
        <div>
          <span>{{ t('strategy.aiResearchIterations') }}</span>
          <strong>{{ aiResearchResult.iterations.length }}</strong>
        </div>
        <div>
          <span>{{ t('strategy.aiResearchPaperStatus') }}</span>
          <strong>
            {{ aiResearchPaperStatusText }}
          </strong>
        </div>
        <div
          v-if="aiResearchCurrentContinuationSummary"
          data-test="ai-research-current-continuation"
        >
          <span>继续来源</span>
          <strong>{{ aiResearchCurrentContinuationSummary }}</strong>
        </div>
      </div>

      <div class="ai-research-links">
        <el-button
          v-if="canViewBestStrategyFromCurrentResult"
          size="small"
          :loading="aiResearchStrategyViewingRunId === aiResearchResult.run_id"
          data-test="ai-research-view-best-strategy"
          @click="viewBestStrategyFromCurrentResult"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <Link />
          </el-icon>
          查看最佳脚本
        </el-button>
        <el-button
          size="small"
          @click="openResearchWorkspace"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <Link />
          </el-icon>
          {{ t('strategy.aiResearchOpenResearch') }}
        </el-button>
        <el-button
          v-if="canStartPaperFromCurrentResult"
          size="small"
          type="success"
          :loading="aiResearchPaperStartingRunId === aiResearchResult.run_id"
          data-test="ai-research-current-start-paper"
          @click="startPaperFromCurrentResult"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <VideoPlay />
          </el-icon>
          {{
            aiResearchCurrentPaperTargetMissing
              ? '重启模拟'
              : aiResearchCurrentPaperFailed ? '重试模拟' : '启动模拟'
          }}
        </el-button>
        <el-button
          v-if="canOpenPaperFromCurrentResult"
          size="small"
          type="success"
          data-test="ai-research-current-open-paper"
          @click="openPaperWorkspace"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <VideoPlay />
          </el-icon>
          {{ t('strategy.aiResearchOpenPaper') }}
        </el-button>
        <el-button
          v-if="canReviewPaperFromCurrentResult"
          size="small"
          type="primary"
          plain
          :loading="aiResearchPaperReviewingRunId === aiResearchResult.run_id"
          data-test="ai-research-current-review-paper"
          @click="reviewPaperFromCurrentResult"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <MagicStick />
          </el-icon>
          复核模拟
        </el-button>
        <el-button
          v-if="canBuildLiveHandoffFromCurrentResult"
          size="small"
          type="success"
          plain
          :loading="aiResearchLiveHandoffLoadingRunId === aiResearchResult.run_id"
          data-test="ai-research-current-live-handoff-button"
          @click="buildLiveHandoffFromCurrentResult"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <Link />
          </el-icon>
          实盘交接包
        </el-button>
        <el-button
          v-if="canContinueResearchFromCurrentRunRecord"
          size="small"
          type="warning"
          plain
          :loading="aiResearchRunning && aiResearchForm.continue_from_run_id === aiResearchResult.run_id"
          data-test="ai-research-current-continue-run"
          @click="continueResearchFromCurrentRunRecord"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <MagicStick />
          </el-icon>
          继续投研
        </el-button>
        <el-button
          v-if="canContinueResearchFromCurrentPaperIssue && !aiResearchCurrentPaperReview"
          size="small"
          type="warning"
          plain
          :loading="aiResearchRunning && aiResearchForm.continue_from_run_id === aiResearchResult.run_id"
          data-test="ai-research-current-continue-paper-issue"
          @click="continueResearchFromCurrentPaperReview"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <MagicStick />
          </el-icon>
          继续改进
        </el-button>
      </div>

      <AIResearchLiveHandoffCard />

      <div
        v-if="aiResearchPipelineSteps.length"
        class="ai-research-pipeline"
        data-test="ai-research-pipeline"
      >
        <strong>AI投研流水线</strong>
        <div class="ai-research-pipeline-steps">
          <span
            v-for="step in aiResearchPipelineSteps"
            :key="step.key"
            class="ai-research-pipeline-step"
          >
            <span>{{ step.label || aiResearchStageLabel(step.key) }}</span>
            <el-tag
              size="small"
              :type="pipelineStepTagType(step.status)"
            >
              {{ pipelineStepStatusLabel(step.status) }}
            </el-tag>
            <small v-if="pipelineStepDetailText(step, aiResearchResult.pipeline)">
              {{ pipelineStepDetailText(step, aiResearchResult.pipeline) }}
            </small>
            <small
              v-if="step.error"
              class="ai-research-warning-text"
            >
              {{ step.error }}
            </small>
          </span>
        </div>
      </div>

      <div
        class="ai-research-timeline"
        data-test="ai-research-timeline"
      >
        <div class="ai-research-section-head">
          <strong>投研时间线</strong>
          <el-tag
            size="small"
            type="info"
          >
            {{ aiResearchTimeline.length }}
          </el-tag>
        </div>
        <div
          v-if="aiResearchTimelineLoading"
          class="ai-research-history-empty"
        >
          {{ t('common.loading') }}
        </div>
        <el-timeline v-else-if="aiResearchTimeline.length">
          <el-timeline-item
            v-for="event in aiResearchTimeline"
            :key="event.id"
            :timestamp="formatDateTime(event.created_at)"
            placement="top"
          >
            <div class="ai-research-timeline-item">
              <div>
                <strong>{{ aiResearchStageLabel(event.stage) }}</strong>
                <el-tag
                  size="small"
                  :type="aiResearchEventTagType(event.status)"
                >
                  {{ pipelineStepStatusLabel(event.status) || event.status }}
                </el-tag>
                <span v-if="event.iteration">第 {{ event.iteration }} 轮</span>
              </div>
              <p v-if="event.summary">
                {{ event.summary }}
              </p>
              <span
                v-if="event.error"
                class="ai-research-warning-text"
              >
                {{ event.error }}
              </span>
            </div>
          </el-timeline-item>
        </el-timeline>
        <div
          v-else
          class="ai-research-history-empty"
        >
          暂无时间线记录
        </div>
      </div>

      <div
        class="ai-research-versions"
        data-test="ai-research-versions"
      >
        <div class="ai-research-section-head">
          <strong>策略版本</strong>
          <div class="ai-research-version-compare-tools">
            <el-select
              v-model="aiResearchSelectedVersionIds"
              multiple
              collapse-tags
              collapse-tags-tooltip
              :multiple-limit="2"
              size="small"
              placeholder="选择两个版本"
            >
              <el-option
                v-for="version in aiResearchVersions"
                :key="version.id"
                :label="`${version.version_name} · ${version.strategy_name || '策略'}`"
                :value="version.id"
              />
            </el-select>
            <el-button
              size="small"
              plain
              :disabled="!aiResearchCanCompareVersions"
              :loading="aiResearchVersionCompareLoading"
              data-test="ai-research-compare-versions"
              @click="compareSelectedAIResearchVersions"
            >
              对比版本
            </el-button>
          </div>
        </div>
        <el-table
          v-loading="aiResearchVersionsLoading"
          :data="aiResearchVersions"
          size="small"
          class="ai-research-version-table"
          :empty-text="'暂无版本记录'"
        >
          <el-table-column
            prop="version_name"
            label="版本"
            width="90"
          />
          <el-table-column
            label="修改原因"
            min-width="240"
          >
            <template #default="{ row }">
              <span>{{ row.ai_rationale || row.change_summary || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column
            label="质量"
            width="100"
          >
            <template #default="{ row }">
              <el-tag
                size="small"
                :type="aiResearchVersionStatusTagType(row.quality_gate_status)"
              >
                {{ row.quality_gate_status }}
              </el-tag>
            </template>
          </el-table-column>
          <!-- @vue-generic {typeof aiResearchVersions.value[number]} -->
          <el-table-column
            label="指标"
            min-width="240"
          >
            <template #default="{ row }">
              <span class="ai-research-version-metrics">
                <span
                  v-for="key in aiResearchVersionMetricKeys"
                  :key="key"
                >
                  {{ aiResearchVersionMetricLabel(key) }}
                  {{ aiResearchVersionMetric(row, key) }}
                </span>
              </span>
            </template>
          </el-table-column>
          <!-- @vue-generic {typeof aiResearchVersions.value[number]} -->
          <el-table-column
            label="操作"
            width="110"
          >
            <template #default="{ row }">
              <el-button
                size="small"
                link
                data-test="ai-research-view-version-code"
                @click="viewAIResearchVersionCode(row)"
              >
                {{ t('strategy.aiResearchViewCode') }}
              </el-button>
            </template>
          </el-table-column>
        </el-table>
        <div
          v-if="aiResearchVersionCompare"
          class="ai-research-version-compare"
          data-test="ai-research-version-compare"
        >
          <strong>{{ aiResearchVersionCompare.summary }}</strong>
          <div
            v-if="aiResearchVersionComparisonRows.length"
            class="ai-research-version-delta-table"
          >
            <div
              v-for="row in aiResearchVersionComparisonRows"
              :key="`${row.scope}-${row.key}`"
              class="ai-research-version-delta-row"
              data-test="ai-research-version-delta-row"
            >
              <span>{{ row.scope === 'metric' ? '指标' : '门控' }} · {{ row.label }}</span>
              <span>左 {{ row.left }}</span>
              <span>右 {{ row.right }}</span>
              <span>变化 {{ row.delta }}</span>
              <span>{{ row.operator }}</span>
              <el-tag
                v-if="row.passed !== null"
                size="small"
                :type="row.passed ? 'success' : 'danger'"
              >
                {{ row.passed ? '通过' : '未通过' }}
              </el-tag>
            </div>
          </div>
          <pre v-if="aiResearchVersionCompare.code_diff">{{ aiResearchVersionCompare.code_diff }}</pre>
        </div>
      </div>

      <div
        v-if="aiResearchPromotionAudit.length"
        class="ai-research-promotion-audit"
        data-test="ai-research-promotion-audit"
      >
        <strong>晋级审计</strong>
        <div class="ai-research-promotion-audit-items">
          <span
            v-for="item in aiResearchPromotionAudit"
            :key="item.key"
            class="ai-research-promotion-audit-item"
          >
            <span>{{ item.label }}</span>
            <el-tag
              size="small"
              :type="pipelineStepTagType(item.status)"
            >
              {{ pipelineStepStatusLabel(item.status) }}
            </el-tag>
            <small>{{ item.evidence }}</small>
            <small
              v-if="item.action"
              class="ai-research-muted-text"
            >
              {{ item.action }}
            </small>
          </span>
        </div>
      </div>

      <div
        v-if="aiResearchNextActions.length"
        class="ai-research-action-plan"
        data-test="ai-research-next-actions"
      >
        <strong>下一步动作</strong>
        <ul>
          <li
            v-for="action in aiResearchNextActions"
            :key="action"
          >
            {{ action }}
          </li>
        </ul>
      </div>

      <div
        v-if="aiResearchBestDiagnostics"
        class="ai-research-diagnostics"
        data-test="ai-research-best-diagnostics"
      >
        <div class="ai-research-diagnostics-head">
          <strong>投研诊断</strong>
          <el-tag
            v-if="aiResearchBestDiagnostics.promotionReady !== null"
            size="small"
            :type="aiResearchBestDiagnostics.promotionReady ? 'success' : 'warning'"
          >
            {{ aiResearchBestDiagnostics.promotionReady ? '可晋级' : '需改进' }}
          </el-tag>
        </div>
        <p v-if="aiResearchBestDiagnostics.summary">
          {{ aiResearchBestDiagnostics.summary }}
        </p>
        <div class="ai-research-diagnostics-items">
          <span v-if="aiResearchBestDiagnostics.generationText">
            {{ aiResearchBestDiagnostics.generationText }}
          </span>
          <span
            v-for="category in aiResearchBestDiagnostics.failureCategories"
            :key="`category-${category}`"
          >
            问题 {{ category }}
          </span>
          <span
            v-for="weakness in aiResearchBestDiagnostics.weaknesses"
            :key="`weakness-${weakness}`"
            class="ai-research-warning-text"
          >
            {{ weakness }}
          </span>
          <span
            v-for="gap in aiResearchBestDiagnostics.gateGaps"
            :key="`best-gap-${gap.key || gap.label}`"
            class="ai-research-warning-text"
          >
            差距 {{ gateGapText(gap) }}
          </span>
          <span
            v-for="strength in aiResearchBestDiagnostics.strengths"
            :key="`strength-${strength}`"
          >
            {{ strength }}
          </span>
          <span
            v-for="plan in aiResearchBestDiagnostics.improvementPlan"
            :key="`plan-${plan}`"
          >
            {{ plan }}
          </span>
        </div>
      </div>

      <div
        v-if="aiResearchBestGateEvaluations.length"
        class="ai-research-gate-summary"
        data-test="ai-research-gate-summary"
      >
        <span
          v-for="gate in aiResearchBestGateEvaluations"
          :key="gate.key"
          class="ai-research-gate-summary-item"
        >
          <el-tag
            size="small"
            :type="gate.passed ? 'success' : 'warning'"
          >
            {{ gate.label }}
          </el-tag>
          <span>{{ formatMetric(gate.actual) }} / {{ formatMetric(gate.target) }}</span>
        </span>
      </div>

      <div
        v-if="aiResearchOutOfSampleValidation"
        class="ai-research-oos-summary"
        data-test="ai-research-oos-summary"
      >
        <div class="ai-research-oos-head">
          <strong>样本外验证</strong>
          <el-tag
            size="small"
            :type="outOfSampleTagType(aiResearchOutOfSampleValidation.status)"
          >
            {{ outOfSampleStatusLabel(aiResearchOutOfSampleValidation.status) }}
          </el-tag>
        </div>
        <div class="ai-research-oos-details">
          <span v-if="formatOutOfSampleWindow(aiResearchOutOfSampleValidation.window)">
            {{ formatOutOfSampleWindow(aiResearchOutOfSampleValidation.window) }}
          </span>
          <span
            v-for="gate in aiResearchOutOfSampleValidation.gate_evaluations || []"
            :key="gate.key"
          >
            {{ gate.label }} {{ formatMetric(gate.actual) }} / {{ formatMetric(gate.target) }}
          </span>
          <span
            v-for="failure in aiResearchOutOfSampleValidation.failures || []"
            :key="failure"
            class="ai-research-warning-text"
          >
            {{ failure }}
          </span>
        </div>
      </div>

      <div class="ai-research-iterations">
        <div
          v-for="item in aiResearchResult.iterations"
          :key="item.iteration"
          class="ai-research-iteration"
        >
          <div class="ai-research-iteration-head">
            <strong>{{ t('strategy.aiResearchIteration') }} {{ item.iteration }}</strong>
            <span class="ai-research-iteration-actions">
              <el-button
                size="small"
                data-test="ai-research-view-iteration-strategy"
                @click="viewResearchIterationStrategy(item)"
              >
                查看脚本
              </el-button>
              <el-tag
                size="small"
                :type="item.passed ? 'success' : 'info'"
              >
                {{ item.unit_status?.run_status || item.run_result.status }}
              </el-tag>
            </span>
          </div>
          <div class="ai-research-iteration-metrics">
            <span>{{ t('strategy.aiResearchStrategy') }}: {{ item.strategy.name }}</span>
            <span>{{ t('strategy.aiResearchSharpe') }}: {{ formatMetric(item.sharpe_ratio) }}</span>
            <span>质量分: {{ formatMetric(item.quality_score) }}</span>
            <span>{{ t('strategy.aiResearchTrades') }}: {{ item.total_trades }}</span>
          </div>
          <div
            v-if="researchIterationBacktestSummary(item).length"
            class="ai-research-backtest-summary"
            data-test="ai-research-iteration-backtest-summary"
          >
            <strong>回测结果</strong>
            <span
              v-for="metric in researchIterationBacktestSummary(item)"
              :key="metric.key"
            >
              {{ metric.label }} {{ metric.value }}
            </span>
          </div>
          <div
            v-if="iterationProgress(item)"
            class="ai-research-iteration-progress"
            data-test="ai-research-iteration-progress"
          >
            <el-tag
              size="small"
              :type="iterationProgressTagType(iterationProgress(item)?.status)"
            >
              {{ iterationProgressLabel(iterationProgress(item)?.status) }}
            </el-tag>
            <span v-if="iterationProgress(item)?.previous_iteration">
              对比第 {{ iterationProgress(item)?.previous_iteration }} 轮
            </span>
            <span v-if="iterationProgressDeltaText(iterationProgress(item), 'sharpe_delta')">
              Sharpe {{ iterationProgressDeltaText(iterationProgress(item), 'sharpe_delta') }}
            </span>
            <span v-if="iterationProgressDeltaText(iterationProgress(item), 'quality_score_delta')">
              质量分 {{ iterationProgressDeltaText(iterationProgress(item), 'quality_score_delta') }}
            </span>
            <span v-if="iterationProgress(item)?.summary">
              {{ iterationProgress(item)?.summary }}
            </span>
          </div>
          <p
            v-if="item.failure_reason"
            class="ai-research-warning"
          >
            {{ item.failure_reason }}
          </p>
          <ul
            v-if="item.quality_gate_failures?.length"
            class="ai-research-notes ai-research-warning-list"
            data-test="ai-research-iteration-failures"
          >
            <li
              v-for="failure in item.quality_gate_failures"
              :key="failure"
            >
              {{ failure }}
            </li>
          </ul>
          <div
            v-if="iterationOutOfSampleValidation(item)"
            class="ai-research-oos-summary ai-research-oos-summary-compact"
            data-test="ai-research-iteration-oos"
          >
            <div class="ai-research-oos-head">
              <strong>样本外验证</strong>
              <el-tag
                size="small"
                :type="outOfSampleTagType(iterationOutOfSampleValidation(item)?.status)"
              >
                {{ outOfSampleStatusLabel(iterationOutOfSampleValidation(item)?.status) }}
              </el-tag>
            </div>
            <div class="ai-research-oos-details">
              <span v-if="formatOutOfSampleWindow(iterationOutOfSampleValidation(item)?.window)">
                {{ formatOutOfSampleWindow(iterationOutOfSampleValidation(item)?.window) }}
              </span>
              <span
                v-for="gate in iterationOutOfSampleValidation(item)?.gate_evaluations || []"
                :key="gate.key"
              >
                {{ gate.label }} {{ formatMetric(gate.actual) }} / {{ formatMetric(gate.target) }}
              </span>
              <span
                v-for="failure in iterationOutOfSampleValidation(item)?.failures || []"
                :key="failure"
                class="ai-research-warning-text"
              >
                {{ failure }}
              </span>
            </div>
          </div>
          <ul
            v-if="item.improvement_notes.length"
            class="ai-research-notes"
          >
            <li
              v-for="note in item.improvement_notes"
              :key="note"
            >
              {{ note }}
            </li>
          </ul>
          <ul
            v-if="researchIterationNextActions(item).length"
            class="ai-research-next-actions"
          >
            <li
              v-for="action in researchIterationNextActions(item)"
              :key="action"
            >
              {{ action }}
            </li>
          </ul>
        </div>
      </div>
    </div>
    <div
      v-else-if="aiResearchRunning"
      class="ai-research-result-context"
      data-test="ai-research-live-output"
    >
      <strong>
        正在更新 {{ aiResearchOutputConfigProfile?.name || '当前方案' }} 的研究输出
      </strong>
      <span>
        阶段 {{ aiResearchTaskStageLabel || '排队中' }} · {{ formatTaskProgress(aiResearchTaskProgress) }}
      </span>
      <span v-if="aiResearchTaskMessage">{{ aiResearchTaskMessage }}</span>
      <span v-if="aiResearchTaskLatestIteration">
        最近{{ taskLatestIterationLabel(aiResearchTaskLatestIteration) }}
        Sharpe {{ formatMetric(taskLatestIterationMetric(aiResearchTaskLatestIteration, 'sharpe_ratio', 'sharpe')) }}
      </span>
    </div>
    <el-empty
      v-else
      :description="aiResearchNoResultDescription"
    />

    <AIResearchRunHistoryPanel />
  </section>
</template>

<script setup lang="ts">
import { Link, MagicStick, VideoPlay } from '@element-plus/icons-vue'
import AIResearchLiveHandoffCard from './AIResearchLiveHandoffCard.vue'
import AIResearchRunHistoryPanel from './AIResearchRunHistoryPanel.vue'
import { useStrategyPageContext } from '../strategy/strategyPageContext'

const {
  t,
  aiResearchRunning,
  aiResearchResult,
  aiResearchTaskProgress,
  aiResearchTaskMessage,
  aiResearchTaskLatestIteration,
  aiResearchPaperStartingRunId,
  aiResearchPaperReviewingRunId,
  aiResearchLiveHandoffLoadingRunId,
  aiResearchStrategyViewingRunId,
  aiResearchTimeline,
  aiResearchTimelineLoading,
  aiResearchVersions,
  aiResearchVersionsLoading,
  aiResearchVersionCompare,
  aiResearchVersionCompareLoading,
  aiResearchSelectedVersionIds,
  aiResearchVersionComparisonRows,
  aiResearchForm,
  aiResearchOutputConfigProfile,
  aiResearchOutputProfileSummary,
  aiResearchNoResultDescription,
  aiResearchCanCompareVersions,
  aiResearchVersionMetricKeys,
  aiBestSharpe,
  aiResearchNextActions,
  aiResearchBestDiagnostics,
  aiResearchPipelineSteps,
  aiResearchPromotionAudit,
  aiResearchCurrentPaperFailed,
  aiResearchCurrentPaperTargetMissing,
  aiResearchPaperStatusText,
  aiResearchTaskStageLabel,
  aiResearchCurrentContinuationSummary,
  canViewBestStrategyFromCurrentResult,
  canStartPaperFromCurrentResult,
  canOpenPaperFromCurrentResult,
  canReviewPaperFromCurrentResult,
  canContinueResearchFromCurrentPaperIssue,
  canContinueResearchFromCurrentRunRecord,
  aiResearchCurrentPaperReview,
  canBuildLiveHandoffFromCurrentResult,
  aiResearchBestGateEvaluations,
  aiResearchOutOfSampleValidation,
  formatMetric,
  gateGapText,
  formatTaskProgress,
  taskLatestIterationLabel,
  taskLatestIterationMetric,
  formatDateTime,
  iterationOutOfSampleValidation,
  researchIterationBacktestSummary,
  formatOutOfSampleWindow,
  outOfSampleTagType,
  outOfSampleStatusLabel,
  compareSelectedAIResearchVersions,
  aiResearchEventTagType,
  aiResearchVersionStatusTagType,
  aiResearchVersionMetric,
  aiResearchVersionMetricLabel,
  researchIterationNextActions,
  iterationProgress,
  iterationProgressLabel,
  iterationProgressTagType,
  iterationProgressDeltaText,
  pipelineStepStatusLabel,
  pipelineStepTagType,
  pipelineStepDetailText,
  aiResearchStageLabel,
  startPaperFromCurrentResult,
  viewBestStrategyFromCurrentResult,
  viewResearchIterationStrategy,
  viewAIResearchVersionCode,
  reviewPaperFromCurrentResult,
  buildLiveHandoffFromCurrentResult,
  continueResearchFromCurrentPaperReview,
  continueResearchFromCurrentRunRecord,
  openResearchWorkspace,
  openPaperWorkspace,
} = useStrategyPageContext()
</script>

<style scoped src="../StrategyPage.css" />
