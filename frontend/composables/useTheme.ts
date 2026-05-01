import { useThemeStore } from '~/stores/theme'

export function useTheme() {
  const themeStore = useThemeStore()

  const setTheme = async (themeId: string, options: { persistRemote?: boolean } = {}) => {
    themeStore.setTheme(themeId)
    if (options.persistRemote && import.meta.client) {
      const authStore = useAuthStore()
      if (authStore.isLoggedIn) {
        const { $api } = useNuxtApp()
        await $api.patch('/preferences/me/preferences', { ui_theme: themeId })
      }
    }
  }

  const initializeTheme = async () => {
    const savedTheme = useCookie('ui_theme').value as string || 'fintech-trust-light'
    themeStore.setTheme(savedTheme)

    if (import.meta.client) {
      const authStore = useAuthStore()
      if (authStore.isLoggedIn) {
        try {
          const { $api } = useNuxtApp()
          const response = await $api.get('/preferences/me/preferences')
          if (response.data?.ui_theme) {
            themeStore.setTheme(response.data.ui_theme)
          }
        } catch {}
      }
    }
  }

  const currentTheme = computed(() => themeStore.currentTheme)
  const availableThemes = computed(() => themeStore.availableThemes)

  return {
    theme: currentTheme,
    setTheme,
    initializeTheme,
    availableThemes,
  }
}
