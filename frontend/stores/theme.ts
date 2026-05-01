import { defineStore } from 'pinia'

interface ThemeState {
  currentTheme: string
  availableThemes: Array<{ id: string; name: string; description: string }>
}

export const useThemeStore = defineStore('theme', {
  state: (): ThemeState => ({
    currentTheme: 'fintech-trust-light',
    availableThemes: [
      { id: 'fintech-trust-light', name: '金融可信', description: '清爽浅色，适合公共内容传播' },
      { id: 'terminal-agent-dark', name: '开发者暗色', description: 'AI Agent、代码和工具讨论' },
      { id: 'minimal-focus', name: '极简专注', description: '降低视觉噪音，提高浏览效率' },
      { id: 'research-docs-light', name: '研究文档', description: '适合教程、长帖和项目复盘' },
    ],
  }),

  actions: {
    setTheme(themeId: string) {
      this.currentTheme = themeId
      if (import.meta.client) {
        document.documentElement.setAttribute('data-theme', themeId)
        useCookie('ui_theme').value = themeId
      }
    },
  },
})
