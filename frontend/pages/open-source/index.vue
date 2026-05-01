<template>
  <div class="project-library-page">
    <header class="library-hero">
      <h1>开源项目库</h1>
      <p>浏览经过人工审核的 AI 投资与量化研究开源项目。内容仅用于教育与研究，不构成投资建议或收益承诺。</p>
    </header>

    <section class="filter-panel">
      <input v-model="search" class="filter-input" placeholder="搜索项目、摘要或关键词" @keyup.enter="applyFilters" />
      <input v-model="language" class="filter-input" placeholder="按语言过滤，例如 Python" @keyup.enter="applyFilters" />
      <button class="btn btn-primary" @click="applyFilters">筛选</button>
    </section>

    <div v-if="pending" class="state-card">加载项目中...</div>
    <div v-else-if="error" class="state-card error">项目加载失败</div>
    <div v-else-if="projects.length" class="project-grid">
      <NuxtLink v-for="project in projects" :key="project.id" :to="`/open-source/${project.id}`" class="project-card">
        <div class="project-card-header">
          <h2>{{ project.repo_full_name }}</h2>
          <span class="score-badge">{{ project.overall_score?.toFixed?.(1) || project.overall_score }}</span>
        </div>
        <p>{{ project.description || '暂无项目摘要' }}</p>
        <div class="project-meta">
          <span>{{ project.language || 'Unknown' }}</span>
          <span>{{ project.license || 'License unknown' }}</span>
          <span>{{ project.stars }} stars</span>
        </div>
      </NuxtLink>
    </div>
    <div v-else class="state-card">暂无已审核精选项目。</div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()
const router = useRouter()

const search = ref((route.query.q as string) || '')
const language = ref((route.query.language as string) || '')

const { data, pending, error, refresh } = await useAsyncData(
  () => `open-source-projects-${route.query.q || ''}-${route.query.language || ''}`,
  () => $api.get('/open-source/projects', {
    ...(search.value ? { q: search.value } : {}),
    ...(language.value ? { language: language.value } : {}),
  }),
  { watch: [() => route.query.q, () => route.query.language] }
)

const projects = computed(() => data.value?.data || [])

const applyFilters = async () => {
  await router.replace({
    query: {
      ...(search.value ? { q: search.value } : {}),
      ...(language.value ? { language: language.value } : {}),
    },
  })
  await refresh()
}

useHead({
  title: '开源项目库 - AI For Investor',
})
</script>

<style scoped>
.project-library-page {
  padding: var(--space-4) 0;
}

.library-hero {
  margin-bottom: var(--space-8);
}

.library-hero h1 {
  font-size: var(--font-size-2xl);
  margin-bottom: var(--space-3);
}

.library-hero p {
  color: var(--color-text-muted);
  max-width: 760px;
}

.filter-panel {
  display: flex;
  gap: var(--space-3);
  margin-bottom: var(--space-6);
}

.filter-input {
  flex: 1;
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
}

.btn {
  padding: var(--space-3) var(--space-5);
  border: 0;
  border-radius: var(--radius-md);
  cursor: pointer;
  font-weight: 600;
}

.btn-primary {
  background-color: var(--color-primary);
  color: white;
}

.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: var(--space-4);
}

.project-card,
.state-card {
  display: block;
  padding: var(--space-5);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface);
  text-decoration: none;
  color: var(--color-text);
}

.project-card:hover {
  border-color: var(--color-primary);
}

.project-card-header {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  margin-bottom: var(--space-3);
}

.project-card h2 {
  font-size: var(--font-size-md);
}

.project-card p {
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
}

.score-badge {
  color: var(--color-primary);
  font-weight: 700;
}

.project-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-3);
  color: var(--color-text-subtle);
  font-size: var(--font-size-xs);
}

.error {
  color: var(--color-danger);
}

@media (max-width: 640px) {
  .filter-panel {
    flex-direction: column;
  }

  .btn {
    width: 100%;
  }

  .project-grid {
    grid-template-columns: 1fr;
  }

  .project-card-header {
    flex-direction: column;
  }
}
</style>
