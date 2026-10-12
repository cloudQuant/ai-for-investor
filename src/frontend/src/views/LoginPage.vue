<template>
  <AuthFrame
    title-id="login-title"
    :eyebrow="t('auth.loginEyebrow')"
    :title="t('auth.loginTitle')"
    :subtitle="t('auth.loginSubtitle')"
  >
    <div
      v-if="hasUnconfirmedToken"
      class="auth-identity-state"
      :data-testid="identityNeedsRetry ? 'identity-retry-panel' : 'identity-checking-panel'"
      :role="identityNeedsRetry ? 'alert' : 'status'"
    >
      <p>{{ identityNeedsRetry ? t('auth.identityUnconfirmed') : t('common.loading') }}</p>
      <p v-if="identityNeedsRetry && authStore.identityError">
        {{ authStore.identityError }}
      </p>
      <el-button
        v-if="identityNeedsRetry"
        data-testid="identity-retry"
        type="primary"
        :loading="retryingIdentity"
        @click="retryIdentity"
      >
        {{ t('auth.retryIdentity') }}
      </el-button>
    </div>

    <el-form
      v-else
      ref="formRef"
      class="auth-form"
      :model="form"
      :rules="rules"
      :aria-label="t('auth.login')"
      @submit.prevent="handleLogin"
    >
      <el-form-item prop="username">
        <el-input
          ref="usernameInputRef"
          v-model="form.username"
          data-testid="login-username"
          :placeholder="t('auth.username')"
          :aria-label="t('auth.username')"
          :prefix-icon="User"
          size="large"
          autocomplete="username"
        />
      </el-form-item>

      <el-form-item prop="password">
        <el-input
          v-model="form.password"
          data-testid="login-password"
          type="password"
          :placeholder="t('auth.password')"
          :aria-label="t('auth.password')"
          :prefix-icon="Lock"
          size="large"
          show-password
          autocomplete="current-password"
        />
      </el-form-item>

      <el-form-item>
        <el-button
          data-testid="login-submit"
          type="primary"
          size="large"
          class="auth-submit"
          :loading="loading"
          native-type="submit"
          :aria-label="t('auth.login')"
        >
          {{ t('auth.login') }}
        </el-button>
      </el-form-item>
    </el-form>

    <template #footer>
      {{ t('auth.noAccount') }}
      <router-link
        to="/register"
        class="auth-link"
        :aria-label="t('auth.registerNow')"
      >
        {{ t('auth.registerNow') }}
      </router-link>
    </template>
  </AuthFrame>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Lock, User } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'
import type { ElInput, FormInstance, FormRules } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '@/stores/auth'
import AuthFrame from '@/components/auth/AuthFrame.vue'

const { t } = useI18n()
const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const retryingIdentity = ref(false)
const usernameInputRef = ref<InstanceType<typeof ElInput> | null>(null)
const hasUnconfirmedToken = computed(() =>
  !!authStore.token && authStore.identityStatus !== 'confirmed',
)
const identityNeedsRetry = computed(() =>
  !!authStore.token && authStore.identityStatus === 'retryable_error',
)

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [
    { required: true, message: t('auth.usernameRequired'), trigger: 'blur' },
  ],
  password: [
    { required: true, message: t('auth.passwordRequired'), trigger: 'blur' },
  ],
}

async function handleLogin() {
  if (loading.value || hasUnconfirmedToken.value) return

  if (!formRef.value) {
    console.warn('[Login] formRef is null, skipping validation')
  } else {
    const valid = await formRef.value.validate().catch(() => false)
    if (!valid) return
  }

  loading.value = true
  try {
    await authStore.login(form)
    ElMessage.success(t('auth.loginSuccess'))
    navigateAfterAuthentication()
  } catch {
    // 错误已在拦截器中处理
  } finally {
    loading.value = false
  }
}

async function retryIdentity() {
  if (retryingIdentity.value || !identityNeedsRetry.value) return

  retryingIdentity.value = true
  try {
    if (await authStore.fetchUser()) {
      ElMessage.success(t('auth.identityConfirmed'))
      navigateAfterAuthentication()
    }
  } catch {
    // Keep the retained token and let the store expose the retryable error.
  } finally {
    retryingIdentity.value = false
  }
}

function navigateAfterAuthentication() {
  // BUG-11: 验证重定向路径安全性，防止 XSS
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : ''
  const safeRedirect = redirect && redirect.startsWith('/') && !redirect.startsWith('//') ? redirect : '/'
  router.push(safeRedirect)
}

onMounted(() => {
  // Auto-focus username input on page load
  usernameInputRef.value?.focus()
})
</script>
