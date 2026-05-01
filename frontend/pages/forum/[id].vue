<template>
  <article class="thread-detail-page">
    <div v-if="pending" class="loading">加载中...</div>
    <div v-else-if="error" class="error">主题不存在或已被隐藏。</div>
    <template v-else-if="thread">
      <NuxtLink to="/forum" class="back-link">返回论坛</NuxtLink>
      <div class="thread-card">
        <div class="thread-category" v-if="thread.category_name">{{ thread.category_name }}</div>
        <h1 class="thread-title">{{ thread.title }}</h1>
        <div class="thread-meta">
          <span>{{ thread.author_username }}</span>
          <span>{{ formatDate(thread.created_at) }}</span>
          <span>{{ thread.view_count }} 阅读</span>
          <span>{{ thread.reply_count }} 回复</span>
        </div>
        <section class="thread-content">{{ thread.content }}</section>
        <div v-if="canEditThread" class="author-actions">
          <button class="btn btn-secondary" @click="startThreadEdit">编辑主题</button>
          <button class="btn btn-danger" @click="deleteThread">删除主题</button>
        </div>
        <form v-if="editingThread" class="edit-form" @submit.prevent="submitThreadEdit">
          <input v-model="threadEdit.title" required maxlength="255" />
          <textarea v-model="threadEdit.content" rows="6" required />
          <p v-if="threadEditError" class="form-error">{{ threadEditError }}</p>
          <div class="notice-actions">
            <button class="btn btn-primary" type="submit">保存修改</button>
            <button class="btn btn-secondary" type="button" @click="editingThread = false">取消</button>
          </div>
        </form>
      </div>

      <section class="reply-section">
        <h2 class="reply-title">公开回复</h2>
        <div v-if="replies.length" class="reply-list">
          <div v-for="reply in replies" :key="reply.id" class="reply-item">
            <div class="reply-meta">
              <span>{{ reply.author_username }}</span>
              <span>{{ formatDate(reply.created_at) }}</span>
            </div>
            <p>{{ reply.content }}</p>
            <div v-if="canEditReply(reply)" class="author-actions">
              <button class="btn btn-secondary" @click="startReplyEdit(reply)">编辑回复</button>
              <button class="btn btn-danger" @click="deleteReply(reply.id)">删除回复</button>
            </div>
            <form v-if="editingReplyId === reply.id" class="edit-form" @submit.prevent="submitReplyEdit(reply.id)">
              <textarea v-model="replyEditContent" rows="4" required />
              <p v-if="replyEditError" class="form-error">{{ replyEditError }}</p>
              <div class="notice-actions">
                <button class="btn btn-primary" type="submit">保存回复</button>
                <button class="btn btn-secondary" type="button" @click="editingReplyId = null">取消</button>
              </div>
            </form>
          </div>
        </div>
        <div v-else class="empty-replies">还没有公开回复。注册并验证邮箱后，可以参与高质量讨论。</div>
        <div class="reply-composer">
          <div v-if="!authStore.isLoggedIn" class="auth-notice">
            <p>登录或注册后可以参与回复。</p>
            <div class="notice-actions">
              <NuxtLink class="btn btn-primary" :to="`/auth/login?redirect=${route.fullPath}`">登录</NuxtLink>
              <NuxtLink class="btn btn-secondary" to="/auth/register">注册</NuxtLink>
            </div>
          </div>
          <div v-else-if="!isVerified" class="auth-notice">
            <p>完成邮箱验证后可以参与回复。</p>
            <NuxtLink class="btn btn-primary" to="/user">前往用户中心</NuxtLink>
          </div>
          <form v-else-if="!thread.is_locked" class="reply-form" @submit.prevent="submitReply">
            <textarea v-model="replyContent" rows="4" required placeholder="分享你的研究观点、复现经验或风险提醒。" />
            <p v-if="replyError" class="form-error">{{ replyError }}</p>
            <button class="btn btn-primary" type="submit" :disabled="submittingReply">{{ submittingReply ? '提交中...' : '发表回复' }}</button>
          </form>
          <div v-else class="auth-notice">
            <p>该主题已锁定，暂不能继续回复。</p>
          </div>
        </div>
      </section>
    </template>
  </article>
</template>

<script setup lang="ts">
const { $api } = useNuxtApp()
const route = useRoute()
const authStore = useAuthStore()

if (!authStore.isLoggedIn) {
  authStore.restoreSession()
}
if (authStore.isLoggedIn && !authStore.user) {
  await authStore.fetchUser()
}

const threadId = computed(() => route.params.id as string)
const { data, pending, error } = await useAsyncData(
  () => `forum-thread-${threadId.value}`,
  () => $api.get(`/forum/threads/${threadId.value}`),
  { watch: [threadId] }
)

const thread = computed(() => data.value?.data?.thread)
const replies = computed(() => data.value?.data?.replies || [])
const isVerified = computed(() => Boolean(authStore.user?.email_verified_at || authStore.user?.email_verified))
const currentUserId = computed(() => authStore.user?.id)
const canEditThread = computed(() => Boolean(currentUserId.value && thread.value?.author_id === currentUserId.value))
const replyContent = ref('')
const replyError = ref('')
const submittingReply = ref(false)
const editingThread = ref(false)
const threadEdit = reactive({ title: '', content: '' })
const threadEditError = ref('')
const editingReplyId = ref<number | null>(null)
const replyEditContent = ref('')
const replyEditError = ref('')

const submitReply = async () => {
  replyError.value = ''
  submittingReply.value = true
  try {
    await $api.post(`/forum/threads/${threadId.value}/replies`, { content: replyContent.value })
    replyContent.value = ''
    await refreshNuxtData(`forum-thread-${threadId.value}`)
  } catch (error: any) {
    replyError.value = error.message || '回复失败，请稍后重试。'
  } finally {
    submittingReply.value = false
  }
}

const startThreadEdit = () => {
  threadEdit.title = thread.value?.title || ''
  threadEdit.content = thread.value?.content || ''
  threadEditError.value = ''
  editingThread.value = true
}

const submitThreadEdit = async () => {
  threadEditError.value = ''
  try {
    await $api.patch(`/forum/threads/${threadId.value}`, { title: threadEdit.title, content: threadEdit.content })
    editingThread.value = false
    await refreshNuxtData(`forum-thread-${threadId.value}`)
  } catch (error: any) {
    threadEditError.value = error.message || '保存失败，请稍后重试。'
  }
}

const deleteThread = async () => {
  if (!confirm('确定要删除这个主题吗？')) return
  await $api.delete(`/forum/threads/${threadId.value}`)
  await navigateTo('/forum')
}

const canEditReply = (reply: any) => Boolean(currentUserId.value && reply.author_id === currentUserId.value)

const startReplyEdit = (reply: any) => {
  editingReplyId.value = reply.id
  replyEditContent.value = reply.content
  replyEditError.value = ''
}

const submitReplyEdit = async (replyId: number) => {
  replyEditError.value = ''
  try {
    await $api.patch(`/forum/replies/${replyId}`, { content: replyEditContent.value })
    editingReplyId.value = null
    await refreshNuxtData(`forum-thread-${threadId.value}`)
  } catch (error: any) {
    replyEditError.value = error.message || '保存失败，请稍后重试。'
  }
}

const deleteReply = async (replyId: number) => {
  if (!confirm('确定要删除这条回复吗？')) return
  await $api.delete(`/forum/replies/${replyId}`)
  await refreshNuxtData(`forum-thread-${threadId.value}`)
}

const formatDate = (dateStr: string) => {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleDateString('zh-CN')
}

useHead(() => ({
  title: thread.value ? `${thread.value.title} - 论坛 - AI For Investor` : '论坛主题 - AI For Investor',
  meta: [
    { name: 'description', content: thread.value?.content?.slice(0, 120) || 'AI 投资研究与工具体验社区讨论' },
  ],
}))
</script>

<style scoped>
.thread-detail-page {
  max-width: 860px;
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

.thread-card,
.reply-section {
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-xl);
}

.thread-category {
  color: var(--color-primary);
  font-size: var(--font-size-sm);
  margin-bottom: var(--space-3);
}

.thread-title {
  font-size: var(--font-size-2xl);
  color: var(--color-text);
  margin-bottom: var(--space-3);
}

.thread-meta,
.reply-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-4);
  color: var(--color-text-subtle);
  font-size: var(--font-size-sm);
  margin-bottom: var(--space-5);
}

.thread-content {
  white-space: pre-wrap;
  line-height: 1.8;
  color: var(--color-text);
}

.reply-section {
  margin-top: var(--space-6);
}

.reply-title {
  font-size: var(--font-size-lg);
  margin-bottom: var(--space-4);
}

.reply-list {
  display: flex;
  flex-direction: column;
  gap: var(--space-4);
}

.reply-item {
  padding-bottom: var(--space-4);
  border-bottom: 1px solid var(--color-border);
}

.reply-item:last-child {
  padding-bottom: 0;
  border-bottom: 0;
}

.empty-replies,
.loading,
.error {
  padding: var(--space-8);
  text-align: center;
  color: var(--color-text-muted);
}

.reply-composer {
  margin-top: var(--space-6);
}

.auth-notice,
.reply-form {
  padding: var(--space-4);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  background-color: var(--color-surface-muted);
}

.reply-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
}

.reply-form textarea {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

.edit-form {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.edit-form input,
.edit-form textarea {
  padding: var(--space-3);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  background-color: var(--color-surface);
  color: var(--color-text);
  font: inherit;
}

.author-actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-4);
}

.notice-actions {
  display: flex;
  gap: var(--space-3);
  margin-top: var(--space-3);
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
  background-color: var(--color-surface);
  color: var(--color-text);
}

.btn-danger {
  background-color: var(--color-danger);
  color: white;
}

.form-error {
  color: var(--color-danger);
}
</style>
