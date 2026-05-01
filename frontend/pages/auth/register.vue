<template>
  <div class="auth-page">
    <div class="auth-card">
      <h1 class="auth-title">注册</h1>
      <form @submit.prevent="handleRegister" class="auth-form">
        <div class="form-group">
          <label for="email" class="form-label">邮箱</label>
          <input
            id="email"
            v-model="email"
            type="email"
            class="form-input"
            required
          />
        </div>
        <div class="form-group">
          <label for="username" class="form-label">用户名（可选）</label>
          <input
            id="username"
            v-model="username"
            type="text"
            class="form-input"
          />
        </div>
        <div class="form-group">
          <label for="password" class="form-label">密码</label>
          <input
            id="password"
            v-model="password"
            type="password"
            class="form-input"
            required
          />
          <span class="form-hint">至少8位，包含大小写字母和数字</span>
        </div>
        <div v-if="errorMsg" class="error-message">{{ errorMsg }}</div>
        <div v-if="successMsg" class="success-message">{{ successMsg }}</div>
        <button type="submit" class="btn btn-primary btn-full" :disabled="loading">
          {{ loading ? '注册中...' : '注册' }}
        </button>
      </form>
      <div class="auth-footer">
        <NuxtLink to="/auth/login" class="auth-link">已有账号？立即登录</NuxtLink>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
const authStore = useAuthStore()
const router = useRouter()

const email = ref('')
const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMsg = ref('')
const successMsg = ref('')

const handleRegister = async () => {
  loading.value = true
  errorMsg.value = ''
  successMsg.value = ''
  try {
    await authStore.register(email.value, username.value, password.value)
    successMsg.value = '注册成功！请前往邮箱验证账号。'
    setTimeout(() => router.push('/auth/login'), 2000)
  } catch (error: any) {
    errorMsg.value = error.message || '注册失败'
  } finally {
    loading.value = false
  }
}

useHead({
  title: '注册 - AI For Investor',
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
  max-width: 400px;
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

.form-input:focus {
  outline: none;
  border-color: var(--color-primary);
  box-shadow: 0 0 0 2px var(--color-focus-ring);
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

.btn-primary:hover {
  background-color: var(--color-primary-hover);
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

.auth-link:hover {
  text-decoration: underline;
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
