<template>
  <article class="blog-detail-page">
    <div v-if="pending" class="loading">加载中...</div>
    <div v-else-if="error" class="error">文章不存在或尚未发布。</div>
    <template v-else-if="post">
      <NuxtLink to="/blog" class="back-link">返回博客列表</NuxtLink>
      <img v-if="post.cover_image_url" :src="post.cover_image_url" :alt="post.title" class="cover-image" />
      <h1 class="post-title">{{ post.title }}</h1>
      <div class="post-meta">
        <span>{{ post.author_username }}</span>
        <span>{{ formatDate(post.published_at) }}</span>
        <span v-if="post.category_name">{{ post.category_name }}</span>
      </div>
      <p v-if="post.summary" class="post-summary">{{ post.summary }}</p>
      <div v-if="post.tags?.length" class="tag-list">
        <span v-for="tag in post.tags" :key="tag.slug" class="tag-item">{{ tag.name }}</span>
      </div>
      <section class="post-content markdown-content" v-html="post.rendered_content || post.content" />
      <section class="disclaimer-note">
        <strong>内容边界：</strong>本文仅供教育和研究参考，不构成投资建议。
        <NuxtLink to="/legal/risk-disclaimer">查看金融风险免责声明</NuxtLink>
      </section>
    </template>
  </article>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const config = useRuntimeConfig()
const route = useRoute()

const slug = computed(() => route.params.slug as string)
const { data, pending, error } = await useAsyncData(
  () => `blog-post-${slug.value}`,
  () => $api.get(`/blog/posts/${slug.value}`),
  { watch: [slug] }
)

const post = computed(() => data.value?.data)
const canonicalUrl = computed(() => post.value?.canonical_url || `${config.public.siteUrl}/blog/${slug.value}`)
const structuredData = computed(() => post.value?.structured_data ? JSON.stringify(post.value.structured_data) : '')

const formatDate = (dateStr: string) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

useHead(() => ({
  title: post.value ? `${post.value.title} - AI For Investor` : '博客详情 - AI For Investor',
  meta: [
    { name: 'description', content: post.value?.summary || 'AI交易与投资内容文章' },
    { property: 'og:type', content: post.value?.open_graph?.type || 'article' },
    { property: 'og:title', content: post.value?.open_graph?.title || post.value?.title || '博客详情 - AI For Investor' },
    { property: 'og:description', content: post.value?.open_graph?.description || post.value?.summary || 'AI交易与投资内容文章' },
    { property: 'og:url', content: post.value?.open_graph?.url || canonicalUrl.value },
    { property: 'og:image', content: post.value?.open_graph?.image || '' },
    { name: 'twitter:card', content: post.value?.cover_image_url ? 'summary_large_image' : 'summary' },
    { name: 'twitter:title', content: post.value?.title || '博客详情 - AI For Investor' },
    { name: 'twitter:description', content: post.value?.summary || 'AI交易与投资内容文章' },
  ],
  link: [
    { rel: 'canonical', href: canonicalUrl.value },
  ],
  script: [
    {
      type: 'application/ld+json',
      children: structuredData.value,
    },
  ],
}))
</script>

<style scoped>
.blog-detail-page {
  max-width: 820px;
  margin: 0 auto;
  padding: var(--space-4) 0 var(--space-12);
}

.back-link {
  display: inline-block;
  margin-bottom: var(--space-6);
  color: var(--color-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
}

.cover-image {
  width: 100%;
  max-height: 360px;
  object-fit: cover;
  border-radius: var(--radius-xl);
  margin-bottom: var(--space-8);
}

.post-title {
  font-size: var(--font-size-3xl);
  font-weight: 700;
  color: var(--color-text);
  margin-bottom: var(--space-4);
}

.post-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  color: var(--color-text-subtle);
  font-size: var(--font-size-sm);
  margin-bottom: var(--space-6);
}

.post-summary {
  padding: var(--space-4);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  color: var(--color-text-muted);
  margin-bottom: var(--space-6);
}

.tag-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-bottom: var(--space-8);
}

.tag-item {
  padding: var(--space-1) var(--space-3);
  background-color: var(--color-surface-muted);
  border-radius: var(--radius-full);
  color: var(--color-text-muted);
  font-size: var(--font-size-xs);
}

.markdown-content {
  line-height: 1.8;
  color: var(--color-text);
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin: var(--space-8) 0 var(--space-4);
  color: var(--color-text);
}

.markdown-content :deep(p),
.markdown-content :deep(ul),
.markdown-content :deep(ol),
.markdown-content :deep(table),
.markdown-content :deep(pre) {
  margin-bottom: var(--space-5);
}

.markdown-content :deep(a) {
  color: var(--color-primary);
}

.markdown-content :deep(pre) {
  overflow-x: auto;
  padding: var(--space-4);
  background-color: var(--color-surface-muted);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
}

.markdown-content :deep(code) {
  font-family: monospace;
  background-color: var(--color-surface-muted);
  padding: 0.1rem 0.3rem;
  border-radius: var(--radius-sm);
}

.markdown-content :deep(pre code) {
  padding: 0;
  background: transparent;
}

.markdown-content :deep(table) {
  width: 100%;
  border-collapse: collapse;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: var(--space-2);
  border: 1px solid var(--color-border);
  text-align: left;
}

.disclaimer-note {
  margin-top: var(--space-8);
  padding: var(--space-4);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-lg);
  color: var(--color-text-muted);
}

.disclaimer-note a {
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}

.loading,
.error {
  padding: var(--space-8);
  text-align: center;
  color: var(--color-text-muted);
}
</style>
