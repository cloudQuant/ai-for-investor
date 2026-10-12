import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '@/api/auth'
import {
  beginSession,
  getSessionGeneration,
  getToken,
  setToken,
} from '@/utils/tokenRef'
import type { UserInfo, LoginRequest, RegisterRequest } from '@/types'
import { clearAccessToken } from '@/utils/session'
import { useStrategyStore } from '@/stores/strategy'
import { useBacktestStore } from '@/stores/backtest'
import { useSimulationStore } from '@/stores/simulation'
import { useWorkspaceStore } from '@/stores/workspace'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(null)
  const refreshToken = ref<string | null>(null)
  const user = ref<UserInfo | null>(null)
  const initialized = ref(false)
  const identityStatus = ref<'anonymous' | 'loading' | 'retryable_error' | 'confirmed'>('anonymous')
  const identityError = ref<string | null>(null)
  let initializePromise: Promise<void> | null = null
  let loginAttemptGeneration = 0
  let profileRequestGeneration = 0
  let lastIdentityFailure: unknown = null

  const isIdentityConfirmed = computed(() =>
    !!token.value && !!user.value && identityStatus.value === 'confirmed',
  )
  const isAuthenticated = computed(() => isIdentityConfirmed.value)

  function isUnauthorized(error: unknown): boolean {
    if (!error || typeof error !== 'object' || !('response' in error)) {
      return false
    }
    return (error as { response?: { status?: number } }).response?.status === 401
  }

  function getFailureMessage(error: unknown): string {
    return error instanceof Error ? error.message : 'Unable to confirm the current user.'
  }

  async function login(data: LoginRequest) {
    const attempt = ++loginAttemptGeneration
    const response = await authApi.login(data)
    if (attempt !== loginAttemptGeneration) {
      throw new Error('Login attempt was superseded.')
    }

    useWorkspaceStore().resetForSession()
    token.value = response.access_token
    refreshToken.value = null
    user.value = null
    identityStatus.value = 'loading'
    identityError.value = null
    initialized.value = false
    const sessionGeneration = beginSession(response.access_token)
    const confirmed = await fetchUser(sessionGeneration)

    if (
      sessionGeneration === getSessionGeneration()
      && token.value === response.access_token
    ) {
      initialized.value = true
    }

    if (!confirmed) {
      throw lastIdentityFailure ?? new Error(identityError.value || 'Unable to confirm the current user.')
    }
  }

  async function register(data: RegisterRequest) {
    await authApi.register(data)
  }

  async function fetchUser(expectedSessionGeneration?: number): Promise<boolean> {
    const requestToken = token.value
    if (!requestToken) {
      user.value = null
      identityStatus.value = 'anonymous'
      identityError.value = null
      return false
    }

    if (expectedSessionGeneration === undefined && getToken() !== requestToken) {
      setToken(requestToken)
    }

    const sessionGeneration = expectedSessionGeneration ?? getSessionGeneration()
    if (sessionGeneration !== getSessionGeneration()) {
      return false
    }

    const requestGeneration = ++profileRequestGeneration
    lastIdentityFailure = null
    user.value = null
    identityStatus.value = 'loading'
    identityError.value = null

    const isCurrentRequest = () =>
      sessionGeneration === getSessionGeneration()
      && requestGeneration === profileRequestGeneration
      && token.value === requestToken

    try {
      const currentUser = await authApi.getMe()
      if (!isCurrentRequest()) {
        return false
      }
      user.value = currentUser
      identityStatus.value = 'confirmed'
      return true
    } catch (error) {
      // The API interceptor expires the matching session before this catch
      // runs. During bootstrap there is no app-level expiry listener yet, so
      // clear the still-matching Pinia identity here as well. A newer session
      // keeps its token reference and cannot be logged out by this request.
      if (
        sessionGeneration !== getSessionGeneration()
        && requestGeneration === profileRequestGeneration
        && token.value === requestToken
        && getToken() === null
        && isUnauthorized(error)
      ) {
        logout()
        return false
      }

      if (!isCurrentRequest()) {
        return false
      }

      lastIdentityFailure = error
      if (isUnauthorized(error)) {
        logout()
      } else {
        identityStatus.value = 'retryable_error'
        identityError.value = getFailureMessage(error)
      }
      return false
    }
  }

  async function initialize() {
    if (initialized.value) {
      return
    }
    if (initializePromise) {
      await initializePromise
      return
    }

    initializePromise = (async () => {
      const storedToken = token.value
      if (!storedToken) {
        identityStatus.value = 'anonymous'
        initialized.value = true
        return
      }

      if (getToken() !== storedToken) {
        setToken(storedToken)
      }
      const sessionGeneration = getSessionGeneration()
      await fetchUser(sessionGeneration)
      if (
        sessionGeneration === getSessionGeneration()
        && token.value === storedToken
      ) {
        initialized.value = true
      }
    })()

    try {
      await initializePromise
    } finally {
      initializePromise = null
    }
  }

  function logout() {
    loginAttemptGeneration += 1
    profileRequestGeneration += 1
    token.value = null
    refreshToken.value = null
    user.value = null
    identityStatus.value = 'anonymous'
    identityError.value = null
    lastIdentityFailure = null
    initialized.value = true
    setToken(null)
    clearAccessToken()
    useWorkspaceStore().resetForSession()
    // Clear business store state so stale data doesn't persist after logout
    try {
      const strategyStore = useStrategyStore()
      strategyStore.strategies = []
      strategyStore.templates = []
      strategyStore.currentStrategy = null
      strategyStore.total = 0
      const backtestStore = useBacktestStore()
      backtestStore.results = []
      backtestStore.currentResult = null
      backtestStore.total = 0
      const simulationStore = useSimulationStore()
      simulationStore.instances = []
      simulationStore.total = 0
    } catch {
      // Store cleanup is best-effort; auth state is already cleared
    }
  }

  // 初始化时获取用户信息
  if (token.value) {
    void initialize()
  }

  return {
    token,
    refreshToken,
    user,
    initialized,
    identityStatus,
    identityError,
    isIdentityConfirmed,
    isAuthenticated,
    login,
    register,
    fetchUser,
    initialize,
    logout,
  }
}, {
  persist: {
    storage: sessionStorage,
    paths: ['token', 'refreshToken'],
  },
})
