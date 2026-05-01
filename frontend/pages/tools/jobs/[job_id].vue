<template>
  <div class="job-detail-page">
    <NuxtLink to="/tools/jobs" class="back-link">返回运行历史</NuxtLink>

    <div v-if="pending" class="state-card">加载任务详情中...</div>
    <div v-else-if="error" class="state-card error">任务详情加载失败，请确认这是你的任务记录。</div>
    <article v-else-if="job" class="job-detail-card">
      <header class="detail-header">
        <div>
          <h1>{{ job.job_id }}</h1>
          <p>工具 ID: {{ job.tool_id }}</p>
        </div>
        <span :class="['status-badge', job.status]">{{ getStatusLabel(job.status) }}</span>
      </header>

      <section class="timeline-grid">
        <div class="timeline-item">
          <span>排队时间</span>
          <strong>{{ formatDate(job.queued_at) }}</strong>
        </div>
        <div class="timeline-item">
          <span>开始时间</span>
          <strong>{{ formatDate(job.started_at) }}</strong>
        </div>
        <div class="timeline-item">
          <span>完成时间</span>
          <strong>{{ formatDate(job.completed_at) }}</strong>
        </div>
      </section>

      <section class="content-section">
        <h2>运行参数</h2>
        <pre>{{ JSON.stringify(job.parameters, null, 2) }}</pre>
      </section>

      <section class="content-section">
        <h2>{{ resultTitle }}</h2>
        <div v-if="job.status === 'queued'" class="state-card inline">任务已进入队列，等待 worker 执行。</div>
        <div v-else-if="job.status === 'running'" class="state-card inline">任务正在运行，请稍后刷新查看结果。</div>
        <pre v-else-if="job.status === 'succeeded'">{{ job.result_summary || '任务已完成，暂无结果摘要。' }}</pre>
        <div v-else class="state-card inline error">{{ job.error_message || '任务未能完成。' }}</div>
      </section>
    </article>
    <div v-else class="state-card">任务不存在。</div>
  </div>
</template>

<script setup lang="ts">
interface ToolJob {
  id: number
  job_id: string
  tool_id: number
  user_id: number
  parameters: Record<string, unknown>
  status: string
  result_summary?: string | null
  error_message?: string | null
  queued_at: string
  started_at?: string | null
  completed_at?: string | null
}

const { $api } = useNuxtApp()
const route = useRoute()

const { data, pending, error } = await useAsyncData(
  () => `tool-job-${route.params.job_id}`,
  () => $api.get(`/tools/jobs/${route.params.job_id}`)
)

const job = computed<ToolJob | null>(() => data.value?.data || null)

const getStatusLabel = (status: string) => {
  const labels: Record<string, string> = {
    queued: '排队中',
    running: '运行中',
    succeeded: '已完成',
    failed: '失败',
    timeout: '超时',
  }
  return labels[status] || status
}

const formatDate = (value?: string | null) => {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN')
}

const resultTitle = computed(() => {
  if (!job.value) return '运行结果'
  if (job.value.status === 'failed' || job.value.status === 'timeout') return '失败原因'
  return '运行结果'
})

useHead({
  title: computed(() => job.value ? `${job.value.job_id} - 工具任务` : '工具任务详情 - AI For Investor'),
})
</script>

<style scoped>
.job-detail-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-4) 0;
}

.back-link {
  display: inline-block;
  margin-bottom: var(--space-4);
  color: var(--color-primary);
  text-decoration: none;
}

.job-detail-card,
.state-card {
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface);
}

.state-card.inline {
  padding: var(--space-4);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.detail-header h1 {
  font-size: var(--font-size-2xl);
  margin-bottom: var(--space-2);
}

.detail-header p,
.timeline-item span {
  color: var(--color-text-muted);
}

.status-badge {
  align-self: flex-start;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-full);
  color: white;
  background-color: var(--color-text-muted);
}

.status-badge.running {
  background-color: var(--color-primary);
}

.status-badge.succeeded {
  background-color: var(--color-success);
}

.status-badge.failed,
.status-badge.timeout {
  background-color: var(--color-danger);
}

.timeline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.timeline-item {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.timeline-item span {
  display: block;
  font-size: var(--font-size-xs);
  margin-bottom: var(--space-1);
}

.content-section {
  margin-top: var(--space-6);
}

.content-section h2 {
  margin-bottom: var(--space-3);
}

pre {
  overflow-x: auto;
  padding: var(--space-4);
  border-radius: var(--radius-md);
  background-color: var(--color-surface-muted);
  white-space: pre-wrap;
}

.error {
  color: var(--color-danger);
}
</style>
