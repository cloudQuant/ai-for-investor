<template>
  <div class="user-menu">
    <template v-if="isLoggedIn">
      <NuxtLink to="/user" class="user-avatar">
        <img v-if="user?.avatar_url" :src="user.avatar_url" alt="avatar" />
        <span v-else class="avatar-placeholder">{{ user?.username?.[0]?.toUpperCase() }}</span>
      </NuxtLink>
    </template>
    <template v-else>
      <NuxtLink to="/auth/login" class="auth-link">登录</NuxtLink>
      <NuxtLink to="/auth/register" class="auth-link register">注册</NuxtLink>
    </template>
  </div>
</template>

<script setup lang="ts">
const authStore = useAuthStore()

const isLoggedIn = computed(() => authStore.isLoggedIn)
const user = computed(() => authStore.user)
</script>

<style scoped>
.user-menu {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.user-avatar {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-full);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: var(--color-primary);
  color: white;
  text-decoration: none;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-placeholder {
  font-size: var(--font-size-sm);
  font-weight: 600;
}

.auth-link {
  color: var(--color-text-muted);
  text-decoration: none;
  font-size: var(--font-size-sm);
}

.auth-link:hover {
  color: var(--color-text);
}

.auth-link.register {
  background-color: var(--color-primary);
  color: white;
  padding: var(--space-2) var(--space-4);
  border-radius: var(--radius-md);
}
</style>
