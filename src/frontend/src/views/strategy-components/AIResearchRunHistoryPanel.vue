<template>
  <div
    class="ai-research-history"
    data-test="ai-research-history"
  >
    <div class="ai-research-summary ai-research-history-head">
      <div>
        <span class="ai-research-kicker">{{ t('strategy.aiResearchResult') }}</span>
        <h3 class="ai-research-history-title">
          {{ t('strategy.aiResearchIterations') }}
        </h3>
      </div>
      <el-tag
        size="small"
        type="info"
      >
        {{ aiResearchVisibleRuns.length }}
      </el-tag>
    </div>

    <div
      v-if="aiResearchRunsLoading"
      class="ai-research-history-empty"
    >
      {{ t('common.loading') }}
    </div>
    <div
      v-else-if="aiResearchVisibleRuns.length"
      class="ai-research-history-list"
    >
      <div
        v-for="record in aiResearchVisibleRuns"
        :key="record.run_id"
        class="ai-research-history-item"
      >
        <button
          type="button"
          class="ai-research-history-select"
          @click="selectAIResearchRunRecord(record)"
        >
          <span class="ai-research-history-main">
            <strong>{{ record.prompt }}</strong>
            <el-tag
              size="small"
              :type="record.achieved ? 'success' : 'warning'"
            >
              {{ aiResearchRunStatusLabel(record.status) }}
            </el-tag>
          </span>
          <span class="ai-research-history-meta">
            <span>{{ record.symbol }}</span>
            <span>{{ t('strategy.aiResearchBestSharpe') }} {{ formatMetric(record.best_sharpe) }}</span>
            <span>质量分 {{ formatMetric(record.best_quality_score) }}</span>
            <span v-if="pipelineStage(record)">
              阶段 {{ pipelineStageLabel(record) }}
            </span>
            <span v-if="record.paper_workspace_name">
              模拟 {{ record.paper_workspace_name }}
            </span>
            <span
              v-if="continuationSummaryForRecord(record)"
              data-test="ai-research-history-continuation"
            >
              继续来源 {{ continuationSummaryForRecord(record) }}
            </span>
            <span v-if="record.pipeline?.paper_trading_error">
              模拟错误 {{ record.pipeline.paper_trading_error }}
            </span>
            <span v-if="recordOutOfSampleSummary(record)">
              {{ recordOutOfSampleSummary(record) }}
            </span>
            <span>{{ t('strategy.aiResearchIterations') }} {{ record.iteration_count }}</span>
            <span v-if="record.paper_review_status">
              复核 {{ paperReviewStatusLabel(record.paper_review_status) }}
            </span>
            <span v-if="record.paper_reviewed_at">
              复核时间 {{ formatDateTime(record.paper_reviewed_at) }}
            </span>
            <span v-if="record.live_readiness_expires_at">
              候选有效期 {{ formatDateTime(record.live_readiness_expires_at) }}
            </span>
            <span>{{ formatDateTime(record.completed_at) }}</span>
          </span>
        </button>
        <el-button
          v-if="canStartPaperFromRecord(record)"
          size="small"
          type="success"
          :loading="aiResearchPaperStartingRunId === record.run_id"
          data-test="ai-research-history-start-paper"
          @click="startPaperFromResearchRecord(record)"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <VideoPlay />
          </el-icon>
          {{ paperStartButtonLabel(record) }}
        </el-button>
        <el-button
          v-else-if="canReviewPaperFromRecord(record)"
          size="small"
          type="primary"
          plain
          :loading="aiResearchPaperReviewingRunId === record.run_id"
          data-test="ai-research-history-review-paper"
          @click="reviewPaperFromResearchRecord(record)"
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
          v-if="canBuildLiveHandoffFromRecord(record)"
          size="small"
          type="success"
          plain
          :loading="aiResearchLiveHandoffLoadingRunId === record.run_id"
          data-test="ai-research-history-live-handoff"
          @click="buildLiveHandoffFromResearchRecord(record)"
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
          v-if="bestStrategyIdForRecord(record)"
          size="small"
          plain
          :loading="aiResearchStrategyViewingRunId === record.run_id"
          data-test="ai-research-history-view-strategy"
          @click="viewStrategyFromResearchRecord(record)"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <Link />
          </el-icon>
          查看脚本
        </el-button>
        <el-button
          v-if="canContinueResearchFromRunRecord(record)"
          size="small"
          type="warning"
          plain
          :loading="aiResearchRunning && aiResearchForm.continue_from_run_id === record.run_id"
          data-test="ai-research-history-continue-run"
          @click="continueResearchFromRecord(record)"
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
          v-if="canContinueResearchFromPaperReview(record)"
          size="small"
          type="warning"
          plain
          :loading="aiResearchRunning && aiResearchForm.continue_from_run_id === record.run_id"
          data-test="ai-research-history-continue-paper-review"
          @click="continueResearchFromPaperReview(record)"
        >
          <el-icon
            class="mr-1"
            aria-hidden="true"
          >
            <MagicStick />
          </el-icon>
          继续改进
        </el-button>
        <div
          v-if="hasResearchRuntimeEnvironment(record)"
          class="ai-research-paper-env"
          data-test="ai-research-history-runtime-env"
        >
          <strong>回测环境</strong>
          <span
            v-for="item in researchRuntimeItems(record)"
            :key="item.key"
          >
            {{ item.label }} {{ item.value }}
          </span>
        </div>
        <div
          v-if="hasPaperEnvironment(record.paper_handoff)"
          class="ai-research-paper-env"
          data-test="ai-research-history-paper-env"
        >
          <strong>模拟环境</strong>
          <span
            v-for="item in paperEnvironmentItems(record.paper_handoff)"
            :key="item.key"
          >
            {{ item.label }} {{ item.value }}
          </span>
        </div>
        <div
          v-if="paperReviewForRecord(record)"
          class="ai-research-paper-review"
          data-test="ai-research-paper-review"
        >
          <div class="ai-research-paper-review-head">
            <el-tag
              size="small"
              :type="paperReviewForRecord(record)?.ready_for_live ? 'success' : 'warning'"
            >
              {{ paperReviewStatusLabel(paperReviewForRecord(record)?.status) }}
            </el-tag>
            <span>
              {{ paperReviewDispositionLabel(paperReviewForRecord(record)) }}
            </span>
          </div>
          <div class="ai-research-paper-review-rules">
            <span
              v-for="rule in paperReviewForRecord(record)?.evaluations ?? []"
              :key="rule.key"
            >
              {{ rule.label }} {{ paperReviewRuleStatusLabel(rule.status) }}
              {{ formatMetric(rule.actual) }} / {{ formatMetric(rule.threshold) }}
              {{ paperReviewRuleGapText(rule) }}
            </span>
            <span v-if="paperReviewForRecord(record)?.live_readiness_expires_at">
              候选有效期 {{ formatDateTime(paperReviewForRecord(record)?.live_readiness_expires_at) }}
            </span>
          </div>
          <div
            v-if="liveReadinessChecklistForReview(paperReviewForRecord(record)).length"
            class="ai-research-live-readiness"
            data-test="ai-research-live-readiness"
          >
            <strong>实盘交接清单</strong>
            <span
              v-for="item in liveReadinessChecklistForReview(paperReviewForRecord(record))"
              :key="item.key"
            >
              {{ item.label }} {{ liveReadinessStatusLabel(item.status) }}：{{ item.evidence }}
            </span>
          </div>
          <div
            v-if="paperReviewLockForRecord(record)"
            class="ai-research-live-readiness"
            data-test="ai-research-paper-review-lock"
          >
            <strong>模拟单元保护</strong>
            <span>{{ paperReviewLockSummary(paperReviewLockForRecord(record)) }}</span>
            <span v-if="paperReviewLockForRecord(record)?.reviewed_at">
              复核时间 {{ formatDateTime(paperReviewLockForRecord(record)?.reviewed_at) }}
            </span>
            <span v-if="paperReviewLockStopResultText(paperReviewLockForRecord(record))">
              停止结果 {{ paperReviewLockStopResultText(paperReviewLockForRecord(record)) }}
            </span>
          </div>
          <div
            v-if="paperReviewForRecord(record)?.next_actions?.length"
            class="ai-research-paper-review-actions"
            data-test="ai-research-paper-review-actions"
          >
            <span
              v-for="action in paperReviewForRecord(record)?.next_actions ?? []"
              :key="action"
            >
              {{ action }}
            </span>
          </div>
        </div>
        <div
          v-if="liveHandoffForRecord(record)"
          class="ai-research-paper-review ai-research-live-handoff"
          data-test="ai-research-history-live-handoff-panel"
        >
          <div class="ai-research-paper-review-head">
            <el-tag
              size="small"
              :type="liveHandoffForRecord(record)?.ready_for_live ? 'success' : 'danger'"
            >
              {{ liveHandoffStatusLabel(liveHandoffForRecord(record)?.status) }}
            </el-tag>
            <span>
              {{ liveHandoffForRecord(record)?.approval_required ? '需要人工审批' : '无需额外审批' }}
            </span>
          </div>
          <div class="ai-research-paper-review-rules">
            <span>标的 {{ liveHandoffForRecord(record)?.symbol }}</span>
            <span>Sharpe {{ formatMetric(liveHandoffForRecord(record)?.best_sharpe) }}</span>
            <span v-if="liveHandoffForRecord(record)?.expires_at">
              候选有效期 {{ formatDateTime(liveHandoffForRecord(record)?.expires_at) }}
            </span>
            <span v-if="Object.keys(liveHandoffForRecord(record)?.asset_specs || {}).length">
              资产规格已随交接包固化
            </span>
          </div>
          <div
            v-if="liveHandoffForRecord(record)?.approvals_required.length"
            class="ai-research-live-readiness"
            data-test="ai-research-history-live-handoff-approvals"
          >
            <strong>审批项</strong>
            <span
              v-for="item in liveHandoffForRecord(record)?.approvals_required ?? []"
              :key="item.key"
            >
              {{ item.label }} {{ liveReadinessStatusLabel(item.status) }}：{{ item.action || item.evidence }}
            </span>
          </div>
          <div
            v-if="liveHandoffForRecord(record)?.deployment_blockers.length"
            class="ai-research-paper-review-actions"
            data-test="ai-research-history-live-handoff-blockers"
          >
            <span
              v-for="blocker in liveHandoffForRecord(record)?.deployment_blockers ?? []"
              :key="blocker"
            >
              {{ blocker }}
            </span>
          </div>
          <div
            v-if="liveHandoffForRecord(record)?.approval"
            class="ai-research-live-readiness"
            data-test="ai-research-history-live-handoff-approval"
          >
            <strong>审批结果</strong>
            <span>
              {{ liveHandoffApprovalLabel(liveHandoffForRecord(record)) }}
              {{ liveHandoffForRecord(record)?.approval?.decided_by }}
              {{ formatDateTime(liveHandoffForRecord(record)?.approval?.decided_at) }}
            </span>
            <span v-if="liveHandoffForRecord(record)?.approval?.comment">
              {{ liveHandoffForRecord(record)?.approval?.comment }}
            </span>
          </div>
          <div
            v-if="canApproveLiveHandoff(liveHandoffForRecord(record))"
            class="ai-research-paper-review-actions"
            data-test="ai-research-history-live-handoff-actions"
          >
            <el-button
              size="small"
              type="success"
              plain
              :loading="aiResearchLiveHandoffApprovingRunId === `${record.run_id}:approved`"
              data-test="ai-research-history-live-handoff-approve"
              @click="approveLiveHandoffFromResearchRecord(record, 'approved')"
            >
              批准交接
            </el-button>
            <el-button
              size="small"
              type="danger"
              plain
              :loading="aiResearchLiveHandoffApprovingRunId === `${record.run_id}:rejected`"
              data-test="ai-research-history-live-handoff-reject"
              @click="approveLiveHandoffFromResearchRecord(record, 'rejected')"
            >
              驳回
            </el-button>
          </div>
          <div
            v-if="isLiveTradingPreparedForRecord(record)"
            class="ai-research-live-readiness"
            data-test="ai-research-history-live-prepare-status"
          >
            <strong>实盘单元</strong>
            <span>{{ liveTradingPrepareSummary(record) }}</span>
            <el-button
              size="small"
              type="primary"
              plain
              data-test="ai-research-history-open-live"
              @click="openLiveWorkspaceFromRecord(record)"
            >
              打开实盘工作区
            </el-button>
            <el-button
              v-if="canActivateLiveTradingFromRecord(record)"
              size="small"
              type="success"
              plain
              :loading="aiResearchLiveTradingActivatingRunId === record.run_id"
              data-test="ai-research-history-live-activate"
              @click="activateLiveTradingFromResearchRecord(record)"
            >
              受控启动实盘
            </el-button>
            <el-button
              v-if="canDeactivateLiveTradingFromRecord(record)"
              size="small"
              type="danger"
              plain
              :loading="aiResearchLiveTradingDeactivatingRunId === record.run_id"
              data-test="ai-research-history-live-deactivate"
              @click="deactivateLiveTradingFromResearchRecord(record)"
            >
              停止并撤销
            </el-button>
          </div>
          <div
            v-else-if="canPrepareLiveTradingFromRecord(record)"
            class="ai-research-paper-review-actions"
            data-test="ai-research-history-live-prepare-actions"
          >
            <el-button
              size="small"
              type="success"
              plain
              :loading="aiResearchLiveTradingPreparingRunId === record.run_id"
              data-test="ai-research-history-live-prepare"
              @click="prepareLiveTradingFromResearchRecord(record)"
            >
              准备实盘单元
            </el-button>
          </div>
        </div>
      </div>
    </div>
    <div
      v-else
      class="ai-research-history-empty"
    >
      {{ aiResearchNoResultDescription }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { Link, MagicStick, VideoPlay } from '@element-plus/icons-vue'
import { useStrategyPageContext } from '../strategy/strategyPageContext'

const {
  t,
  aiResearchRunning,
  aiResearchRunsLoading,
  aiResearchPaperStartingRunId,
  aiResearchPaperReviewingRunId,
  aiResearchLiveHandoffLoadingRunId,
  aiResearchStrategyViewingRunId,
  aiResearchLiveHandoffApprovingRunId,
  aiResearchLiveTradingPreparingRunId,
  aiResearchLiveTradingActivatingRunId,
  aiResearchLiveTradingDeactivatingRunId,
  aiResearchForm,
  aiResearchVisibleRuns,
  aiResearchNoResultDescription,
  formatMetric,
  formatDateTime,
  hasResearchRuntimeEnvironment,
  researchRuntimeItems,
  hasPaperEnvironment,
  paperEnvironmentItems,
  recordOutOfSampleSummary,
  bestStrategyIdForRecord,
  selectAIResearchRunRecord,
  canStartPaperFromRecord,
  canReviewPaperFromRecord,
  canBuildLiveHandoffFromRecord,
  liveHandoffForRecord,
  canApproveLiveHandoff,
  canPrepareLiveTradingFromRecord,
  canActivateLiveTradingFromRecord,
  canDeactivateLiveTradingFromRecord,
  liveHandoffApprovalLabel,
  liveTradingPrepareSummary,
  isLiveTradingPreparedForRecord,
  paperStartButtonLabel,
  canContinueResearchFromPaperReview,
  canContinueResearchFromRunRecord,
  continuationSummaryForRecord,
  pipelineStage,
  pipelineStageLabel,
  aiResearchRunStatusLabel,
  paperReviewStatusLabel,
  paperReviewRuleStatusLabel,
  paperReviewRuleGapText,
  paperReviewDispositionLabel,
  liveReadinessStatusLabel,
  liveHandoffStatusLabel,
  liveReadinessChecklistForReview,
  paperReviewLockForRecord,
  paperReviewLockSummary,
  paperReviewLockStopResultText,
  paperReviewForRecord,
  startPaperFromResearchRecord,
  viewStrategyFromResearchRecord,
  reviewPaperFromResearchRecord,
  buildLiveHandoffFromResearchRecord,
  approveLiveHandoffFromResearchRecord,
  prepareLiveTradingFromResearchRecord,
  activateLiveTradingFromResearchRecord,
  deactivateLiveTradingFromResearchRecord,
  continueResearchFromPaperReview,
  continueResearchFromRecord,
  openLiveWorkspaceFromRecord,
} = useStrategyPageContext()
</script>

<style scoped src="../StrategyPage.css" />
