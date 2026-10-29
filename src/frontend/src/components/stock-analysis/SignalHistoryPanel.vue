<template>
  <section
    class="signal-panel"
    aria-labelledby="signal-history-title"
  >
    <div class="panel-head">
      <div>
        <span class="panel-kicker">{{ t('stockAnalysis.signalHistoryKicker') }}</span>
        <h3 id="signal-history-title">
          {{ t('stockAnalysis.signalHistoryTitle') }}
        </h3>
      </div>
      <span class="signal-note">{{ t('stockAnalysis.signalHistoryNote') }}</span>
    </div>

    <p
      v-if="loading"
      class="signal-empty"
    >
      {{ t('common.loading') }}
    </p>
    <p
      v-else-if="!items.length"
      class="signal-empty"
    >
      {{ t('stockAnalysis.signalHistoryEmpty') }}
    </p>
    <div
      v-else
      class="signal-table-wrap"
    >
      <table class="signal-table">
        <thead>
          <tr>
            <th>{{ t('stockAnalysis.signalDate') }}</th>
            <th>{{ t('stockAnalysis.signalSource') }}</th>
            <th>{{ t('stockAnalysis.signalAction') }}</th>
            <th>{{ t('stockAnalysis.signalConfidence') }}</th>
            <th>{{ t('stockAnalysis.signalOutcome') }}</th>
            <th>{{ t('stockAnalysis.signalReturn20d') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in items"
            :key="item.id"
          >
            <td>{{ item.as_of_date }}</td>
            <td>{{ sourceLabel(item.source) }}</td>
            <td>
              <span :class="['action-badge', item.signal_action.toLowerCase()]">{{ item.action_label }}</span>
              <small v-if="item.eligibility_status !== 'eligible'">{{ qualityLabel(item.eligibility_status) }}</small>
            </td>
            <td>{{ percent(item.confidence_score) }}</td>
            <td>{{ outcomeLabel(item) }}</td>
            <td>
              <div class="return-values">
                <span>{{ t('stockAnalysis.signalStockReturn', { value: percent(item.horizon_20d_return) }) }}</span>
                <small
                  class="benchmark-return"
                  :data-benchmark-status="benchmarkStatus(item)"
                >
                  {{ benchmarkReturnLabel(item) }}
                </small>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type { StockSignalEligibility, StockSignalRecord } from '@/api/stockAnalysis'

defineProps<{
  items: StockSignalRecord[]
  loading?: boolean
}>()

const { t } = useI18n()

function percent(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : '—'
}

function benchmarkReturnLabel(item: StockSignalRecord): string {
  const value = item.benchmark_20d_return
  if (typeof value === 'number' && Number.isFinite(value)) {
    return t('stockAnalysis.signalBenchmarkReturn', {
      value: percent(value),
    })
  }

  // Older API payloads omit benchmark_status. A missing value does not prove
  // that the source lacked benchmark data, so preserve the uncertainty.
  return t('stockAnalysis.signalBenchmarkUnknown')
}

function benchmarkStatus(item: StockSignalRecord): 'available' | 'unknown' {
  const hasReturn =
    typeof item.benchmark_20d_return === 'number' && Number.isFinite(item.benchmark_20d_return)
  if (hasReturn) {
    return 'available'
  }
  // A status without the corresponding 20-day value cannot support a displayed
  // benchmark result; keep the UI conservative if a payload is inconsistent.
  if (item.benchmark_status === 'available') return 'unknown'
  return item.benchmark_status ?? 'unknown'
}

function qualityLabel(status: StockSignalEligibility): string {
  return status === 'degraded'
    ? t('stockAnalysis.signalDegraded')
    : t('stockAnalysis.signalRejected')
}

function outcomeLabel(item: StockSignalRecord): string {
  if (item.outcome_status === 'scored') return t('stockAnalysis.signalScored')
  if (item.outcome_status === 'partial') return t('stockAnalysis.signalPartial')
  if (item.outcome_status === 'unscorable') return t('stockAnalysis.signalUnscorable')
  return t('stockAnalysis.signalPending')
}

function sourceLabel(source: string): string {
  return source === 'nightly_sse50'
    ? t('stockAnalysis.signalSourceNightly')
    : t('stockAnalysis.signalSourceManual')
}
</script>

<style scoped>
.signal-panel {
  padding: 20px;
  border: 1px solid var(--border-color-light);
  border-radius: 16px;
  background: var(--bg-color-overlay);
}

.panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.panel-kicker { display: block; color: var(--el-color-primary); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; }
h3 { margin: 4px 0 0; font-size: 18px; }
.signal-note, small { color: var(--text-color-secondary); font-size: 12px; }
.signal-empty { margin: 18px 0 0; color: var(--text-color-secondary); }
.signal-table-wrap { overflow-x: auto; margin-top: 16px; }
.signal-table { width: 100%; border-collapse: collapse; min-width: 680px; font-size: 13px; }
th, td { padding: 10px 8px; border-bottom: 1px solid var(--border-color-lighter); text-align: left; }
th { color: var(--text-color-secondary); font-weight: 600; }
.return-values { display: flex; flex-direction: column; gap: 3px; }
.benchmark-return { margin-top: 0; }
.action-badge { display: inline-flex; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.buy { color: var(--el-color-success); background: var(--el-color-success-light-9); }
.sell { color: var(--el-color-danger); background: var(--el-color-danger-light-9); }
.watch { color: var(--el-color-warning); background: var(--el-color-warning-light-9); }
small { display: block; margin-top: 3px; }
</style>
