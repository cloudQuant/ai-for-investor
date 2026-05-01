<template>
  <div class="blog-list-page">
    <h1 class="page-title">博客</h1>
    <div class="filter-panel">
      <input
        v-model="searchInput"
        type="search"
        class="search-input"
        placeholder="搜索教程、项目评测或风险方法论"
        @keyup.enter="applyFilters"
      />
      <select v-model="selectedCategory" class="filter-select" @change="applyFilters">
        <option value="">全部分类</option>
        <option v-for="category in categories" :key="category.slug" :value="category.slug">
          {{ category.name }}
        </option>
      </select>
      <select v-model="selectedTag" class="filter-select" @change="applyFilters">
        <option value="">全部标签</option>
        <option v-for="tag in tags" :key="tag.slug" :value="tag.slug">
          {{ tag.name }}
        </option>
      </select>
      <button class="filter-btn" @click="applyFilters">筛选</button>
      <button class="filter-btn secondary" @click="resetFilters">重置</button>
    </div>
    <div class="blog-list">
      <div v-if="pending" class="loading">加载中...</div>
      <div v-else-if="error" class="error">加载失败</div>
      <div v-else-if="posts.length === 0" class="empty-state">
        <h3>没有找到匹配内容</h3>
        <p>尝试更换关键词、分类或标签，查看所有已发布文章。</p>
        <button class="filter-btn" @click="resetFilters">查看全部文章</button>
      </div>
      <template v-else>
        <NuxtLink
          v-for="post in posts"
          :key="post.id"
          :to="`/blog/${post.slug}`"
          class="blog-card"
        >
          <h3 class="blog-title">{{ post.title }}</h3>
          <p class="blog-summary">{{ post.summary }}</p>
          <div class="blog-meta">
            <span class="blog-author">{{ post.author_username }}</span>
            <span v-if="post.category_name">{{ post.category_name }}</span>
            <span class="blog-date">{{ formatDate(post.published_at) }}</span>
          </div>
          <div v-if="post.tags?.length" class="tag-list">
            <span v-for="tag in post.tags" :key="tag.slug" class="tag-item">{{ tag.name }}</span>
          </div>
        </NuxtLink>
      </template>
    </div>
    <div class="pagination">
      <button
        :disabled="page <= 1"
        @click="page--"
        class="page-btn"
      >
        上一页
      </button>
      <span class="page-info">{{ page }} / {{ totalPages }}</span>
      <button
        :disabled="page >= totalPages"
        @click="page++"
        class="page-btn"
      >
        下一页
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()
const router = useRouter()

const page = ref(Number(route.query.page) || 1)
const pageSize = 20
const searchInput = ref(typeof route.query.q === 'string' ? route.query.q : '')
const selectedCategory = ref(typeof route.query.category === 'string' ? route.query.category : '')
const selectedTag = ref(typeof route.query.tag === 'string' ? route.query.tag : '')

const apiParams = computed(() => ({
  page: page.value,
  page_size: pageSize,
  ...(searchInput.value ? { q: searchInput.value } : {}),
  ...(selectedCategory.value ? { category: selectedCategory.value } : {}),
  ...(selectedTag.value ? { tag: selectedTag.value } : {}),
}))

const { data, pending, error } = await useAsyncData(
  () => `blog-posts-${page.value}-${searchInput.value}-${selectedCategory.value}-${selectedTag.value}`,
  () => $api.get('/blog/posts', apiParams.value),
  { watch: [page, searchInput, selectedCategory, selectedTag] }
)

const { data: categoryData } = await useAsyncData('blog-categories', () => $api.get('/blog/categories'))
const { data: tagData } = await useAsyncData('blog-tags', () => $api.get('/blog/tags'))

const posts = computed(() => data.value?.data || [])
const categories = computed(() => categoryData.value?.data || [])
const tags = computed(() => tagData.value?.data || [])
const total = computed(() => data.value?.pagination?.total || 0)
const totalPages = computed(() => Math.max(1, Math.ceil(total.value / pageSize)))

const syncQuery = () => {
  router.replace({
    query: {
      ...(page.value > 1 ? { page: String(page.value) } : {}),
      ...(searchInput.value ? { q: searchInput.value } : {}),
      ...(selectedCategory.value ? { category: selectedCategory.value } : {}),
      ...(selectedTag.value ? { tag: selectedTag.value } : {}),
    },
  })
}

const applyFilters = () => {
  page.value = 1
  syncQuery()
}

const resetFilters = () => {
  page.value = 1
  searchInput.value = ''
  selectedCategory.value = ''
  selectedTag.value = ''
  syncQuery()
}

watch(page, syncQuery)

const formatDate = (dateStr: string) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

useHead({
  title: '博客 - AI For Investor',
})
</script>

<style scoped>
.blog-list-page {
  padding: var(--space-4) 0;
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: 700;
  margin-bottom: var(--space-8);
}

.filter-panel {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) repeat(2, minmax(140px, 180px)) auto auto;
  gap: var(--space-3);
  align-items: center;
  margin-bottom: var(--space-6);
}

.search-input,
.filter-select {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-bg);
  color: var(--color-text);
  font-size: var(--font-size-sm);
}

.filter-btn {
  padding: var(--space-3) var(--space-4);
  border: 1px solid var(--color-primary);
  border-radius: var(--radius-md);
  background-color: var(--color-primary);
  color: white;
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.filter-btn.secondary {
  border-color: var(--color-border);
  background-color: var(--color-surface);
  color: var(--color-text);
}

.blog-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.blog-card {
  display: block;
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  transition: all 0.2s;
}

.blog-card:hover {
  border-color: var(--color-primary);
  box-shadow: var(--shadow-card);
}

.blog-title {
  font-size: var(--font-size-lg);
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.blog-summary {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
}

.blog-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  font-size: var(--font-size-xs);
  color: var(--color-text-subtle);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}

.tag-item {
  padding: var(--space-1) var(--space-3);
  background-color: var(--color-surface-muted);
  border-radius: var(--radius-full);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.loading,
.error,
.empty-state {
  padding: var(--space-8);
  text-align: center;
  color: var(--color-text-muted);
}

.empty-state h3 {
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.empty-state p {
  margin-bottom: var(--space-4);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  margin-top: var(--space-8);
}

.page-btn {
  padding: var(--space-2) var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
  font-size: var(--font-size-sm);
  cursor: pointer;
}

.page-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.page-info {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
}

@media (max-width: 768px) {
  .filter-panel {
    grid-template-columns: 1fr;
  }
}
</style>
