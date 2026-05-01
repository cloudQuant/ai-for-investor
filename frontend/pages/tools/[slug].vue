<template>
  <div class="tool-detail-page">
    <NuxtLink to="/tools" class="back-link">返回工具列表</NuxtLink>

    <div v-if="pending" class="state-card">加载工具详情中...</div>
    <div v-else-if="error" class="state-card error">工具详情加载失败</div>
    <article v-else-if="tool" class="tool-detail-card">
      <header class="detail-header">
        <div>
          <h1>{{ tool.name }}</h1>
          <p>{{ tool.description }}</p>
        </div>
        <span :class="['access-badge', tool.access_type]">{{ getAccessLabel(tool.access_type) }}</span>
      </header>

      <section class="risk-box">
        <strong>金融风险提示：</strong>{{ tool.financial_risk_reminder || '工具仅供教育与研究，不构成投资建议或收益承诺。' }}
      </section>
      <section class="risk-box execution">
        <strong>执行风险提示：</strong>{{ tool.execution_risk_reminder || '请勿将工具输出直接用于真实账户、实盘交易或自动化下单。' }}
        <NuxtLink to="/legal/risk-disclaimer" class="risk-link">查看完整免责声明</NuxtLink>
      </section>

      <section class="detail-grid">
        <div class="detail-item">
          <span>风险等级</span>
          <strong>{{ getRiskLabel(tool.risk_level) }}</strong>
        </div>
        <div class="detail-item">
          <span>支持模式</span>
          <strong>{{ getModeLabel(tool.run_mode) }}</strong>
        </div>
        <div class="detail-item">
          <span>许可证</span>
          <strong>{{ tool.license || 'Unknown' }}</strong>
        </div>
        <div class="detail-item">
          <span>资源成本</span>
          <strong>{{ tool.resource_cost || '未标注' }}</strong>
        </div>
      </section>

      <section class="content-section">
        <h2>源项目</h2>
        <a v-if="tool.source_url" :href="tool.source_url" target="_blank" rel="noopener noreferrer">{{ tool.source_url }}</a>
        <p v-else>暂无源项目链接。</p>
      </section>

      <section class="content-section">
        <h2>使用限制</h2>
        <p>{{ tool.usage_limitations || '仅限教育和研究场景使用。' }}</p>
      </section>
    </article>
    <div v-else class="state-card">工具不存在或尚未公开。</div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()

const { data, pending, error } = await useAsyncData(
  () => `tool-${route.params.slug}`,
  () => $api.get(`/tools/tools/${route.params.slug}`)
)

const tool = computed(() => data.value?.data)

const getRiskLabel = (level: string) => {
  const labels: Record<string, string> = {
    low: '低风险',
    medium: '中风险',
    high: '高风险',
    extreme: '极高风险',
  }
  return labels[level] || level
}

const getModeLabel = (mode: string) => {
  const labels: Record<string, string> = {
    internal: '在线运行',
    external: '外部 Demo',
    document: '仅文档',
  }
  return labels[mode] || mode
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
  title: computed(() => tool.value ? `${tool.value.name} - 工具详情` : '工具详情 - AI For Investor'),
})
</script>

<style scoped>
.tool-detail-page {
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

.tool-detail-card,
.state-card {
  padding: var(--space-6);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface);
}

.detail-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-6);
  margin-bottom: var(--space-6);
}

.detail-header h1 {
  font-size: var(--font-size-2xl);
  margin-bottom: var(--space-2);
}

.detail-header p,
.content-section p {
  color: var(--color-text-muted);
}

.access-badge {
  align-self: flex-start;
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-full);
  background-color: var(--color-primary);
  color: white;
  white-space: nowrap;
}

.access-badge.documentation_only {
  background-color: var(--color-text-muted);
}

.access-badge.external_demo {
  background-color: var(--color-warning);
}

.risk-box {
  margin-bottom: var(--space-4);
  padding: var(--space-4);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-md);
  color: var(--color-warning);
}

.risk-box.execution {
  margin-bottom: var(--space-6);
}

.risk-link {
  display: inline-block;
  margin-left: var(--space-2);
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--space-4);
  margin-bottom: var(--space-6);
}

.detail-item {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
}

.detail-item span {
  display: block;
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
  margin-bottom: var(--space-1);
}

.content-section {
  margin-top: var(--space-6);
}

.content-section h2 {
  margin-bottom: var(--space-3);
}

.content-section a {
  color: var(--color-primary);
  word-break: break-all;
}

.error {
  color: var(--color-danger);
}
</style>
