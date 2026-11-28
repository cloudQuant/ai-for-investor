<template>
  <SharedPositionManagerDialog
    ref="innerRef"
    :model-value="modelValue"
    mode="aggregated"
    :title="t('workspaceDialogs.positionMgrTitle')"
    :labels="labels"
    :load-aggregated="handleLoadAggregated"
    :format-valuation-label="valuationStatusLabel"
    :format-valuation-tooltip="valuationTooltip"
    :on-error="handleLoadError"
    @update:model-value="emit('update:modelValue', $event)"
  />
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import {
  formatPositionQuantity,
  PositionManagerDialog as SharedPositionManagerDialog,
  type AggregatedPositionRow,
} from '@bt-api/workspace-ui/trading'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { workspaceApi } from '@/api/workspace'
import { getErrorMessage } from '@/api/index'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  modelValue: boolean
  workspaceId: string
  unitIds?: string[]
}>()

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

const innerRef = ref<InstanceType<typeof SharedPositionManagerDialog> | null>(null)

const labels = computed(() => ({
  instrument: t('workspaceDialogs.pmColSymbol'),
  symbolName: t('workspaceDialogs.pmColSymbolName'),
  mode: t('workspaceDialogs.pmColMode'),
  modeLive: t('workspaceDialogs.pmModeLive'),
  modeSim: t('workspaceDialogs.pmModeSim'),
  avgPrice: t('workspaceDialogs.pmColAvgPrice'),
  lastPrice: t('workspaceDialogs.pmColLatestPrice'),
  pnl: t('workspaceDialogs.pmColPositionPnl'),
  marketValue: t('workspaceDialogs.pmColMarketValue'),
  marginValue: t('workspaceDialogs.pmColMarginValue'),
  leverage: t('workspaceDialogs.leverage'),
  commission: t('workspaceDialogs.pmColCommission'),
  valuationStatus: t('workspaceDialogs.pmColValuationStatus'),
  amountWan: t('workspaceDialogs.pmAmountWan'),
  amountYi: t('workspaceDialogs.pmAmountYi'),
  aggSummaryPrefix: t('workspaceDialogs.pmCurrentDisplay'),
  aggSummarySuffix: t('workspaceDialogs.pmAggUnitsSuffix'),
  emptyText: t('workspaceDialogs.pmEmpty'),
}))

async function handleLoadAggregated(): Promise<AggregatedPositionRow[]> {
  const response = await workspaceApi.getTradingPositions(props.workspaceId, props.unitIds)
  return response.positions as unknown as AggregatedPositionRow[]
}

function handleLoadError(error: unknown): void {
  ElMessage.error(getErrorMessage(error, t('workspaceDialogs.pmLoadFailed')))
}

function positionSourceLabel(value: string | null | undefined): string {
  const source = String(value || '').toLowerCase()
  if (source === 'gateway') return t('workspaceDialogs.pmSourceGateway')
  if (source === 'log') return t('workspaceDialogs.pmSourceLog')
  if (source === 'snapshot') return t('workspaceDialogs.pmSourceSnapshot')
  if (source === 'mixed') return t('workspaceDialogs.pmSourceMixed')
  return t('workspaceDialogs.pmSourceUnknown')
}

function valuationStatusLabel(row: AggregatedPositionRow): string {
  const status = String(row.valuation_status || '').toLowerCase()
  if (row.position_source === 'gateway' && status === 'confirmed') return t('workspaceDialogs.pmValuationGatewayConfirmed')
  if (status === 'stale_fallback') return t('workspaceDialogs.pmValuationStale')
  if (status === 'estimated' || (row.valuation_warnings?.length ?? 0) > 0) return t('workspaceDialogs.pmValuationEstimated')
  return t('workspaceDialogs.pmValuationUnknown')
}

function valuationTooltip(row: AggregatedPositionRow): string {
  const warnings = row.valuation_warnings?.filter(Boolean) ?? []
  if (warnings.length > 0) return warnings.join('；')
  const assetSource = row.asset_spec_source || '-'
  return `${t('workspaceDialogs.pmPositionSource')}: ${positionSourceLabel(row.position_source)}；${t('workspaceDialogs.pmAssetSpecSource')}: ${assetSource}`
}

const positions = computed(() => innerRef.value?.positions ?? [])
const summary = computed(() => innerRef.value?.summary ?? { total_long_value: 0, total_short_value: 0, total_pnl: 0 })
const loading = computed(() => Boolean(innerRef.value?.loading))

async function loadPositions(): Promise<void> {
  await innerRef.value?.loadPositions()
}

defineExpose({
  positions,
  summary,
  loading,
  loadPositions,
  formatQuantity: formatPositionQuantity,
})
</script>
