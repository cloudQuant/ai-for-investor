<template>
  <div class="forum-page">
    <div class="forum-header">
      <h1 class="page-title">论坛</h1>
      <div class="forum-actions">
        <NuxtLink to="/forum/rules" class="btn btn-secondary">社区规则</NuxtLink>
        <NuxtLink to="/forum/new" class="btn btn-primary">发布主题</NuxtLink>
      </div>
    </div>

    <div class="forum-layout">
      <aside class="forum-sidebar">
        <h3 class="sidebar-title">分类</h3>
        <ul class="category-list">
          <li
            :class="['category-item', { active: !selectedCategory }]"
            @click="selectCategory(null)"
          >
            全部讨论
          </li>
          <li
            v-for="cat in categories"
            :key="cat.id"
            :class="['category-item', { active: selectedCategory === cat.slug }]"
            @click="selectCategory(cat.slug)"
          >
            <span>{{ cat.name }}</span>
            <small>{{ cat.thread_count }} 主题</small>
          </li>
        </ul>
      </aside>

      <main class="forum-main">
        <div class="forum-toolbar">
          <select v-model="sort" class="sort-select" @change="syncQuery">
            <option value="latest">最新回复</option>
            <option value="newest">最新发布</option>
            <option value="popular">热门讨论</option>
          </select>
        </div>
        <div v-if="pending" class="loading">加载中...</div>
        <div v-else-if="error" class="error">加载失败</div>
        <div v-else-if="threads.length" class="thread-list">
          <NuxtLink
            v-for="thread in threads"
            :key="thread.id"
            :to="`/forum/${thread.id}`"
            class="thread-item"
          >
            <div class="thread-status" v-if="thread.is_pinned">
              <span class="status-badge pin">置顶</span>
            </div>
            <div class="thread-status" v-if="thread.is_locked">
              <span class="status-badge lock">锁定</span>
            </div>
            <h3 class="thread-title">{{ thread.title }}</h3>
            <div class="thread-meta">
              <span>{{ thread.author_username }}</span>
              <span>{{ formatDate(thread.created_at) }}</span>
              <span>{{ thread.reply_count }} 回复</span>
              <span>{{ thread.view_count }} 阅读</span>
            </div>
          </NuxtLink>
        </div>
        <div v-else class="empty-state">
          <h3>这个分类还没有公开讨论</h3>
          <p>欢迎浏览其他分类，或注册后发起与 AI 投资研究、工具体验、风险方法相关的高质量讨论。</p>
        </div>
        <div v-if="pagination.total > pagination.page_size" class="pagination">
          <button class="page-button" :disabled="page <= 1" @click="changePage(page - 1)">上一页</button>
          <span>第 {{ page }} 页 / 共 {{ totalPages }} 页</span>
          <button class="page-button" :disabled="page >= totalPages" @click="changePage(page + 1)">下一页</button>
        </div>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()
const router = useRouter()

const page = ref(Number(route.query.page || 1))
const sort = ref((route.query.sort as string) || 'latest')
const selectedCategory = ref<string | null>((route.query.category as string) || null)

const { data: categoriesData } = await useAsyncData('forum-categories', () =>
  $api.get('/forum/categories')
)
const categories = computed(() => categoriesData.value?.data || [])

const { data: threadsData, pending, error } = await useAsyncData(
  () => `forum-threads-${page.value}-${sort.value}-${selectedCategory.value || 'all'}`,
  () => $api.get('/forum/threads', {
    page: page.value,
    page_size: 20,
    sort: sort.value,
    ...(selectedCategory.value ? { category: selectedCategory.value } : {}),
  }),
  { watch: [page, sort, selectedCategory] }
)
const threads = computed(() => threadsData.value?.data || [])
const pagination = computed(() => threadsData.value?.pagination || { page: 1, page_size: 20, total: 0 })
const totalPages = computed(() => Math.max(1, Math.ceil(pagination.value.total / pagination.value.page_size)))

const syncQuery = () => {
  router.replace({
    query: {
      ...(selectedCategory.value ? { category: selectedCategory.value } : {}),
      ...(sort.value !== 'latest' ? { sort: sort.value } : {}),
      ...(page.value > 1 ? { page: String(page.value) } : {}),
    },
  })
}

const selectCategory = (category: string | null) => {
  selectedCategory.value = category
  page.value = 1
  syncQuery()
}

const changePage = (nextPage: number) => {
  page.value = nextPage
  syncQuery()
}

const formatDate = (dateStr: string) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

useHead({
  title: '论坛 - AI For Investor',
})
</script>

<style scoped>
.forum-page {
  padding: var(--space-4) 0;
}

.forum-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-6);
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: 700;
}

.btn {
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
  text-decoration: none;
  font-size: var(--font-size-sm);
  font-weight: 500;
}

.btn-primary {
  background-color: var(--color-primary);
  color: white;
}

.btn-secondary {
  border: 1px solid var(--color-border);
  color: var(--color-text);
}

.forum-actions {
  display: flex;
  gap: var(--space-3);
}

.forum-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--space-6);
}

.forum-sidebar {
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: var(--space-4);
}

.sidebar-title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
  text-transform: uppercase;
}

.category-list {
  list-style: none;
}

.category-item {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  padding: var(--space-2) var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  cursor: pointer;
  color: var(--color-text-muted);
}

.category-item:hover,
.category-item.active {
  background-color: var(--color-primary);
  color: white;
}

.category-item small {
  color: inherit;
  opacity: 0.75;
}

.forum-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: var(--space-4);
}

.sort-select {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
}

.thread-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.thread-item {
  display: block;
  padding: var(--space-4);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  transition: all 0.2s;
}

.thread-item:hover {
  border-color: var(--color-primary);
}

.thread-title {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.thread-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--font-size-xs);
  color: var(--color-text-subtle);
}

.empty-state {
  padding: var(--space-8);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-align: center;
  color: var(--color-text-muted);
}

.empty-state h3 {
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-4);
  margin-top: var(--space-6);
  color: var(--color-text-muted);
}

.page-button {
  padding: var(--space-2) var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
  cursor: pointer;
}

.page-button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.status-badge {
  display: inline-block;
  padding: var(--space-1) var(--space-2);
  border-radius: var(--radius-sm);
  font-size: var(--font-size-xs);
  margin-right: var(--space-2);
}

.status-badge.pin {
  background-color: var(--color-primary);
  color: white;
}

.status-badge.lock {
  background-color: var(--color-warning);
  color: white;
}

.loading,
.error {
  padding: var(--space-8);
  text-align: center;
  color: var(--color-text-muted);
}

@media (max-width: 768px) {
  .forum-header {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-3);
  }

  .forum-actions,
  .forum-toolbar {
    width: 100%;
  }

  .forum-actions {
    flex-wrap: wrap;
  }

  .forum-layout {
    grid-template-columns: 1fr;
  }

  .category-list {
    display: flex;
    overflow-x: auto;
    gap: var(--space-2);
    padding-bottom: var(--space-2);
  }

  .category-item {
    min-width: max-content;
  }

  .sort-select {
    width: 100%;
  }

  .thread-meta,
  .pagination {
    flex-wrap: wrap;
    gap: var(--space-2);
  }
}
</style>
