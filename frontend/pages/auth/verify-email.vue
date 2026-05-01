<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1 class="auth-title">邮箱验证</h1>
      <p v-if="loading" class="status-message">正在验证邮箱...</p>
      <p v-else-if="successMsg" class="success-message">{{ successMsg }}</p>
      <p v-else class="error-message">{{ errorMsg }}</p>
      <div class="auth-footer">
        <NuxtLink to="/auth/login" class="auth-link">返回登录</NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()

const loading = ref(true)
const successMsg = ref('')
const errorMsg = ref('')

onMounted(async () => {
  const token = route.query.token
  if (typeof token !== 'string' || !token) {
    errorMsg.value = '验证链接无效或已过期。'
    loading.value = false
    return
  }

  try {
    const response = await $api.post('/auth/verify-email', { token })
    successMsg.value = response.data?.message || '邮箱验证成功，请登录。'
  } catch (error: any) {
    errorMsg.value = error.message || '验证失败，请确认链接是否已过期。'
  } finally {
    loading.value = false
  }
})

useHead({
  title: '邮箱验证 - AI For Investor',
})
</script>

<style scoped>
.auth-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 60vh;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  padding: var(--space-8);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
  text-align: center;
}

.auth-title {
  font-size: var(--font-size-xl);
  font-weight: 700;
  margin-bottom: var(--space-6);
}

.status-message {
  color: var(--color-text-muted);
}

.success-message {
  color: var(--color-success);
}

.error-message {
  color: var(--color-danger);
}

.auth-footer {
  margin-top: var(--space-6);
}

.auth-link {
  color: var(--color-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
}
</style>
