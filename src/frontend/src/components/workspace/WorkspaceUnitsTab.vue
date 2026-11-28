<template>
  <div class="workspace-units-tab">
    <teleport
      to="#page-header-actions"
      :disabled="!props.toolbarInHeader || !props.active"
    >
      <ResearchUnitActionsBar
        :compact="true"
        :class="props.toolbarInHeader && props.active ? 'mb-0' : 'mb-4'"
        :has-selection="hasSelection"
        :has-single-selection="hasSingleSelection"
        :has-openable-selected-report="hasOpenableSelectedReport"
        :running="store.running"
        :batch-submitting-optimization="batchSubmittingOptimization"
        :unit-count="store.units.length"
        @run-serial="handleRunSelected(false)"
        @run-parallel="handleRunSelected(true)"
        @stop-selected="handleStopSelected"
        @reload-strategy="handleReloadStrategy"
        @create-unit="showCreateUnit = true"
        @delete-selected="handleBulkDelete"
        @import-units="handleImportUnits"
        @export-units="handleExportUnits"
        @open-data-source="showDataSource = true"
        @open-unit-settings="showUnitSettings = true"
        @open-strategy-params="showStrategyParams = true"
        @open-change-symbol="showChangeSymbol = true"
        @open-kline="handleOpenKline"
        @open-selected-report="handleOpenSelectedReport"
        @open-opt-config="showOptConfig = true"
        @open-opt-thread="showOptThread = true"
        @open-batch-opt-config="showBatchOptConfig = true"
        @submit-batch-opt="handleBatchSubmitOpt"
        @copy-opt-params="handleCopyOptParams"
        @open-opt-results="emit('switch-tab', 'optimization', store.selectedUnitIds[0])"
        @open-multi-task-report="emit('switch-tab', 'report', store.selectedUnitIds[0], [...store.selectedUnitIds])"
        @open-group-rename="showGroupRename = true"
        @open-unit-rename="showUnitRename = true"
        @move-up="handleMove('up')"
        @move-down="handleMove('down')"
        @move-top="handleMove('top')"
        @move-bottom="handleMove('bottom')"
      />
    </teleport>

    <!-- Strategy Unit Table -->
    <el-table
      :data="store.units"
      stripe
      border
      size="small"
      :empty-text="t('units.emptyUnits') + '，' + t('units.clickToCreate') + ' + ' + t('units.create')"
      @selection-change="onSelectionChange"
      @row-dblclick="handleRowDblClick"
    >
      <el-table-column
        type="selection"
        width="40"
      />
      <el-table-column
        label="#"
        width="50"
        align="center"
      >
        <template #default="{ row }">
          {{ row.sort_order + 1 }}
        </template>
      </el-table-column>
      <el-table-column
        prop="group_name"
        :label="t('units.groupName')"
        min-width="120"
        show-overflow-tooltip
      />
      <el-table-column
        prop="strategy_name"
        :label="t('units.strategyName')"
        min-width="120"
        show-overflow-tooltip
      />
      <el-table-column
        prop="symbol"
        :label="t('units.code')"
        width="80"
      />
      <el-table-column
        prop="symbol_name"
        :label="t('units.name')"
        width="100"
        show-overflow-tooltip
      />
      <el-table-column
        prop="timeframe"
        :label="t('units.timeframe')"
        width="70"
        align="center"
      />
      <el-table-column
        prop="category"
        :label="t('units.category')"
        width="80"
        show-overflow-tooltip
      />
      <el-table-column
        :label="t('units.rangeStartDate')"
        width="150"
      >
        <template #default="{ row }">
          {{ formatDate(row.data_config?.start_date) }}
        </template>
      </el-table-column>
      <el-table-column
        :label="t('units.rangeEndDate')"
        width="150"
      >
        <template #default="{ row }">
          {{ row.data_config?.use_end_date ? formatDate(row.data_config?.end_date) : '-' }}
        </template>
      </el-table-column>
      <el-table-column
        :label="'bar ' + t('units.countSuffix')"
        width="70"
        align="center"
      >
        <template #default="{ row }">
          {{ row.bar_count ?? '-' }}
        </template>
      </el-table-column>
      <el-table-column
        :label="t('units.strategyTarget')"
        width="100"
        align="center"
      >
        <template #default="{ row }">
          {{ objectiveLabel(row.optimization_config?.objective, row.optimization_config?.direction) }}
        </template>
      </el-table-column>
      <!-- @vue-generic {typeof store.units[number]} -->
      <el-table-column
        :label="t('units.runStatus')"
        width="120"
        align="center"
      >
        <template #default="{ row }">
          <div class="unit-status-cell">
            <template v-if="shouldShowOptimizationProgress(row)">
              <span class="unit-status-count">{{ formatOptimizationCount(row) }}</span>
              <el-progress
                class="unit-status-progress"
                :percentage="optimizationProgressPercent(row)"
                :stroke-width="6"
                :show-text="false"
              />
            </template>
            <template v-else-if="shouldShowOptimizationTerminal(row)">
              <el-tag
                :type="optimizationStatusTagType(row.opt_status)"
                size="small"
              >
                {{ optimizationStatusLabel(row.opt_status) }}
              </el-tag>
            </template>
            <template v-else>
              <el-tag
                :type="runStatusTagType(row.run_status)"
                size="small"
              >
                {{ runStatusLabel(row.run_status) }}
              </el-tag>
              <template v-if="shouldShowRunProgress(row)">
                <span class="unit-status-count">{{ runProgressLabel(row) }}</span>
                <el-progress
                  class="unit-status-progress"
                  :percentage="runProgressPercent(row)"
                  :status="runProgressStatus(row)"
                  :stroke-width="6"
                  :show-text="false"
                />
                <span
                  v-if="row.run_message"
                  class="unit-status-message"
                >
                  {{ row.run_message }}
                </span>
              </template>
            </template>
          </div>
        </template>
      </el-table-column>
      <!-- @vue-generic {typeof store.units[number]} -->
      <el-table-column
        label="结果"
        min-width="280"
      >
        <template #default="{ row }">
          <div class="unit-result-cell">
            <span
              class="unit-result-summary"
              :class="{ 'unit-result-summary--error': row.run_status === 'failed' }"
            >
              {{ unitResultSummary(row) }}
            </span>
            <el-button
              v-if="canOpenReport(row)"
              class="unit-result-action"
              size="small"
              link
              type="primary"
              @click.stop="openBacktestResult(row)"
            >
              <el-icon aria-hidden="true">
                <View />
              </el-icon>
              {{ t('units.viewResult') }}
            </el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        prop="run_count"
        :label="t('units.runCount')"
        width="80"
        align="center"
      />
      <!-- @vue-generic {typeof store.units[number]} -->
      <el-table-column
        :label="t('units.elapsed')"
        width="90"
        align="center"
      >
        <template #default="{ row }">
          {{ formatElapsedTime(row) }}
        </template>
      </el-table-column>
      <!-- @vue-generic {typeof store.units[number]} -->
      <el-table-column
        :label="t('units.remaining')"
        width="130"
        align="center"
      >
        <template #default="{ row }">
          {{ formatRemainingTime(row) }}
        </template>
      </el-table-column>
      <el-table-column
        :label="t('units.createdAt')"
        width="150"
      >
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
    </el-table>

    <!-- Create Unit Dialog -->
    <CreateUnitDialog
      v-model="showCreateUnit"
      :workspace-id="props.workspaceId"
      @created="onUnitCreated"
    />

    <!-- Data Source Dialog -->
    <DataSourceDialog
      v-model="showDataSource"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      workspace-type="research"
      @saved="onUnitUpdated"
    />

    <!-- Unit Settings Dialog -->
    <UnitSettingsDialog
      v-model="showUnitSettings"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      workspace-type="research"
      @saved="onUnitUpdated"
    />

    <!-- Strategy Params Dialog -->
    <StrategyParamsDialog
      v-model="showStrategyParams"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      workspace-type="research"
      @saved="onUnitUpdated"
    />

    <!-- Optimization Config Dialog -->
    <OptimizationConfigDialog
      v-model="showOptConfig"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      @saved="onUnitUpdated"
    />

    <!-- Optimization Thread Dialog -->
    <OptimizationThreadDialog
      v-model="showOptThread"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      @saved="onUnitUpdated"
    />

    <!-- Batch Optimization Config Dialog -->
    <BatchOptimizationConfigDialog
      v-model="showBatchOptConfig"
      :workspace-id="props.workspaceId"
      :unit-ids="store.selectedUnitIds"
      :units="store.units"
      @saved="onUnitUpdated"
    />

    <!-- Change Symbol Dialog -->
    <ChangeSymbolDialog
      v-model="showChangeSymbol"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      :selected-unit-ids="store.selectedUnitIds"
      @saved="onUnitsRefresh"
    />

    <!-- Hidden file input for import -->
    <input
      ref="importFileInput"
      type="file"
      accept=".json"
      style="display: none"
      @change="onImportFileSelected"
    >

    <!-- Group Rename Dialog -->
    <GroupRenameDialog
      v-model="showGroupRename"
      :workspace-id="props.workspaceId"
      :unit-ids="store.selectedUnitIds"
      @saved="onUnitsRefresh"
    />

    <!-- Unit Rename Dialog -->
    <UnitRenameDialog
      v-model="showUnitRename"
      :workspace-id="props.workspaceId"
      :unit="selectedUnit"
      @saved="onUnitsRefresh"
    />
  </div>
</template>

<script setup lang="ts">
import { View } from '@element-plus/icons-vue'
import { ResearchUnitActionsBar } from '@bt-api/workspace-ui/research'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import CreateUnitDialog from './CreateUnitDialog.vue'
import DataSourceDialog from './DataSourceDialog.vue'
import UnitSettingsDialog from './UnitSettingsDialog.vue'
import StrategyParamsDialog from './StrategyParamsDialog.vue'
import OptimizationConfigDialog from './OptimizationConfigDialog.vue'
import OptimizationThreadDialog from './OptimizationThreadDialog.vue'
import BatchOptimizationConfigDialog from './BatchOptimizationConfigDialog.vue'
import ChangeSymbolDialog from './ChangeSymbolDialog.vue'
import GroupRenameDialog from './GroupRenameDialog.vue'
import UnitRenameDialog from './UnitRenameDialog.vue'
import {
  useWorkspaceUnitsTab,
  type WorkspaceUnitsTabProps,
} from './units/useWorkspaceUnitsTab'

const props = defineProps<WorkspaceUnitsTabProps>()
const emit = defineEmits<{
  'switch-tab': [tab: string, unitId?: string, unitIds?: string[]]
}>()
useWorkspaceUiBridge()
const unitsPage = useWorkspaceUnitsTab(props)
const {
  batchSubmittingOptimization,
  canOpenReport,
  formatDate,
  formatElapsedTime,
  formatOptimizationCount,
  formatRemainingTime,
  formatTime,
  handleBatchSubmitOpt,
  handleBulkDelete,
  handleCopyOptParams,
  handleExportUnits,
  handleImportUnits,
  importFileInput,
  handleMove,
  handleOpenKline,
  handleOpenSelectedReport,
  handleReloadStrategy,
  handleRowDblClick,
  handleRunSelected,
  handleStopSelected,
  hasOpenableSelectedReport,
  hasSelection,
  hasSingleSelection,
  objectiveLabel,
  onImportFileSelected,
  onSelectionChange,
  onUnitCreated,
  onUnitUpdated,
  onUnitsRefresh,
  openBacktestResult,
  optimizationProgressPercent,
  optimizationStatusLabel,
  optimizationStatusTagType,
  runProgressLabel,
  runProgressPercent,
  runProgressStatus,
  runStatusLabel,
  runStatusTagType,
  selectedUnit,
  shouldShowOptimizationProgress,
  shouldShowOptimizationTerminal,
  shouldShowRunProgress,
  showBatchOptConfig,
  showChangeSymbol,
  showCreateUnit,
  showDataSource,
  showGroupRename,
  showOptConfig,
  showOptThread,
  showStrategyParams,
  showUnitRename,
  showUnitSettings,
  store,
  t,
  unitResultSummary,
} = unitsPage

defineExpose(unitsPage)
</script>

<style scoped>
.unit-status-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  min-width: 0;
}

.unit-status-count {
  font-size: 12px;
  line-height: 1;
  color: var(--el-text-color-secondary);
}

.unit-status-progress {
  width: 84px;
}

.unit-status-message {
  max-width: 108px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 11px;
  line-height: 1.2;
  color: var(--el-text-color-placeholder);
}

.unit-result-cell {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.unit-result-summary {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-regular);
  font-size: 12px;
  line-height: 1.4;
}

.unit-result-summary--error {
  color: var(--el-color-danger);
}

.unit-result-action {
  flex: 0 0 auto;
}
</style>
