<template>
  <section class="analytics-panel" data-test="portfolio-analytics-task-panel">
    <header>
      <h3>离线组合分析 / Offline portfolio analytics</h3>
      <p>
        Risk 会按版本计算敞口/回撤、VaR/ES 与情景结果。输入必须是带来源、版本和时间切片的 V2 快照；
        缺失数据请保留为 unavailable，不能填成零。此入口不读取账户、不连接 provider，也不授予交易权限。
      </p>
    </header>

    <p v-if="sourceType === 'live'" class="analytics-panel__unavailable" role="status">
      Live 组合不接受离线分析输入。请切换到 research、imported 或 paper 的固定版本。
    </p>

    <template v-else>
      <p class="analytics-panel__selection">
        {{ portfolioRef }} · membership v{{ membershipVersion }} · {{ sourceType }}
      </p>
      <label for="portfolio-analytics-input-file">读取已有 V2 JSON 文件</label>
      <input
        id="portfolio-analytics-input-file"
        type="file"
        accept="application/json,.json"
        data-test="portfolio-analytics-input-file"
        :disabled="loading"
        @change="readFile"
      >
      <label for="portfolio-analytics-input">V2 facts 与 request</label>
      <textarea
        id="portfolio-analytics-input"
        v-model="rawInput"
        rows="14"
        spellcheck="false"
        data-test="portfolio-analytics-input"
        placeholder="粘贴包含 facts 与 request 的离线 JSON；本页不会填充价格、FX、NAV 或损失样本。"
        :disabled="loading"
      />
      <div class="analytics-panel__actions">
        <button
          type="button"
          data-test="portfolio-analytics-submit"
          :disabled="loading || !rawInput.trim()"
          @click="submit"
        >
          {{ loading ? '处理中…' : '提交离线分析' }}
        </button>
        <button
          v-if="task && (task.state === 'pending' || task.state === 'running')"
          type="button"
          data-test="portfolio-analytics-cancel"
          :disabled="loading"
          @click="cancel"
        >
          取消任务
        </button>
        <button
          v-if="task && !polling && (task.state === 'pending' || task.state === 'running')"
          type="button"
          data-test="portfolio-analytics-refresh"
          :disabled="loading"
          @click="refresh"
        >
          刷新状态
        </button>
      </div>
    </template>

    <p v-if="errorMessage" class="analytics-panel__error" role="alert" data-test="portfolio-analytics-error">
      {{ errorMessage }}
    </p>
    <div v-if="task" class="analytics-panel__task" data-test="portfolio-analytics-task">
      <p>任务状态：<strong>{{ task.state }}</strong></p>
      <p v-if="task.detail_code">诊断码：<code>{{ task.detail_code }}</code></p>
      <p>输入摘要：<code>{{ task.input_sha256 }}</code></p>
      <p>任务摘要：<code>{{ task.task_ref }}</code></p>
      <pre v-if="task.result" data-test="portfolio-analytics-result">{{ JSON.stringify(task.result, null, 2) }}</pre>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'

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
  return typeof code === 'string' ? `分析任务未完成：${code}` : '分析请求失败，请检查输入或稍后重试。'
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
