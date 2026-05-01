<template>
  <section class="new-thread-page">
    <NuxtLink to="/forum" class="back-link">返回论坛</NuxtLink>
    <div class="form-card">
      <h1>发布主题</h1>
      <p class="form-intro">分享 AI 投资研究、工具体验、风险方法或开源项目问题。请避免投资建议、收益承诺或买卖指令。</p>

      <div v-if="!authStore.isLoggedIn" class="auth-notice">
        <h2>登录后发布主题</h2>
        <p>你需要登录或注册账号，并完成邮箱验证后才能参与讨论。</p>
        <div class="notice-actions">
          <NuxtLink class="btn btn-primary" :to="`/auth/login?redirect=${route.fullPath}`">登录</NuxtLink>
          <NuxtLink class="btn btn-secondary" to="/auth/register">注册</NuxtLink>
        </div>
      </div>

      <div v-else-if="!isVerified" class="auth-notice">
        <h2>请先验证邮箱</h2>
        <p>为了减少垃圾内容和保护社区质量，发布主题前需要完成邮箱验证。</p>
        <NuxtLink class="btn btn-primary" to="/user">前往用户中心</NuxtLink>
      </div>

      <form v-else class="thread-form" @submit.prevent="submitThread">
        <label>
          分类
          <select v-model="form.category_id" required>
            <option value="" disabled>选择分类</option>
            <option v-for="cat in categories" :key="cat.id" :value="cat.id">{{ cat.name }}</option>
          </select>
        </label>
        <label>
          标题
          <input v-model="form.title" type="text" maxlength="255" required placeholder="例如：如何评估一个 AI 投研 Demo 的可信度？" />
        </label>
        <label>
          内容
          <textarea v-model="form.content" rows="10" required placeholder="描述背景、已尝试的方法、风险边界和希望讨论的问题。" />
        </label>
        <p v-if="errorMessage" class="form-error">{{ errorMessage }}</p>
        <button class="btn btn-primary" type="submit" :disabled="submitting">{{ submitting ? '发布中...' : '发布主题' }}</button>
      </form>
    </div>
  </section>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

if (!authStore.isLoggedIn) {
  authStore.restoreSession()
}
if (authStore.isLoggedIn && !authStore.user) {
  await authStore.fetchUser()
}

const { data: categoriesData } = await useAsyncData('forum-categories-for-new-thread', () => $api.get('/forum/categories'))
const categories = computed(() => categoriesData.value?.data || [])
const isVerified = computed(() => Boolean(authStore.user?.email_verified_at || authStore.user?.email_verified))
const submitting = ref(false)
const errorMessage = ref('')
const form = reactive({
  category_id: '',
  title: '',
  content: '',
})

const submitThread = async () => {
  errorMessage.value = ''
  submitting.value = true
  try {
    const response = await $api.post('/forum/threads', {
      category_id: Number(form.category_id),
      title: form.title,
      content: form.content,
    })
    await router.push(`/forum/${response.data.id}`)
  } catch (error: any) {
    errorMessage.value = error.message || '发布失败，请稍后重试。'
  } finally {
    submitting.value = false
  }
}

useHead({
  title: '发布主题 - 论坛 - AI For Investor',
})
</script>

<style scoped>
.new-thread-page {
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

.form-card,
.auth-notice {
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
}

.form-card h1 {
  margin-bottom: var(--space-3);
}

.form-intro,
.auth-notice p {
  color: var(--color-text-muted);
  line-height: 1.7;
  margin-bottom: var(--space-5);
}

.thread-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.thread-form label {
  display: flex;
  flex-direction: column;
  gap: var(--space-2);
  color: var(--color-text);
  font-weight: 600;
}

.thread-form input,
.thread-form select,
.thread-form textarea {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

.notice-actions {
  display: flex;
  gap: var(--space-3);
}

.btn {
  display: inline-flex;
  justify-content: center;
  padding: var(--space-2) var(--space-4);
  border: 0;
  border-radius: var(--radius-md);
  text-decoration: none;
  font-size: var(--font-size-sm);
  font-weight: 600;
  cursor: pointer;
}

.btn-primary {
  background-color: var(--color-primary);
  color: white;
}

.btn-secondary {
  background-color: var(--color-surface-muted);
  color: var(--color-text);
}

.form-error {
  color: var(--color-danger);
}
</style>
