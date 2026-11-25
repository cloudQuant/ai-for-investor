<template>
  <template v-if="aiResearchResult">
    <div
      v-if="aiResearchCurrentLiveHandoff"
      class="ai-research-paper-review ai-research-live-handoff"
      data-test="ai-research-current-live-handoff"
    >
      <div class="ai-research-paper-review-head">
        <el-tag
          size="small"
          :type="aiResearchCurrentLiveHandoff.ready_for_live ? 'success' : 'danger'"
        >
          {{ liveHandoffStatusLabel(aiResearchCurrentLiveHandoff.status) }}
        </el-tag>
        <span>
          {{ aiResearchCurrentLiveHandoff.approval_required ? '需要人工审批' : '无需额外审批' }}
        </span>
      </div>
      <div class="ai-research-paper-review-rules">
        <span>标的 {{ aiResearchCurrentLiveHandoff.symbol }}</span>
        <span>Sharpe {{ formatMetric(aiResearchCurrentLiveHandoff.best_sharpe) }}</span>
        <span v-if="aiResearchCurrentLiveHandoff.expires_at">
          候选有效期 {{ formatDateTime(aiResearchCurrentLiveHandoff.expires_at) }}
        </span>
        <span v-if="Object.keys(aiResearchCurrentLiveHandoff.asset_specs || {}).length">
          资产规格已随交接包固化
        </span>
      </div>
      <div
        v-if="aiResearchCurrentLiveHandoff.approvals_required.length"
        class="ai-research-live-readiness"
        data-test="ai-research-current-live-handoff-approvals"
      >
        <strong>审批项</strong>
        <span
          v-for="item in aiResearchCurrentLiveHandoff.approvals_required"
          :key="item.key"
        >
          {{ item.label }} {{ liveReadinessStatusLabel(item.status) }}：{{ item.action || item.evidence }}
        </span>
      </div>
      <div
        v-if="aiResearchCurrentLiveHandoff.deployment_blockers.length"
        class="ai-research-paper-review-actions"
        data-test="ai-research-current-live-handoff-blockers"
      >
        <span
          v-for="blocker in aiResearchCurrentLiveHandoff.deployment_blockers"
          :key="blocker"
        >
          {{ blocker }}
        </span>
      </div>
      <div
        v-if="aiResearchCurrentLiveHandoff.approval"
        class="ai-research-live-readiness"
        data-test="ai-research-current-live-handoff-approval"
      >
        <strong>审批结果</strong>
        <span>
          {{ liveHandoffApprovalLabel(aiResearchCurrentLiveHandoff) }}
          {{ aiResearchCurrentLiveHandoff.approval.decided_by }}
          {{ formatDateTime(aiResearchCurrentLiveHandoff.approval.decided_at) }}
        </span>
        <span v-if="aiResearchCurrentLiveHandoff.approval.comment">
          {{ aiResearchCurrentLiveHandoff.approval.comment }}
        </span>
      </div>
      <div
        v-if="canApproveLiveHandoff(aiResearchCurrentLiveHandoff)"
        class="ai-research-paper-review-actions"
        data-test="ai-research-current-live-handoff-actions"
      >
        <el-button
          size="small"
          type="success"
          plain
          :loading="aiResearchLiveHandoffApprovingRunId === `${aiResearchCurrentLiveHandoff.run_id}:approved`"
          data-test="ai-research-current-live-handoff-approve"
          @click="approveCurrentLiveHandoff('approved')"
        >
          批准交接
        </el-button>
        <el-button
          size="small"
          type="danger"
          plain
          :loading="aiResearchLiveHandoffApprovingRunId === `${aiResearchCurrentLiveHandoff.run_id}:rejected`"
          data-test="ai-research-current-live-handoff-reject"
          @click="approveCurrentLiveHandoff('rejected')"
        >
          驳回
        </el-button>
      </div>
      <div
        v-if="isLiveTradingPreparedForRecord(aiResearchResult.run_record)"
        class="ai-research-live-readiness"
        data-test="ai-research-current-live-prepare-status"
      >
        <strong>实盘单元</strong>
        <span>{{ liveTradingPrepareSummary(aiResearchResult.run_record) }}</span>
        <el-button
          size="small"
          type="primary"
          plain
          data-test="ai-research-current-open-live"
          @click="openLiveWorkspaceFromCurrentResult"
        >
          打开实盘工作区
        </el-button>
        <el-button
          v-if="aiResearchResult.run_record && canActivateLiveTradingFromRecord(aiResearchResult.run_record)"
          size="small"
          type="success"
          plain
          :loading="aiResearchLiveTradingActivatingRunId === aiResearchResult.run_id"
          data-test="ai-research-current-live-activate"
          @click="activateLiveTradingFromCurrentResult"
        >
          受控启动实盘
        </el-button>
        <el-button
          v-if="aiResearchResult.run_record && canDeactivateLiveTradingFromRecord(aiResearchResult.run_record)"
          size="small"
          type="danger"
          plain
          :loading="aiResearchLiveTradingDeactivatingRunId === aiResearchResult.run_id"
          data-test="ai-research-current-live-deactivate"
          @click="deactivateLiveTradingFromCurrentResult"
        >
          停止并撤销
        </el-button>
      </div>
      <div
        v-else-if="aiResearchResult.run_record && canPrepareLiveTradingFromRecord(aiResearchResult.run_record)"
        class="ai-research-paper-review-actions"
        data-test="ai-research-current-live-prepare-actions"
      >
        <el-button
          size="small"
          type="success"
          plain
          :loading="aiResearchLiveTradingPreparingRunId === aiResearchResult.run_id"
          data-test="ai-research-current-live-prepare"
          @click="prepareLiveTradingFromCurrentResult"
        >
          准备实盘单元
        </el-button>
      </div>
    </div>

    <div
      v-if="aiResearchCurrentRuntimeEnvironment.length"
      class="ai-research-paper-env"
      data-test="ai-research-current-runtime-env"
    >
      <strong>回测环境</strong>
      <span
        v-for="item in aiResearchCurrentRuntimeEnvironment"
        :key="item.key"
      >
        {{ item.label }} {{ item.value }}
      </span>
    </div>

    <div
      v-if="aiResearchCurrentPaperEnvironment.length"
      class="ai-research-paper-env"
      data-test="ai-research-current-paper-env"
    >
      <strong>模拟环境</strong>
      <span
        v-for="item in aiResearchCurrentPaperEnvironment"
        :key="item.key"
      >
        {{ item.label }} {{ item.value }}
      </span>
    </div>

    <div
      v-if="aiResearchCurrentPaperReview"
      class="ai-research-paper-review ai-research-current-paper-review"
      data-test="ai-research-current-paper-review"
    >
      <div class="ai-research-paper-review-head">
        <el-tag
          size="small"
          :type="aiResearchCurrentPaperReview.ready_for_live ? 'success' : 'warning'"
        >
          {{ paperReviewStatusLabel(aiResearchCurrentPaperReview.status) }}
        </el-tag>
        <span>
          {{ paperReviewDispositionLabel(aiResearchCurrentPaperReview) }}
        </span>
      </div>
      <div class="ai-research-paper-review-rules">
        <span
          v-for="rule in aiResearchCurrentPaperReview.evaluations"
          :key="rule.key"
        >
          {{ rule.label }} {{ paperReviewRuleStatusLabel(rule.status) }}
          {{ formatMetric(rule.actual) }} / {{ formatMetric(rule.threshold) }}
          {{ paperReviewRuleGapText(rule) }}
        </span>
        <span v-if="aiResearchCurrentPaperReview.live_readiness_expires_at">
          候选有效期 {{ formatDateTime(aiResearchCurrentPaperReview.live_readiness_expires_at) }}
        </span>
      </div>
      <div
        v-if="liveReadinessChecklistForReview(aiResearchCurrentPaperReview).length"
        class="ai-research-live-readiness"
        data-test="ai-research-current-live-readiness"
      >
        <strong>实盘交接清单</strong>
        <span
          v-for="item in liveReadinessChecklistForReview(aiResearchCurrentPaperReview)"
          :key="item.key"
        >
          {{ item.label }} {{ liveReadinessStatusLabel(item.status) }}：{{ item.evidence }}
        </span>
      </div>
      <div
        v-if="aiResearchCurrentPaperReviewLock"
        class="ai-research-live-readiness"
        data-test="ai-research-current-paper-review-lock"
      >
        <strong>模拟单元保护</strong>
        <span>{{ paperReviewLockSummary(aiResearchCurrentPaperReviewLock) }}</span>
        <span v-if="aiResearchCurrentPaperReviewLock.reviewed_at">
          复核时间 {{ formatDateTime(aiResearchCurrentPaperReviewLock.reviewed_at) }}
        </span>
        <span v-if="paperReviewLockStopResultText(aiResearchCurrentPaperReviewLock)">
          停止结果 {{ paperReviewLockStopResultText(aiResearchCurrentPaperReviewLock) }}
        </span>
      </div>
      <div
        v-if="aiResearchCurrentPaperReview.next_actions?.length"
        class="ai-research-paper-review-actions"
        data-test="ai-research-current-paper-review-actions"
      >
        <span
          v-for="action in aiResearchCurrentPaperReview.next_actions"
          :key="action"
        >
          {{ action }}
        </span>
      </div>
      <el-button
        v-if="canContinueResearchFromCurrentPaperReview"
        size="small"
        type="warning"
        plain
        :loading="aiResearchRunning && aiResearchForm.continue_from_run_id === aiResearchResult.run_id"
        class="ai-research-current-paper-review-action"
        data-test="ai-research-current-continue-paper-review"
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
  </template>
</template>

<script setup lang="ts">
import { MagicStick } from '@element-plus/icons-vue'
import { useStrategyPageContext } from '../strategy/strategyPageContext'

const {
  aiResearchRunning,
  aiResearchResult,
  aiResearchLiveHandoffApprovingRunId,
  aiResearchLiveTradingPreparingRunId,
  aiResearchLiveTradingActivatingRunId,
  aiResearchLiveTradingDeactivatingRunId,
  aiResearchForm,
  canContinueResearchFromCurrentPaperReview,
  aiResearchCurrentPaperReview,
  aiResearchCurrentPaperReviewLock,
  aiResearchCurrentLiveHandoff,
  aiResearchCurrentPaperEnvironment,
  aiResearchCurrentRuntimeEnvironment,
  formatMetric,
  formatDateTime,
  canApproveLiveHandoff,
  canPrepareLiveTradingFromRecord,
  canActivateLiveTradingFromRecord,
  canDeactivateLiveTradingFromRecord,
  liveHandoffApprovalLabel,
  liveTradingPrepareSummary,
  isLiveTradingPreparedForRecord,
  paperReviewStatusLabel,
  paperReviewRuleStatusLabel,
  paperReviewRuleGapText,
  paperReviewDispositionLabel,
  liveReadinessStatusLabel,
  liveHandoffStatusLabel,
  liveReadinessChecklistForReview,
  paperReviewLockSummary,
  paperReviewLockStopResultText,
  approveCurrentLiveHandoff,
  prepareLiveTradingFromCurrentResult,
  activateLiveTradingFromCurrentResult,
  deactivateLiveTradingFromCurrentResult,
  continueResearchFromCurrentPaperReview,
  openLiveWorkspaceFromCurrentResult,
} = useStrategyPageContext()
</script>

<style scoped src="../StrategyPage.css" />
