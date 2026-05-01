<template>
  <div class="project-detail-page">
    <NuxtLink to="/open-source" class="back-link">返回项目库</NuxtLink>

    <div v-if="pending" class="state-card">加载项目详情中...</div>
    <div v-else-if="error" class="state-card error">项目详情加载失败</div>
    <article v-else-if="project" class="project-detail-card">
      <header class="detail-header">
        <div>
          <h1>{{ project.repo_full_name }}</h1>
          <p>{{ project.description || '暂无项目摘要' }}</p>
        </div>
        <a :href="project.repo_url" target="_blank" rel="noopener noreferrer" class="repo-link">查看仓库</a>
      </header>

      <section class="risk-box">
        <strong>风险提示：</strong>{{ project.risk_note || '本项目仅供教育与研究参考，不构成投资建议、交易建议或收益承诺。' }}
        <NuxtLink to="/legal/risk-disclaimer" class="risk-link">查看金融风险免责声明</NuxtLink>
      </section>

      <section class="detail-grid">
        <div class="detail-item">
          <span>许可证</span>
          <strong>{{ project.license || 'Unknown' }}</strong>
        </div>
        <div class="detail-item">
          <span>语言</span>
          <strong>{{ project.language || 'Unknown' }}</strong>
        </div>
        <div class="detail-item">
          <span>Stars</span>
          <strong>{{ project.stars }}</strong>
        </div>
        <div class="detail-item">
          <span>综合分</span>
          <strong>{{ project.overall_score }}</strong>
        </div>
      </section>

      <section class="content-section">
        <h2>README 摘要</h2>
        <p>{{ project.readme_summary || '暂无 README 摘要。' }}</p>
      </section>

      <section class="content-section">
        <h2>标签</h2>
        <div class="tag-list">
          <span v-for="topic in project.topics" :key="topic" class="tag">{{ topic }}</span>
          <span v-if="!project.topics?.length" class="tag">暂无标签</span>
        </div>
      </section>

      <section class="content-section">
        <h2>评分说明</h2>
        <p>{{ project.score_note || '评分仅作为编辑筛选辅助，不代表推荐或收益判断。' }}</p>
      </section>

      <section class="content-section">
        <h2>更新时间</h2>
        <p>最近提交：{{ formatDate(project.latest_commit_at) || '未知' }}</p>
      </section>
    </article>
    <div v-else class="state-card">项目不存在或尚未通过人工审核。</div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()

const { data, pending, error } = await useAsyncData(
  () => `open-source-project-${route.params.id}`,
  () => $api.get(`/open-source/projects/id/${route.params.id}`)
)

const project = computed(() => data.value?.data)

const formatDate = (dateStr?: string) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

useHead({
  title: computed(() => project.value ? `${project.value.repo_full_name} - 开源项目库` : '开源项目详情 - AI For Investor'),
})
</script>

<style scoped>
.project-detail-page {
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

.project-detail-card,
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

.repo-link {
  align-self: flex-start;
  padding: var(--space-3) var(--space-4);
  border-radius: var(--radius-md);
  background-color: var(--color-primary);
  color: white;
  text-decoration: none;
  white-space: nowrap;
}

.risk-box {
  margin-bottom: var(--space-6);
  padding: var(--space-4);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-md);
  color: var(--color-warning);
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

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
}

.tag {
  padding: var(--space-1) var(--space-3);
  border-radius: var(--radius-full);
  background-color: var(--color-bg);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.error {
  color: var(--color-danger);
}
</style>
