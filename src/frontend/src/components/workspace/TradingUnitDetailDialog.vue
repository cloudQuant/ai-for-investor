<template>
  <SharedTradingUnitDetailDialog
    :model-value="visible"
    mode="snapshot"
    :title="t('tradingUnits.unitDetail')"
    :snapshot="snapshotData"
    :allow-open-directory="true"
    :snapshot-labels="snapshotLabels"
    :format-direction="formatDirection"
    :format-trade-time="formatTradeTime"
    @update:model-value="emit('update:visible', $event)"
    @open-logs="detailUnit && emit('openRuntimeDialog', detailUnit)"
    @open-runtime-dir="detailUnit && emit('openRuntimeDirectory', detailUnit)"
  />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { SnapshotUnitDetailData } from '@bt-api/workspace-ui/core'
import { TradingUnitDetailDialog as SharedTradingUnitDetailDialog } from '@bt-api/workspace-ui/trading'
import { useWorkspaceUiBridge } from '@/composables/useWorkspaceUiBridge'
import { directionLabel, formatTime, statusLabel } from '@/composables/useUnitTableRendering'
import type { StrategyUnit } from '@/types/workspace'

const { t } = useI18n()
useWorkspaceUiBridge()

const props = defineProps<{
  visible: boolean
  detailUnit: StrategyUnit | null
}>()

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'openRuntimeDialog', unit: StrategyUnit): void
  (e: 'openRuntimeDirectory', unit: StrategyUnit): void
}>()

const snapshotData = computed<SnapshotUnitDetailData | null>(() => {
  const unit = props.detailUnit
  if (!unit) return null
  const snap = unit.trading_snapshot
  return {
    id: unit.id,
    name: unit.strategy_name || unit.strategy_id || unit.id,
    symbol: unit.symbol,
    timeframe: unit.timeframe,
    trading_mode: unit.trading_mode === 'live' ? t('tradingUnits.liveTrading') : t('tradingUnits.paperTrading'),
    status_label: statusLabel(unit),
    gateway_summary: snap?.gateway_summary,
    instance_id: unit.trading_instance_id,
    updated_at: snap?.updated_at || formatTime(unit.updated_at),
    trading_day: snap?.trading_day,
    long_position: snap?.long_position,
    short_position: snap?.short_position,
    today_pnl: snap?.today_pnl,
    cumulative_pnl: snap?.cumulative_pnl,
    leverage: snap?.leverage,
    latest_price: snap?.latest_price,
    started_at: snap?.started_at,
    stopped_at: snap?.stopped_at,
    error: snap?.error,
    trades: (snap?.trades || []) as unknown as Array<Record<string, unknown>>,
  }
})

const snapshotLabels = computed(() => ({
  viewRunFile: t('tradingUnits.viewRunFile'),
  openUnit: t('tradingUnits.openUnit'),
  unit: t('tradingUnits.unit'),
  tradingMode: t('tradingUnits.tradingMode'),
  gateway: t('tradingUnits.gateway'),
  instance: t('tradingUnits.instance'),
  lastUpdate: t('tradingUnits.lastUpdate'),
  tradingDay: t('tradingUnits.tradingDay'),
  longShort: `${t('tradingUnits.longPosition')} / ${t('tradingUnits.flat')}`,
  todayPnl: t('tradingUnits.todayPnL'),
  cumPnl: t('tradingUnits.cumulativePnL'),
  leveragePrice: `${t('tradingUnits.leverage')} / ${t('tradingUnits.latestPrice')}`,
  runInfo: t('tradingUnits.runInfo'),
  runStarted: t('tradingUnits.runStarted'),
  runStopped: t('tradingUnits.runStopped'),
  errorInfo: t('tradingUnits.errorInfo'),
  tradeDetail: t('tradingUnits.tradeDetail'),
  noTradeDetail: t('tradingUnits.noTradeDetail'),
  colTradeId: t('tradingUnits.tradeId'),
  colContract: t('tradingUnits.contract'),
  colDirection: t('tradingUnits.direction'),
  colQty: t('tradingUnits.quantity'),
  colPrice: t('tradingUnits.tradePrice'),
  colNetPnl: t('tradingUnits.netPnL'),
  colCommission: t('tradingUnits.commission'),
  colOpenTime: t('tradingUnits.openTime'),
  colCloseTime: t('tradingUnits.closeTime'),
  colHoldingBars: t('tradingUnits.holdingBars'),
}))

function formatDirection(value: unknown): string {
  return directionLabel(typeof value === 'string' ? value : null)
}

function formatTradeTime(value: unknown): string {
  const text = String(value ?? '').trim()
  if (!text) return '-'
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return text
  const date = new Date(text.replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString('zh-CN')
}
</script>
