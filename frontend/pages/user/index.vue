<template>
  <div class="user-center">
    <h1 class="page-title">用户中心</h1>

    <div class="state-card" v-if="isLoadingUser">正在加载用户信息...</div>
    <div class="state-card unauthorized" v-else-if="!authStore.user">
      <h2>需要登录</h2>
      <p>请登录后访问用户中心，查看你的内容、设置和工具运行记录。</p>
      <NuxtLink to="/auth/login?redirect=/user" class="action-link">前往登录</NuxtLink>
    </div>

    <div class="user-info" v-if="authStore.user">
      <div class="avatar-large">
        <img v-if="authStore.user.avatar_url" :src="authStore.user.avatar_url" alt="avatar" />
        <span v-else class="avatar-placeholder">{{ authStore.user.username?.[0]?.toUpperCase() }}</span>
      </div>
      <div class="user-details">
        <h2 class="username">{{ authStore.user.username }}</h2>
        <p class="user-email">{{ authStore.user.email }}</p>
        <p class="user-status">
          <span v-if="authStore.user.email_verified_at" class="verified">已验证邮箱</span>
          <span v-else class="unverified">未验证邮箱</span>
        </p>
      </div>
    </div>

    <div v-if="authStore.user && !authStore.user.email_verified" class="verification-notice">
      <strong>需要验证邮箱</strong>
      <p>发帖、回复和创建工具任务前，请先完成邮箱验证。如果验证链接已过期，请重新注册或联系管理员重新发送。</p>
    </div>

    <div class="menu-section">
      <h3 class="section-title">内容管理</h3>
      <div class="menu-grid">
        <NuxtLink to="/user/posts" class="menu-item">
          <span class="menu-icon">📝</span>
          <span class="menu-label">我的帖子</span>
        </NuxtLink>
        <NuxtLink to="/user/favorites" class="menu-item">
          <span class="menu-icon">⭐</span>
          <span class="menu-label">我的收藏</span>
        </NuxtLink>
        <NuxtLink to="/user/jobs" class="menu-item">
          <span class="menu-icon">🔧</span>
          <span class="menu-label">工具记录</span>
        </NuxtLink>
      </div>
    </div>

    <div class="menu-section">
      <h3 class="section-title">设置</h3>
      <div class="menu-grid">
        <NuxtLink to="/user/profile" class="menu-item">
          <span class="menu-icon">👤</span>
          <span class="menu-label">个人资料</span>
        </NuxtLink>
        <NuxtLink to="/user/preferences" class="menu-item">
          <span class="menu-icon">🎨</span>
          <span class="menu-label">外观设置</span>
        </NuxtLink>
      </div>
    </div>

    <div class="logout-section">
      <button @click="handleLogout" class="btn btn-danger">退出登录</button>
    </div>
  </div>
</template>

<script setup lang="ts">
definePageMeta({
  middleware: ['auth' as never],
})

const authStore = useAuthStore()
const router = useRouter()
const isLoadingUser = ref(true)

onMounted(async () => {
  try {
    if (!authStore.isLoggedIn) {
      await authStore.fetchUser()
    }
  } finally {
    isLoadingUser.value = false
  }
})

const handleLogout = async () => {
  await authStore.logout()
  router.push('/')
}

useHead({
  title: '用户中心 - AI For Investor',
})
</script>

<style scoped>
.user-center {
  padding: var(--space-4) 0;
  max-width: 800px;
  margin: 0 auto;
}

.page-title {
  font-size: var(--font-size-2xl);
  font-weight: 700;
  margin-bottom: var(--space-8);
}

.user-info {
  display: flex;
  gap: var(--space-6);
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-8);
}

.state-card {
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  margin-bottom: var(--space-8);
  color: var(--color-text-muted);
}

.state-card h2 {
  color: var(--color-text);
  margin-bottom: var(--space-2);
}

.state-card p {
  margin-bottom: var(--space-4);
}

.unauthorized {
  border-color: var(--color-warning);
}

.action-link {
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}

.avatar-large {
  width: 80px;
  height: 80px;
  border-radius: var(--radius-full);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-primary);
  color: white;
  font-size: var(--font-size-2xl);
  font-weight: 600;
}

.avatar-large img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.user-details {
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.username {
  font-size: var(--font-size-xl);
  font-weight: 600;
  margin-bottom: var(--space-1);
}

.user-email {
  font-size: var(--font-size-sm);
  color: var(--color-text-muted);
  margin-bottom: var(--space-2);
}

.verified {
  color: var(--color-success);
  font-size: var(--font-size-sm);
}

.unverified {
  color: var(--color-warning);
  font-size: var(--font-size-sm);
}

.verification-notice {
  padding: var(--space-4);
  margin-bottom: var(--space-8);
  background-color: var(--color-warning-bg, #fff7ed);
  border: 1px solid var(--color-warning);
  border-radius: var(--radius-lg);
  color: var(--color-text);
}

.verification-notice p {
  margin: var(--space-2) 0 0;
  color: var(--color-text-muted);
}

.menu-section {
  margin-bottom: var(--space-8);
}

.section-title {
  font-size: var(--font-size-md);
  font-weight: 600;
  color: var(--color-text-muted);
  margin-bottom: var(--space-4);
  text-transform: uppercase;
}

.menu-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
  gap: var(--space-4);
}

.menu-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-2);
  padding: var(--space-6);
  background-color: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  text-decoration: none;
  transition: all 0.2s;
}

.menu-item:hover {
  border-color: var(--color-primary);
}

.menu-icon {
  font-size: var(--font-size-2xl);
}

.menu-label {
  font-size: var(--font-size-sm);
  color: var(--color-text);
}

.logout-section {
  padding-top: var(--space-8);
  border-top: 1px solid var(--color-border);
}

.btn {
  padding: var(--space-3) var(--space-6);
  border-radius: var(--radius-md);
  font-size: var(--font-size-md);
  font-weight: 500;
  cursor: pointer;
  border: none;
}

.btn-danger {
  background-color: var(--color-danger);
  color: white;
}

@media (max-width: 640px) {
  .user-info {
    flex-direction: column;
    align-items: center;
    text-align: center;
  }

  .avatar-large {
    width: 64px;
    height: 64px;
  }

  .menu-grid {
    grid-template-columns: 1fr;
  }

  .btn {
    width: 100%;
  }
}
</style>
