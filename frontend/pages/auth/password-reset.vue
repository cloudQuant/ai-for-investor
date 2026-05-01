<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1 class="auth-title">重置密码</h1>

      <form v-if="!resetToken" @submit.prevent="handleRequest" class="auth-form">
        <div class="form-group">
          <label for="email" class="form-label">邮箱</label>
          <input id="email" v-model="email" type="email" class="form-input" required />
        </div>
        <div v-if="errorMsg" class="error-message">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-message">{{ successMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? '发送中...' : '发送重置链接' }}
        </button>
      </form>

      <form v-else @submit.prevent="handleConfirm" class="auth-form">
        <div class="form-group">
          <label for="password" class="form-label">新密码</label>
          <input id="password" v-model="newPassword" type="password" class="form-input" required />
          <span class="form-hint">至少8位，包含大小写字母和数字</span>
        </div>
        <div v-if="errorMsg" class="error-message">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-message">{{ successMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? '重置中...' : '确认重置' }}
        </button>
      </form>

      <div class="auth-footer">
        <NuxtLink to="/auth/login" class="auth-link">返回登录</NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()
const router = useRouter()

const resetToken = computed(() => (typeof route.query.token === 'string' ? route.query.token : ''))
const email = ref('')
const newPassword = ref('')
const loading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const handleRequest = async () => {
  loading.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const response = await $api.post('/auth/password-reset', { email: email.value })
    successMsg.value = response.data?.message || '如果邮箱存在，重置链接已发送。'
  } catch (error: any) {
    errorMsg.value = error.message || '发送失败，请稍后重试。'
  } finally {
    loading.value = false
  }
}

const handleConfirm = async () => {
  loading.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    const response = await $api.post('/auth/password-reset/confirm', {
      token: resetToken.value,
      new_password: newPassword.value,
    })
    successMsg.value = response.data?.message || '密码已重置，请重新登录。'
    setTimeout(() => router.push('/auth/login'), 1500)
  } catch (error: any) {
    errorMsg.value = error.message || '重置失败，请确认链接是否已过期。'
  } finally {
    loading.value = false
  }
}

useHead({
  title: '重置密码 - AI For Investor',
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
}

.auth-title {
  font-size: var(--font-size-xl);
  font-weight: 700;
  text-align: center;
  margin-bottom: var(--space-6);
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
}

.form-label {
  font-size: var(--font-size-sm);
  font-weight: 500;
  color: var(--color-text);
}

.form-input {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  font-size: var(--font-size-md);
  background-color: var(--color-bg);
  color: var(--color-text);
}

.form-hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-subtle);
}

.btn {
  padding: var(--space-3);
  border-radius: var(--radius-md);
  font-size: var(--font-size-md);
  font-weight: 500;
  cursor: pointer;
  border: none;
}

.btn-primary {
  background-color: var(--color-primary);
  color: white;
}

.btn-primary:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-full {
  width: 100%;
}

.error-message {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  text-align: center;
}

.success-message {
  color: var(--color-success);
  font-size: var(--font-size-sm);
  text-align: center;
}

.auth-footer {
  margin-top: var(--space-6);
  text-align: center;
}

.auth-link {
  color: var(--color-primary);
  text-decoration: none;
  font-size: var(--font-size-sm);
}

@media (max-width: 640px) {
  .auth-page {
    align-items: flex-start;
    min-height: auto;
  }

  .auth-card {
    padding: var(--space-6);
  }
}
</style>
