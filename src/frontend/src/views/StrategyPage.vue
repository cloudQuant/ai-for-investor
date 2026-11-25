<template>
  <div
    class="strategy-page"
    :class="{
      'strategy-page--ai-research': showAIResearchTab,
      'strategy-page--management': showStrategyManagementTabs,
    }"
  >
    <section
      v-if="showStrategyManagementTabs"
      class="strategy-management-hero"
      data-test="strategy-management-hero"
      aria-labelledby="strategy-management-title"
    >
      <div class="strategy-management-copy">
        <span class="strategy-management-kicker">{{ t('strategy.managementHeroKicker') }}</span>
        <h1 id="strategy-management-title">
          {{ t('strategy.managementHeroTitle') }}
        </h1>
        <p>{{ t('strategy.managementHeroSubtitle') }}</p>
      </div>

      <div class="strategy-management-actions">
        <el-button
          type="primary"
          size="large"
          :aria-label="t('strategy.createStrategy')"
          @click="showCreateDialog"
        >
          <el-icon aria-hidden="true">
            <Plus />
          </el-icon>
          {{ t('strategy.createStrategy') }}
        </el-button>
      </div>

      <div class="strategy-management-metrics">
        <div
          v-for="item in strategyManagementStats"
          :key="item.key"
          class="strategy-management-metric"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </section>

    <section
      v-if="showAIResearchTab"
      class="ai-research-hero"
      data-test="ai-research-hero"
      aria-labelledby="ai-research-hero-title"
    >
      <div class="ai-research-hero-copy">
        <span class="ai-research-hero-kicker">{{ t('strategy.aiResearchHeroKicker') }}</span>
        <h1 id="ai-research-hero-title">
          {{ t('strategy.aiResearchHeroTitle') }}
        </h1>
        <p>{{ t('strategy.aiResearchHeroSubtitle') }}</p>
      </div>

      <div class="ai-research-hero-steps">
        <span
          v-for="step in aiResearchHeroSteps"
          :key="step.key"
          class="ai-research-hero-step"
        >
          <span class="ai-research-hero-step-index">{{ step.index }}</span>
          <span>{{ step.label }}</span>
        </span>
      </div>

      <div class="ai-research-hero-metrics">
        <div
          v-for="item in aiResearchHeroMetrics"
          :key="item.key"
          class="ai-research-hero-metric"
        >
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </section>

    <!-- Main tabs: Gallery / My strategies -->
    <el-tabs
      v-model="activeTab"
      type="border-card"
      class="strategy-tabs"
    >
      <!-- ========== AI Research Loop ========== -->
      <el-tab-pane
        v-if="showAIResearchTab"
        :label="t('strategy.aiResearch')"
        name="aiResearch"
      >
        <TrustedResearchWorkbench />
        <div class="ai-research-grid">
          <AIResearchMandatePanel />

          <AIResearchResultPanel />
        </div>
      </el-tab-pane>

      <!-- ========== Gallery ========== -->
      <el-tab-pane
        v-if="showStrategyManagementTabs"
        :label="t('strategy.gallery')"
        name="gallery"
      >
        <section class="strategy-library-panel">
          <div class="strategy-panel-head">
            <div>
              <span>{{ t('strategy.searchAndFilter') }}</span>
              <h2>{{ t('strategy.gallery') }}</h2>
            </div>
            <el-tag
              effect="plain"
              round
            >
              {{ t('strategy.customCount', { count: filteredTemplates.length }) }}
            </el-tag>
          </div>

          <div class="strategy-filter-bar">
            <el-input
              v-model="searchKeyword"
              :placeholder="t('strategy.searchPlaceholder')"
              :aria-label="t('strategy.searchAriaLabel')"
              clearable
              class="strategy-search-input"
              :prefix-icon="Search"
            />
            <el-radio-group
              v-model="categoryFilter"
              class="strategy-category-filter"
              size="default"
              :aria-label="t('strategy.filterAriaLabel')"
            >
              <el-radio-button value="">
                {{ t('strategy.categoryAll') }}
              </el-radio-button>
              <el-radio-button value="trend">
                {{ t('strategy.categoryTrend') }}
              </el-radio-button>
              <el-radio-button value="mean_reversion">
                {{ t('strategy.categoryMeanReversion') }}
              </el-radio-button>
              <el-radio-button value="volatility">
                {{ t('strategy.categoryVolatility') }}
              </el-radio-button>
              <el-radio-button value="indicator">
                {{ t('strategy.categoryIndicator') }}
              </el-radio-button>
              <el-radio-button value="arbitrage">
                {{ t('strategy.categoryArbitrage') }}
              </el-radio-button>
              <el-radio-button value="custom">
                {{ t('strategy.categoryOther') }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <div
            v-if="filteredTemplates.length"
            class="strategy-template-grid"
          >
            <StrategyTemplateCard
              v-for="tpl in displayedTemplates"
              :key="tpl.id"
              :tpl="tpl"
              @detail="openTemplateDetail"
              @use="useTemplate"
              @backtest="goBacktest"
            />
          </div>
          <el-empty
            v-else
            class="strategy-empty-state"
            :description="t('strategy.noMatch')"
          />
        </section>
      </el-tab-pane>

      <!-- ========== My strategies ========== -->
      <el-tab-pane
        v-if="showStrategyManagementTabs"
        :label="t('strategy.myStrategies')"
        name="my"
      >
        <section class="strategy-table-panel">
          <div class="strategy-panel-head">
            <div>
              <span>{{ t('strategy.listDialog') }}</span>
              <h2>{{ t('strategy.myStrategies') }}</h2>
            </div>
            <el-button
              type="primary"
              plain
              @click="showCreateDialog"
            >
              <el-icon aria-hidden="true">
                <Plus />
              </el-icon>
              {{ t('strategy.createStrategy') }}
            </el-button>
          </div>

          <el-table
            v-loading="loading"
            class="strategy-owned-table"
            :data="strategies"
            stripe
            :empty-text="t('strategy.customEmpty')"
          >
            <el-table-column
              prop="name"
              :label="t('strategy.strategyName')"
              min-width="180"
            />
            <el-table-column
              prop="description"
              :label="t('strategy.paramDescription')"
              min-width="260"
              show-overflow-tooltip
            />
            <el-table-column
              prop="category"
              :label="t('strategy.strategyType')"
              width="140"
            >
              <template #default="{ row }">
                <el-tag
                  size="small"
                  :type="getCategoryType(row.category)"
                >
                  {{ getCategoryLabel(row.category) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column
              prop="created_at"
              :label="t('strategy.createdAt')"
              width="180"
            />
            <!-- @vue-generic {typeof strategies.value[number]} -->
            <el-table-column
              :label="$t('common.action')"
              width="220"
              fixed="right"
            >
              <template #default="{ row }">
                <el-button
                  type="primary"
                  link
                  size="small"
                  @click="viewStrategy(row)"
                >
                  {{ t('strategy.actionView') }}
                </el-button>
                <el-button
                  type="warning"
                  link
                  size="small"
                  @click="editStrategy(row)"
                >
                  {{ t('strategy.actionEdit') }}
                </el-button>
                <el-button
                  type="danger"
                  link
                  size="small"
                  @click="deleteStrategy(row.id)"
                >
                  {{ t('strategy.actionDelete') }}
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>
    </el-tabs>

    <!-- ========== 策略详情弹窗 (模板) ========== -->
    <StrategyDetailDialog
      v-model:visible="detailVisible"
      v-model:detail-tab="detailTab"
      :template="detailTemplate"
      :param-table-data="paramTableData"
      :readme-loading="readmeLoading"
      :readme-content="readmeContent"
      :strip-meta="stripStrategyMeta"
      @use="useTemplate"
      @backtest="goBacktest"
    />

    <!-- ========== 创建/编辑弹窗 ========== -->
    <StrategyEditDialog
      v-model:visible="dialogVisible"
      :is-edit="isEdit"
      :saving="saving"
      :form="form"
      @update:form="updateStrategyForm"
      @save="saveStrategy"
    />

    <el-dialog
      v-model="aiResearchPromptGenerationDialogVisible"
      title="生成投研目标"
      width="min(560px, calc(100vw - 32px))"
      :close-on-click-modal="!aiResearchPromptGenerationLoading"
      :close-on-press-escape="!aiResearchPromptGenerationLoading"
      :show-close="!aiResearchPromptGenerationLoading"
      data-test="ai-research-prompt-generation-dialog"
      @close="closeAIResearchPromptGenerationDialog"
    >
      <p class="ai-research-prompt-generation-intro">
        将根据当前标的、回测区间、质量门槛与验证设置生成研究目标。你可以直接使用默认方案，或让已配置的大模型润色表达与执行步骤。
      </p>
      <el-radio-group
        v-model="aiResearchPromptGenerationMode"
        class="ai-research-prompt-generation-options"
        data-test="ai-research-prompt-generation-mode"
      >
        <el-radio
          value="default"
          border
          class="ai-research-prompt-generation-option"
          data-test="ai-research-prompt-generation-default"
        >
          <span>使用默认方案</span>
          <small>不调用大模型，沿用当前配置生成稳定、可复现的研究目标。</small>
        </el-radio>
        <el-radio
          value="ai"
          border
          class="ai-research-prompt-generation-option"
          data-test="ai-research-prompt-generation-ai"
        >
          <span>使用大模型优化</span>
          <small>调用当前已配置模型，只优化表达和执行结构，不改变质量门槛与验证约束。</small>
        </el-radio>
      </el-radio-group>
      <template #footer>
        <el-button
          :disabled="aiResearchPromptGenerationLoading"
          @click="closeAIResearchPromptGenerationDialog"
        >
          {{ t('common.cancel') }}
        </el-button>
        <el-button
          type="primary"
          :loading="aiResearchPromptGenerationLoading"
          data-test="ai-research-prompt-generation-confirm"
          @click="confirmAIResearchPromptGeneration"
        >
          {{
            aiResearchPromptGenerationMode === 'ai'
              ? t('strategy.aiResearchPromptGenerateWithAi')
              : t('strategy.aiResearchPromptGenerateDefault')
          }}
        </el-button>
      </template>
    </el-dialog>

    <!-- ========== My strategy detail dialog ========== -->
    <el-dialog
      v-model="viewDialogVisible"
      :title="t('strategy.detailLabel')"
      width="800px"
    >
      <div
        v-if="currentStrategy"
        class="space-y-4"
      >
        <div class="flex justify-between items-center">
          <h2 class="text-xl font-bold">
            {{ currentStrategy.name }}
          </h2>
          <el-tag :type="getCategoryType(currentStrategy.category)">
            {{ getCategoryLabel(currentStrategy.category) }}
          </el-tag>
        </div>
        <p class="text-gray-500">
          {{ currentStrategy.description }}
        </p>
        <el-divider />
        <MonacoEditor
          v-model="currentStrategy.code"
          language="python"
          :height="400"
          :read-only="true"
          theme="vs"
        />
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { provide } from 'vue'
import { Plus, Search } from '@element-plus/icons-vue'
import { getCategoryType, getCategoryLabel, stripStrategyMeta } from '@/constants/strategy'
import MonacoEditor from '@/components/common/MonacoEditor.vue'
import TrustedResearchWorkbench from '@/components/aiResearch/TrustedResearchWorkbench.vue'
import AIResearchMandatePanel from './strategy-components/AIResearchMandatePanel.vue'
import AIResearchResultPanel from './strategy-components/AIResearchResultPanel.vue'
import StrategyEditDialog from './strategy-components/StrategyEditDialog.vue'
import StrategyDetailDialog from './strategy-components/StrategyDetailDialog.vue'
import StrategyTemplateCard from './strategy-components/StrategyTemplateCard.vue'
import { STRATEGY_PAGE_KEY } from './strategy/strategyPageContext'
import { useStrategyPage } from './strategy/useStrategyPage'

const strategyPage = useStrategyPage()
provide(STRATEGY_PAGE_KEY, strategyPage)

const {
  t,
  showAIResearchTab,
  showStrategyManagementTabs,
  activeTab,
  searchKeyword,
  categoryFilter,
  dialogVisible,
  viewDialogVisible,
  detailVisible,
  isEdit,
  saving,
  currentStrategy,
  detailTemplate,
  detailTab,
  readmeContent,
  readmeLoading,
  aiResearchPromptGenerationDialogVisible,
  aiResearchPromptGenerationMode,
  aiResearchPromptGenerationLoading,
  form,
  aiResearchHeroSteps,
  aiResearchHeroMetrics,
  strategies,
  loading,
  filteredTemplates,
  displayedTemplates,
  strategyManagementStats,
  paramTableData,
  openTemplateDetail,
  goBacktest,
  closeAIResearchPromptGenerationDialog,
  confirmAIResearchPromptGeneration,
  showCreateDialog,
  editStrategy,
  viewStrategy,
  useTemplate,
  updateStrategyForm,
  saveStrategy,
  deleteStrategy,
} = strategyPage

defineExpose(strategyPage)
</script>
<style scoped src="./StrategyPage.css" />
