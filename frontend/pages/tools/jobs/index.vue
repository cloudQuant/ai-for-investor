<template>
  <div class="jobs-page">
    <header class="page-header">
      <div>
        <h1>工具运行历史</h1>
        <p>查看你的工具任务状态、结果摘要和历史记录。</p>
      </div>
      <NuxtLink to="/tools" class="secondary-link">返回工具列表</NuxtLink>
    </header>

    <div v-if="pending" class="state-card">加载运行历史中...</div>
    <div v-else-if="error" class="state-card error">运行历史加载失败，请确认已登录并完成邮箱验证。</div>
    <div v-else-if="jobs.length === 0" class="state-card">暂无工具运行记录。</div>
    <div v-else class="jobs-list">
      <NuxtLink
        v-for="job in jobs"
        :key="job.job_id"
        :to="`/tools/jobs/${job.job_id}`"
        class="job-card"
      >
        <div class="job-main">
          <span :class="['status-badge', job.status]">{{ getStatusLabel(job.status) }}</span>
          <strong>{{ job.job_id }}</strong>
        </div>
        <p class="job-summary">{{ getJobPreview(job) }}</p>
        <div class="job-meta">
          <span>工具 ID: {{ job.tool_id }}</span>
          <span>排队时间: {{ formatDate(job.queued_at) }}</span>
        </div>
      </NuxtLink>
    </div>
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

const { data, pending, error } = await useAsyncData('tool-jobs', () =>
  $api.get('/tools/jobs')
)

const jobs = computed<ToolJob[]>(() => data.value?.data || [])

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

const getJobPreview = (job: ToolJob) => {
  if (job.status === 'succeeded') {
    return job.result_summary || '任务已完成，暂无结果摘要。'
  }
  if (job.status === 'failed' || job.status === 'timeout') {
    return job.error_message || '任务未能完成。'
  }
  if (job.status === 'running') {
    return '任务正在运行，请稍后查看结果。'
  }
  return '任务已进入队列，等待 worker 执行。'
}

const formatDate = (value?: string | null) => {
  if (!value) return '未记录'
  return new Date(value).toLocaleString('zh-CN')
}

useHead({
  title: '工具运行历史 - AI For Investor',
})
</script>

<style scoped>
.jobs-page {
  max-width: 960px;
  margin: 0 auto;
  padding: var(--space-4) 0;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
  align-items: flex-start;
  margin-bottom: var(--space-6);
}

.page-header h1 {
  font-size: var(--font-size-2xl);
  margin-bottom: var(--space-2);
}

.page-header p,
.job-summary,
.job-meta {
  color: var(--color-text-muted);
}

.secondary-link {
  color: var(--color-primary);
  text-decoration: none;
  white-space: nowrap;
}

.state-card,
.job-card {
  display: block;
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface);
}

.jobs-list {
  display: grid;
  gap: var(--space-4);
}

.job-card {
  text-decoration: none;
  color: inherit;
  transition: all 0.2s;
}

.job-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card);
}

.job-main,
.job-meta {
  display: flex;
  justify-content: space-between;
  gap: var(--space-4);
}

.job-main {
  align-items: center;
  margin-bottom: var(--space-3);
}

.job-summary {
  margin-bottom: var(--space-3);
}

.job-meta {
  font-size: var(--font-size-xs);
}

.status-badge {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  color: white;
  background-color: var(--color-text-muted);
}

.status-badge.queued {
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

.error {
  color: var(--color-danger);
}
</style>
