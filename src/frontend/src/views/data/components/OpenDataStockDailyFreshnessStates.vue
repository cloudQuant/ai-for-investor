<template>
  <p
    v-if="display.status === 'idle'"
    role="status"
    data-test="opendata-stock-daily-freshness-idle"
  >
    {{ t('dataMgmt.stockDailyFreshnessIdle') }}
  </p>
  <p
    v-else-if="display.status === 'loading'"
    role="status"
    data-test="opendata-stock-daily-freshness-loading"
  >
    {{ t('dataMgmt.stockDailyFreshnessLoading') }}
  </p>
  <template v-else-if="display.status === 'unavailable'">
    <el-tag
      v-if="availability === 'opendata_unavailable'"
      type="warning"
      class="opendata-stock-daily-freshness-coverage-tag"
      data-test="opendata-stock-daily-freshness-coverage"
    >
      {{ t('dataMgmt.stockDailyFreshnessCoverage') }}:
      {{ t('dataMgmt.openDataCoverageState.opendata_unavailable') }}
    </el-tag>
    <el-alert
      type="warning"
      :closable="false"
      show-icon
      data-test="opendata-stock-daily-freshness-unavailable"
      :title="t('dataMgmt.stockDailyFreshnessUnavailable')"
    />
  </template>
  <template v-else-if="display.response">
    <el-tag
      :type="display.response.status === 'fresh'
        ? 'success'
        : display.response.status === 'stale'
          ? 'warning'
          : 'info'"
      data-test="opendata-stock-daily-freshness-status"
    >
      {{ t(`dataMgmt.stockDailyFreshnessStatus.${display.response.status}`) }}
    </el-tag>
    <el-tag
      v-if="availability"
      :type="availability === 'PROVEN'
        ? 'success'
        : availability === 'UNKNOWN'
          ? 'info'
          : 'warning'"
      class="opendata-stock-daily-freshness-coverage-tag"
      data-test="opendata-stock-daily-freshness-coverage"
    >
      {{ t('dataMgmt.stockDailyFreshnessCoverage') }}:
      {{ t(`dataMgmt.openDataCoverageState.${availability}`) }}
    </el-tag>
    <dl class="opendata-stock-daily-freshness-values">
      <div>
        <dt>{{ t('dataMgmt.stockDailyFreshnessProvenance') }}</dt>
        <dd data-test="opendata-stock-daily-freshness-provenance">
          {{ display.response.provider }} · {{ display.response.domain }}
        </dd>
      </div>
      <div>
        <dt>{{ t('dataMgmt.stockDailyFreshnessExpectedDate') }}</dt>
        <dd>{{ display.response.expected_data_date }}</dd>
      </div>
      <div v-if="display.response.status !== 'missing'">
        <dt>{{ t('dataMgmt.stockDailyFreshnessLatestDate') }}</dt>
        <dd>{{ display.response.latest }}</dd>
      </div>
      <div v-if="display.response.status !== 'missing'">
        <dt>{{ t('dataMgmt.stockDailyFreshnessDateDifference') }}</dt>
        <dd>{{ display.response.lag_days }}</dd>
      </div>
      <div v-if="display.response.status !== 'missing'">
        <dt>{{ t('dataMgmt.stockDailyFreshnessField') }}</dt>
        <dd>{{ display.response.field }}</dd>
      </div>
      <div>
        <dt>{{ t('dataMgmt.stockDailyFreshnessAsOf') }}</dt>
        <dd data-test="opendata-stock-daily-freshness-as-of">
          {{ display.response.checked_at }}
        </dd>
      </div>
    </dl>
    <p
      v-if="display.response.status === 'missing'"
      class="opendata-stock-daily-freshness-missing"
      data-test="opendata-stock-daily-freshness-missing"
    >
      {{ t('dataMgmt.stockDailyFreshnessMissingMeaning') }}
    </p>
  </template>
</template>

<script setup lang="ts">
import { useI18n } from 'vue-i18n'

import type {
  OpenDataAvailabilityState,
  OpenDataStockDailyFreshnessDisplayState,
} from '@/api/openDataCoverage'

const { t } = useI18n()

defineProps<{
  display: OpenDataStockDailyFreshnessDisplayState
  availability: OpenDataAvailabilityState | null
}>()
</script>

<style scoped>
.opendata-stock-daily-freshness-values {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px 20px;
  margin: 16px 0 0;
}

.opendata-stock-daily-freshness-values dt {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.opendata-stock-daily-freshness-values dd {
  margin: 4px 0 0;
  overflow-wrap: anywhere;
}

.opendata-stock-daily-freshness-missing {
  margin: 14px 0 0;
  color: var(--el-text-color-secondary);
}

.opendata-stock-daily-freshness-coverage-tag {
  margin: 8px 0 0;
}
</style>
