export default defineNuxtRouteMiddleware(async (to) => {
  const authStore = useAuthStore()

  if (!authStore.isLoggedIn) {
    authStore.restoreSession()
  }

  if (!authStore.isLoggedIn) {
    return navigateTo({ path: '/auth/login', query: { redirect: to.fullPath } })
  }

  if (!authStore.user) {
    await authStore.fetchUser()
  }

  if (!authStore.isLoggedIn) {
    return navigateTo({ path: '/auth/login', query: { redirect: to.fullPath } })
  }
})
