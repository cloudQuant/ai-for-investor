export default defineNuxtPlugin(() => {
  const authStore = useAuthStore()
  authStore.restoreSession()

  return {
    provide: {
      auth: {
        isLoggedIn: computed(() => authStore.isLoggedIn),
        user: computed(() => authStore.user),
        accessToken: computed(() => authStore.accessToken),
      },
    },
  }
})