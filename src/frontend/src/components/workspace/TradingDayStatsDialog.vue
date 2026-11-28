<template>
  <SharedTradingDayStatsDialog
    :model-value="modelValue"
    schema-mode="summary"
    :title="t('workspaceDialogs.tdsTitle')"
    :unit-options="unitOptions"
    :labels="labels"
    :load-summary-stats="handleLoadSummary"
    :on-error="handleLoadError"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import type { SummaryDailyStatsRow } from '@bt-api/workspace-ui/core'
import { TradingDayStatsDialog as SharedTradingDayStatsDialog } from '@bt-api/workspace-ui/trading'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { workspaceApi } from '@/api/workspace'
import { getErrorMessage } from '@/api/index'
import { useWorkspaceStore } from '@/stores/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const store = useWorkspaceStore()

const unitOptions = computed(() =>
  store.units.map(unit => ({
    id: unit.id,
    label: unit.strategy_name || unit.strategy_id || unit.id,
  })),
)

const labels = computed(() => ({
  day: t('workspaceDialogs.tdsColDate'),
  dailyPnl: t('workspaceDialogs.tdsColDailyPnl'),
  tradeCount: t('workspaceDialogs.tdsColTradeCount'),
  cumPnl: t('workspaceDialogs.tdsColCumulativePnl'),
  maxDrawdown: t('workspaceDialogs.tdsColMaxDrawdown'),
  startDatePlaceholder: t('workspaceDialogs.tdsStartDate'),
  endDatePlaceholder: t('workspaceDialogs.tdsEndDate'),
  queryBtn: t('workspaceDialogs.tdsQuery'),
  resetBtn: t('workspaceDialogs.tdsReset'),
  emptyText: t('workspaceDialogs.tdsEmpty'),
}))

async function handleLoadSummary(query: {
  unit_id?: string
  start_date?: string
  end_date?: string
}): Promise<SummaryDailyStatsRow[]> {
  const response = await workspaceApi.getTradingDailySummary(props.workspaceId, query)
  return response.summaries
}

function handleLoadError(error: unknown): void {
  ElMessage.error(getErrorMessage(error, t('workspaceDialogs.tdsLoadFailed')))
}
</script>
