<template>
  <div class="tools-page">
    <h1 class="page-title">工具</h1>
    <p class="page-desc">探索 AI 交易与投资领域的精选工具 Demo</p>

    <div v-if="pending" class="loading">加载中...</div>
    <div v-else-if="error" class="error">加载失败</div>
    <div v-else-if="tools.length" class="tools-grid">
      <NuxtLink
        v-for="tool in tools"
        :key="tool.id"
        :to="`/tools/${tool.slug}`"
        class="tool-card"
      >
        <div class="tool-header">
          <h3 class="tool-name">{{ tool.name }}</h3>
          <span :class="['risk-badge', tool.risk_level]">{{ getRiskLabel(tool.risk_level) }}</span>
        </div>
        <p class="tool-desc">{{ tool.description }}</p>
        <div class="tool-footer">
          <span v-if="tool.license" class="tool-license">{{ tool.license }}</span>
          <span :class="['tool-access', tool.access_type]">{{ getAccessLabel(tool.access_type) }}</span>
        </div>
      </NuxtLink>
    </div>
    <div v-else class="empty-state">
      <h2>暂无可公开体验的工具</h2>
      <p>工具上线前会经过安全审查、供应链检查和人工发布流程。你可以先浏览博客或开源项目库。</p>
      <NuxtLink to="/blog" class="empty-link">浏览博客</NuxtLink>
    </div>

    <div class="disclaimer-box">
      <span class="disclaimer-icon">⚠️</span>
      <p class="disclaimer-text">
        <strong>工具使用风险提示：</strong>所有工具仅供研究和学习使用。工具运行结果不代表任何投资建议。
        请勿将工具输出作为实际投资决策依据。
        <NuxtLink to="/legal/risk-disclaimer" class="disclaimer-link">查看金融风险免责声明</NuxtLink>
      </p>
    </div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()

const { data, pending, error } = await useAsyncData('tools', () =>
  $api.get('/tools/tools')
)
const tools = computed(() => data.value?.data || [])

const getRiskLabel = (level: string) => {
  const labels: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
    extreme: '极高风险',
  }
  return labels[level] || level
}

const getAccessLabel = (accessType: string) => {
  const labels: Record<string, string> = {
    runnable_demo: '可运行 Demo',
    external_demo: '外部 Demo',
    documentation_only: '仅文档',
  }
  return labels[accessType] || accessType
}

useHead({
  title: '工具 - AI For Investor',
})
</script>

<style scoped>
.tools-page {
  padding: var(--space-4) 0;
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: 700;
  margin-bottom: var(--space-2);
}

.page-desc {
  font-size: var(--font-size-md);
  color: var(--color-text-muted);
  margin-bottom: var(--space-8);
}

.tools-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: var(--space-4);
}

.tool-card {
  display: block;
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  transition: all 0.2s;
}

.tool-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card);
}

.tool-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: var(--space-3);
}

.tool-name {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--color-text);
}

.risk-badge {
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
}

.risk-badge.low {
  background-color: var(--color-success);
  color: white;
}

.risk-badge.medium {
  background-color: var(--color-warning);
  color: white;
}

.risk-badge.high,
.risk-badge.extreme {
  background-color: var(--color-danger);
  color: white;
}

.tool-desc {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
}

.tool-footer {
  display: flex;
  gap: var(--space-4);
  font-size: var(--font-size-xs);
  color: var(--color-text-subtle);
}

.tool-access {
  font-weight: 600;
}

.tool-access.runnable_demo {
  color: var(--color-primary);
}

.tool-access.documentation_only {
  color: var(--color-text-muted);
}

.tool-access.external_demo {
  color: var(--color-warning);
}

.loading,
.error,
.empty-state {
  padding: var(--space-8);
  text-align: center;
  color: var(--color-text-muted);
}

.empty-state {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface);
}

.empty-state h2 {
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.empty-state p {
  margin-bottom: var(--space-4);
}

.empty-link {
  color: var(--color-primary);
  text-decoration: none;
  font-weight: 600;
}

.disclaimer-box {
  margin-top: var(--space-8);
  background-color: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  display: flex;
  gap: var(--space-4);
}

.disclaimer-icon {
  font-size: var(--font-size-xl);
}

.disclaimer-text {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  line-height: 1.7;
}

.disclaimer-link {
  display: inline-block;
  margin-left: var(--space-2);
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}

@media (max-width: 640px) {
  .tools-grid {
    grid-template-columns: 1fr;
  }

  .tool-header,
  .tool-footer,
  .disclaimer-box {
    flex-direction: column;
    gap: var(--space-3);
  }
}
</style>
