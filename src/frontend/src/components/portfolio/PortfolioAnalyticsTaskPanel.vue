<template>
  <section
    class="analytics-panel"
    data-test="portfolio-analytics-task-panel"
  >
    <header>
      <h3>{{ t('portfolio.analyticsTitle') }}</h3>
      <p>
        {{ t('portfolio.analyticsDescription') }}
      </p>
    </header>

    <p
      v-if="sourceType === 'live'"
      class="analytics-panel__unavailable"
      role="status"
    >
      {{ t('portfolio.analyticsLiveUnavailable') }}
    </p>

    <template v-else>
      <p class="analytics-panel__selection">
        {{ portfolioRef }} · membership v{{ membershipVersion }} · {{ sourceType }}
      </p>
      <label for="portfolio-analytics-input-file">{{ t('portfolio.analyticsReadFile') }}</label>
      <input
        id="portfolio-analytics-input-file"
        type="file"
        accept="application/json,.json"
        data-test="portfolio-analytics-input-file"
        :disabled="loading"
        @change="readFile"
      >
      <label for="portfolio-analytics-input">{{ t('portfolio.analyticsFactsAndRequest') }}</label>
      <textarea
        id="portfolio-analytics-input"
        v-model="rawInput"
        rows="14"
        spellcheck="false"
        data-test="portfolio-analytics-input"
        :placeholder="t('portfolio.analyticsPlaceholder')"
        :disabled="loading"
      />
      <div class="analytics-panel__actions">
        <button
          type="button"
          data-test="portfolio-analytics-submit"
          :disabled="loading || !rawInput.trim()"
          @click="submit"
        >
          {{ loading ? t('portfolio.analyticsProcessing') : t('portfolio.analyticsSubmit') }}
        </button>
        <button
          v-if="task && (task.state === 'pending' || task.state === 'running')"
          type="button"
          data-test="portfolio-analytics-cancel"
          :disabled="loading"
          @click="cancel"
        >
          {{ t('portfolio.analyticsCancelTask') }}
        </button>
        <button
          v-if="task && !polling && (task.state === 'pending' || task.state === 'running')"
          type="button"
          data-test="portfolio-analytics-refresh"
          :disabled="loading"
          @click="refresh"
        >
          {{ t('portfolio.analyticsRefreshStatus') }}
        </button>
      </div>
    </template>

    <p
      v-if="errorMessage"
      class="analytics-panel__error"
      role="alert"
      data-test="portfolio-analytics-error"
    >
      {{ errorMessage }}
    </p>
    <div
      v-if="task"
      class="analytics-panel__task"
      data-test="portfolio-analytics-task"
    >
      <p>{{ t('portfolio.analyticsTaskState') }}<strong>{{ task.state }}</strong></p>
      <p v-if="task.detail_code">
        {{ t('portfolio.analyticsDiagnosticCode') }}<code>{{ task.detail_code }}</code>
      </p>
      <p>{{ t('portfolio.analyticsInputSummary') }}<code>{{ task.input_sha256 }}</code></p>
      <p>{{ t('portfolio.analyticsTaskSummary') }}<code>{{ task.task_ref }}</code></p>
      <pre
        v-if="task.result"
        data-test="portfolio-analytics-result"
      >{{ JSON.stringify(task.result, null, 2) }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  type PortfolioAnalyticsFactsV2,
  type PortfolioAnalyticsRequestV2,
} from '@/api/portfolioAnalyticsTasks'
import { usePortfolioAnalyticsTask } from '@/composables/usePortfolioAnalyticsTask'

const props = defineProps<{
  portfolioRef: string
  membershipVersion: number
  sourceType: string
}>()

const { t } = useI18n()
const rawInput = ref('')
const runner = usePortfolioAnalyticsTask()
const task = runner.task
const loading = runner.loading
const polling = runner.polling
const error = runner.error
watch(
  () => [props.portfolioRef, props.membershipVersion, props.sourceType],
  () => {
    runner.reset()
    rawInput.value = ''
  },
)
const errorMessage = computed(() => {
  if (!error.value) return ''
  const response = (error.value as { response?: { data?: { detail?: { code?: unknown } } } })
    .response
  const code = response?.data?.detail?.code
  return typeof code === 'string'
    ? t('portfolio.analyticsTaskFailed', { code })
    : t('portfolio.analyticsRequestFailed')
})

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

async function readFile(event: Event) {
  const target = event.target
  if (!(target instanceof HTMLInputElement) || !target.files?.[0]) return
  if (target.files[0].size > 64 * 1024 * 1024) {
    error.value = new Error('INPUT_LIMIT_EXCEEDED')
    target.value = ''
    return
  }
  rawInput.value = await target.files[0].text()
}

async function submit() {
  try {
    const parsed: unknown = JSON.parse(rawInput.value)
    if (!isObject(parsed) || Object.keys(parsed).sort().join(',') !== 'facts,request') {
      throw new Error('INPUT_ENVELOPE_INVALID')
    }
    const facts = parsed.facts
    const request = parsed.request
    if (!isObject(facts) || !isObject(request) || facts.version !== 2 || request.version !== 2) {
      throw new Error('V2_INPUT_REQUIRED')
    }
    if (
      facts.portfolio_ref !== props.portfolioRef
      || request.portfolio_ref !== props.portfolioRef
      || facts.source_mode !== props.sourceType
    ) {
      throw new Error('SELECTED_VERSION_MISMATCH')
    }
    if (!['research', 'imported', 'paper'].includes(props.sourceType)) {
      throw new Error('OFFLINE_SOURCE_REQUIRED')
    }
    const payload = {
      idempotency_key: crypto.randomUUID(),
      facts: facts as unknown as PortfolioAnalyticsFactsV2,
      request: request as unknown as PortfolioAnalyticsRequestV2,
    }
    await runner.start(
      { portfolioRef: props.portfolioRef, membershipVersion: props.membershipVersion },
      payload,
    )
  } catch (caught) {
    error.value = caught
  }
}

async function refresh() {
  await runner.refresh()
}

async function cancel() {
  await runner.cancel()
}
</script>

<style scoped>
.analytics-panel {
  display: grid;
  gap: 0.75rem;
  margin-block: 1rem;
  padding: 1rem;
  border: 1px solid var(--el-border-color, #dcdfe6);
  border-radius: 0.5rem;
}

.analytics-panel header p,
.analytics-panel__selection {
  color: var(--el-text-color-secondary, #606266);
}

.analytics-panel textarea {
  width: 100%;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
}

.analytics-panel__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.analytics-panel__error,
.analytics-panel__unavailable {
  color: var(--el-color-danger, #f56c6c);
}

.analytics-panel pre {
  overflow: auto;
  max-height: 32rem;
  padding: 0.75rem;
  background: var(--el-fill-color-light, #f5f7fa);
}
</style>
