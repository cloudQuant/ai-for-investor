import { defineStore } from 'pinia'

interface User {
  id: number
  email: string
  username: string
  avatar_url?: string
  bio?: string
  email_verified_at?: string
  email_verified?: boolean
  roles?: string[]
  is_active: boolean
}

interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isLoggedIn: boolean
}

export const useAuthStore = defineStore('auth', {
  state: (): AuthState => ({
    user: null,
    accessToken: null,
    refreshToken: null,
    isLoggedIn: false,
  }),

  actions: {
    restoreSession() {
      if (process.client) {
        this.accessToken = localStorage.getItem('access_token')
        this.refreshToken = localStorage.getItem('refresh_token')
        this.isLoggedIn = Boolean(this.accessToken)
      }
    },

    async login(email: string, password: string) {
      const { $api } = useNuxtApp()
      const response = await $api.post('/auth/login', { email, password })
      this.accessToken = response.data.access_token
      this.refreshToken = response.data.refresh_token
      this.isLoggedIn = true
      if (process.client && this.accessToken && this.refreshToken) {
        localStorage.setItem('access_token', this.accessToken)
        localStorage.setItem('refresh_token', this.refreshToken)
      }
      await this.fetchUser()
    },

    async register(email: string, username: string, password: string) {
      const { $api } = useNuxtApp()
      await $api.post('/auth/register', { email, username: username || undefined, password })
    },

    async fetchUser() {
      const { $api } = useNuxtApp()
      if (!this.accessToken) {
        this.restoreSession()
      }
      try {
        const response = await $api.get('/auth/me')
        this.user = response.data
        this.isLoggedIn = true
      } catch {
        this.user = null
        this.accessToken = null
        this.refreshToken = null
        this.isLoggedIn = false
        if (process.client) {
          localStorage.removeItem('access_token')
          localStorage.removeItem('refresh_token')
        }
      }
    },

    async logout() {
      const { $api } = useNuxtApp()
      if (this.accessToken) {
        try {
          await $api.post('/auth/logout')
        } catch {}
      }
      this.user = null
      this.accessToken = null
      this.refreshToken = null
      this.isLoggedIn = false
      if (process.client) {
        localStorage.removeItem('access_token')
        localStorage.removeItem('refresh_token')
      }
    },
  },
})
