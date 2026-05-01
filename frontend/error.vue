<template>
  <div class="error-page">
    <main class="error-card">
      <p class="error-kicker">{{ statusLabel }}</p>
      <h1>{{ title }}</h1>
      <p class="error-message">{{ message }}</p>
      <div class="error-actions">
        <NuxtLink to="/" class="btn btn-primary" @click="clearError({ redirect: '/' })">返回首页</NuxtLink>
        <NuxtLink to="/blog" class="btn btn-secondary" @click="clearError({ redirect: '/blog' })">浏览博客</NuxtLink>
        <NuxtLink to="/auth/login" class="btn btn-secondary" @click="clearError({ redirect: '/auth/login' })">登录账号</NuxtLink>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
import type { NuxtError } from '#app'

const props = defineProps<{
  error: NuxtError
}>()

const statusCode = computed(() => props.error.statusCode || 500)
const statusLabel = computed(() => `${statusCode.value}`)
const title = computed(() => {
  if (statusCode.value === 404) return '页面不存在'
  if (statusCode.value === 401) return '需要登录'
  if (statusCode.value === 403) return '没有访问权限'
  return '页面暂时不可用'
})
const message = computed(() => {
  if (statusCode.value === 404) return '你访问的页面可能已移动、删除，或链接输入有误。'
  if (statusCode.value === 401) return '请登录后继续访问该页面。'
  if (statusCode.value === 403) return '当前账号没有访问该页面的权限，你可以返回首页或切换账号。'
  return '服务遇到临时问题，请稍后重试，或返回首页继续浏览。'
})

useHead({
  title: computed(() => `${title.value} - AI For Investor`),
})
</script>

<style scoped>
.error-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--space-6);
  background-color: var(--color-bg);
  color: var(--color-text);
}

.error-card {
  width: min(100%, 640px);
  padding: var(--space-8);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  background-color: var(--color-surface);
  box-shadow: var(--shadow-card);
  text-align: center;
}

.error-kicker {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  font-weight: 700;
  letter-spacing: 0.12em;
  margin-bottom: var(--space-3);
}

.error-card h1 {
  font-size: var(--font-size-3xl);
  margin-bottom: var(--space-4);
}

.error-message {
  color: var(--color-text-muted);
  margin-bottom: var(--space-8);
}

.error-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: var(--space-3);
}

.btn {
  padding: var(--space-3) var(--space-5);
  border-radius: var(--radius-md);
  text-decoration: none;
  font-weight: 600;
}

.btn-primary {
  background-color: var(--color-primary);
  color: white;
}

.btn-secondary {
  border: 1px solid var(--color-border);
  color: var(--color-text);
}

@media (max-width: 640px) {
  .error-card {
    padding: var(--space-6);
  }

  .error-card h1 {
    font-size: var(--font-size-2xl);
  }

  .error-actions {
    flex-direction: column;
  }
}
</style>
