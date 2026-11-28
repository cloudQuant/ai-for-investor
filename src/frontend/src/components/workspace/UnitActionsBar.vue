<template>
  <TradingUnitActionsBar
    class="trading-toolbar"
    :class="toolbarInHeader && active ? 'mb-0' : 'mb-4'"
    :compact="true"
    :has-selection="hasSelection"
    :has-single-selection="hasSingleSelection"
    :running="running"
    :auto-trading-enabled="autoTradingEnabled"
    :auto-trading-loading="autoTradingLoading"
    :auto-trading-schedule-summary="autoTradingScheduleSummary"
    :selected-count="selectedCount"
    :unit-count="unitCount"
    :export-requires-selection="true"
    :capabilities="TRADING_FULL_CAPABILITIES"
    @select-all-toggle="emit('selectAll')"
    @enable-auto-trading="emit('enableAutoTrading')"
    @disable-auto-trading="emit('disableAutoTrading')"
    @lock-trading="emit('lockTrading')"
    @lock-running="emit('lockRunning')"
    @unlock="emit('unlock')"
    @start-selected="emit('startSelected')"
    @stop-selected="emit('stopSelected')"
    @add-units="emit('createUnit')"
    @remove-selected="emit('bulkDelete')"
    @import-units="emit('importUnits')"
    @export-units="emit('exportUnits')"
    @open-data-source="emit('openDataSource')"
    @open-unit-settings="emit('openUnitSettings')"
    @open-strategy-params="emit('openStrategyParams')"
    @open-position-manager="emit('openPositionManager')"
    @open-market-chart="emit('openKline')"
    @open-report="emit('openReport')"
    @open-auto-trading-config="emit('openAutoTradingConfig')"
    @open-daily-stats="emit('openTradingDayStats')"
    @open-group-link="emit('openGroupLink')"
  >
    <template #optimization-actions>
      <el-tooltip
        :content="t('workspaceDialogs.newOptTask')"
        placement="top"
      >
        <el-button
          size="small"
          :disabled="!hasSelection"
          @click="emit('createOptimizationTask')"
        >
          <el-icon aria-hidden="true">
            <Promotion />
          </el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip
        :content="t('workspaceDialogs.openOptResults')"
        placement="top"
      >
        <el-button
          size="small"
          :disabled="!hasSingleSelection"
          @click="emit('openOptimization')"
        >
          <el-icon aria-hidden="true">
            <DataAnalysis />
          </el-icon>
        </el-button>
      </el-tooltip>
      <el-tooltip
        :content="t('workspaceDialogs.scheduledOptTitle')"
        placement="top"
      >
        <el-button
          size="small"
          @click="emit('openScheduledOptimization')"
        >
          <el-icon aria-hidden="true">
            <Calendar />
          </el-icon>
        </el-button>
      </el-tooltip>
    </template>

    <template #meta>
      <div class="trading-toolbar__meta">
        <el-tag
          size="small"
          effect="dark"
          :type="autoTradingEnabled ? 'success' : 'info'"
        >
          {{ t('workspaceDialogs.autoTradingTitleAlt') }}{{ autoTradingEnabled ? t('workspaceDialogs.enabledStatus') : t('workspaceDialogs.disabledStatus') }}
        </el-tag>
        <span
          v-if="autoTradingScheduleSummary"
          class="text-slate-500"
        >
          {{ autoTradingScheduleSummary }}
        </span>
        <span class="text-slate-500">{{ t('workspaceDialogs.selectedSuffix') }} {{ selectedCount }} / {{ unitCount }}</span>
      </div>
    </template>
  </TradingUnitActionsBar>
</template>

<script setup lang="ts">
import { Calendar, DataAnalysis, Promotion } from '@element-plus/icons-vue'
import { TRADING_FULL_CAPABILITIES } from '@bt-api/workspace-ui/core'
import { TradingUnitActionsBar } from '@bt-api/workspace-ui/trading'
import { useI18n } from 'vue-i18n'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'

const { t } = useI18n()
useWorkspaceUiBridge()

defineProps<{
  active?: boolean
  toolbarInHeader?: boolean
  hasSelection: boolean
  hasSingleSelection: boolean
  running: boolean
  autoTradingEnabled: boolean
  autoTradingLoading: boolean
  autoTradingScheduleSummary: string
  selectedCount: number
  unitCount: number
}>()

const emit = defineEmits<{
  selectAll: []
  enableAutoTrading: []
  disableAutoTrading: []
  lockTrading: []
  lockRunning: []
  unlock: []
  startSelected: []
  stopSelected: []
  createUnit: []
  bulkDelete: []
  importUnits: []
  exportUnits: []
  openDataSource: []
  openUnitSettings: []
  openStrategyParams: []
  openPositionManager: []
  openKline: []
  openReport: []
  openAutoTradingConfig: []
  createOptimizationTask: []
  openOptimization: []
  openScheduledOptimization: []
  openTradingDayStats: []
  openGroupLink: []
}>()
</script>

<style scoped>
.trading-toolbar__meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  font-size: 12px;
}
</style>
