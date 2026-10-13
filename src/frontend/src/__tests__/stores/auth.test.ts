import { describe, it, expect, vi, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { workspaceApi } from '@/api/workspace'
import * as sessionUtils from '@/utils/session'
import { setToken } from '@/utils/tokenRef'

// Mock the auth API
vi.mock('@/api/auth', () => ({
  authApi: {
    login: vi.fn().mockResolvedValue({
      access_token: 'mock-token',
      token_type: 'bearer',
      expires_in: 86400,
    }),
    register: vi.fn().mockResolvedValue({
      id: '1',
      username: 'testuser',
      email: 'test@test.com',
      is_active: true,
      created_at: '2024-01-01T00:00:00',
    }),
    getMe: vi.fn().mockResolvedValue({
      id: '1',
      username: 'testuser',
      email: 'test@test.com',
      is_active: true,
      created_at: '2024-01-01T00:00:00',
    }),
  },
}))

// Mock strategy API
vi.mock('@/api/strategy', () => ({
  strategyApi: {
    getTemplates: vi.fn().mockResolvedValue({ templates: [], total: 0 }),
  },
}))

vi.mock('@/api/workspace', () => ({
  workspaceApi: {
    get: vi.fn(),
    listUnits: vi.fn(),
  },
}))

// Mock session utils
vi.mock('@/utils/session', () => ({
  getAccessToken: vi.fn(() => null),
  setAccessToken: vi.fn(),
  clearAccessToken: vi.fn(),
}))

describe('useAuthStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    setToken(null)
  })

  function deferred<T>() {
    let resolve!: (value: T) => void
    let reject!: (reason?: unknown) => void
    const promise = new Promise<T>((resolvePromise, rejectPromise) => {
      resolve = resolvePromise
      reject = rejectPromise
    })
    return { promise, resolve, reject }
  }

  it('should start unauthenticated', () => {
    const store = useAuthStore()
    expect(store.isAuthenticated).toBe(false)
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
  })

  it('should login and set token', async () => {
    const store = useAuthStore()
    await store.login({ username: 'testuser', password: 'password123' })
    expect(store.token).toBe('mock-token')
    expect(store.isAuthenticated).toBe(true)
  })

  it('should fetch user after login', async () => {
    const store = useAuthStore()
    await store.login({ username: 'testuser', password: 'password123' })
    expect(store.user).not.toBeNull()
    expect(store.user?.username).toBe('testuser')
  })

  it('should logout and clear state', async () => {
    const store = useAuthStore()
    const workspaceStore = useWorkspaceStore()
    await store.login({ username: 'testuser', password: 'password123' })
    workspaceStore.workspaces = [{ id: 'shared' } as never]
    workspaceStore.currentWorkspace = { id: 'shared' } as never
    workspaceStore.units = [{ id: 'unit-shared', workspace_id: 'shared' } as never]
    workspaceStore.selectedUnitIds = ['unit-shared']
    workspaceStore.activeWorkspaceId = 'shared'
    store.logout()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.isAuthenticated).toBe(false)
    expect(sessionUtils.clearAccessToken).toHaveBeenCalled()
    expect(workspaceStore.workspaces).toEqual([])
    expect(workspaceStore.currentWorkspace).toBeNull()
    expect(workspaceStore.units).toEqual([])
    expect(workspaceStore.selectedUnitIds).toEqual([])
    expect(workspaceStore.activeWorkspaceId).toBeNull()
    expect(workspaceStore.loading).toBe(false)
  })

  it('should register without setting token', async () => {
    const store = useAuthStore()
    await store.register({ username: 'newuser', email: 'new@test.com', password: 'password123' })
    expect(store.token).toBeNull()
    expect(store.isAuthenticated).toBe(false)
  })

  it('fetchUser is a no-op when token is null', async () => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    await store.fetchUser()
    expect(authApi.getMe).not.toHaveBeenCalled()
  })

  it.each([
    ['503 response', { response: { status: 503 } }],
    ['network error', new Error('network unavailable')],
  ])('keeps credentials and pending identity after a transient %s', async (_label, error) => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    store.token = 'valid-token'
    const getMeRequest = deferred<any>()
    vi.mocked(authApi.getMe).mockReturnValueOnce(getMeRequest.promise)

    const pendingFetch = store.fetchUser()
    expect(store.identityStatus).toBe('loading')
    getMeRequest.reject(error)
    expect(await pendingFetch).toBe(false)

    expect(store.token).toBe('valid-token')
    expect(store.user).toBeNull()
    expect(store.identityStatus).toBe('retryable_error')
    expect(store.identityError).toBeTruthy()
    expect(store.isAuthenticated).toBe(false)
    expect(sessionUtils.clearAccessToken).not.toHaveBeenCalled()
  })

  it('confirms identity on retry without submitting another login', async () => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    const loginError = { response: { status: 503 } }
    vi.mocked(authApi.getMe).mockRejectedValueOnce(loginError)

    await expect(store.login({ username: 'testuser', password: 'password123' }))
      .rejects.toBe(loginError)
    expect(store.token).toBe('mock-token')
    expect(store.identityStatus).toBe('retryable_error')
    expect(store.isAuthenticated).toBe(false)

    vi.mocked(authApi.getMe).mockResolvedValueOnce({
      id: '1', username: 'testuser', email: 'test@test.com', is_active: true,
      created_at: '2024-01-01T00:00:00',
    })
    expect(await store.fetchUser()).toBe(true)
    expect(store.identityStatus).toBe('confirmed')
    expect(store.isAuthenticated).toBe(true)
    expect(authApi.login).toHaveBeenCalledTimes(1)
  })

  it('logs out when getMe returns a real 401', async () => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    store.token = 'expired-token'
    vi.mocked(authApi.getMe).mockRejectedValueOnce({ response: { status: 401 } })

    expect(await store.fetchUser()).toBe(false)
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(store.identityStatus).toBe('anonymous')
    expect(sessionUtils.clearAccessToken).toHaveBeenCalled()
  })

  it.each(['late 401', 'late success'])('does not let an old session A response replace login B (%s)', async (responseKind) => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    const oldResponse = deferred<any>()
    vi.mocked(authApi.getMe)
      .mockReturnValueOnce(oldResponse.promise)
      .mockResolvedValueOnce({
        id: '2', username: 'user-b', email: 'b@test.com', is_active: true,
        created_at: '2024-01-01T00:00:00',
      })
    store.token = 'token-a'
    const requestA = store.fetchUser()

    vi.mocked(authApi.login).mockResolvedValueOnce({
      access_token: 'token-b', token_type: 'bearer', expires_in: 86400,
    })
    await store.login({ username: 'user-b', password: 'password123' })
    expect(store.token).toBe('token-b')
    expect(store.user?.username).toBe('user-b')

    if (responseKind === 'late 401') {
      oldResponse.reject({ response: { status: 401 } })
    } else {
      oldResponse.resolve({
        id: '1', username: 'user-a', email: 'a@test.com', is_active: true,
        created_at: '2024-01-01T00:00:00',
      })
    }
    await requestA

    expect(store.token).toBe('token-b')
    expect(store.user?.username).toBe('user-b')
    expect(store.isAuthenticated).toBe(true)
    expect(sessionUtils.clearAccessToken).not.toHaveBeenCalled()
  })

  it('clears workspace A as soon as login B starts identity confirmation', async () => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    const workspaceStore = useWorkspaceStore()
    const detailA = deferred<any>()
    const unitsA = deferred<any>()
    const identityB = deferred<any>()

    store.token = 'token-a'
    store.user = {
      id: 'user-a', username: 'user-a', email: 'a@test.com', is_active: true,
      created_at: '2024-01-01T00:00:00',
    }
    store.identityStatus = 'confirmed'
    setToken('token-a')
    workspaceStore.activateWorkspace('shared')
    workspaceStore.workspaces = [{ id: 'shared' } as never]
    workspaceStore.currentWorkspace = { id: 'shared', name: 'Workspace A' } as never
    workspaceStore.units = [{ id: 'unit-a', workspace_id: 'shared' } as never]
    workspaceStore.setSelectedUnitIds(['unit-a'])

    vi.mocked(workspaceApi.get).mockReturnValueOnce(detailA.promise as never)
    vi.mocked(workspaceApi.listUnits).mockReturnValueOnce(unitsA.promise as never)
    const detailRequestA = workspaceStore.fetchWorkspace('shared')
    const unitsRequestA = workspaceStore.fetchUnits('shared')

    vi.mocked(authApi.login).mockResolvedValueOnce({
      access_token: 'token-b', token_type: 'bearer', expires_in: 86400,
    })
    vi.mocked(authApi.getMe).mockReturnValueOnce(identityB.promise)
    const loginB = store.login({ username: 'user-b', password: 'password123' })
    await Promise.resolve()

    expect(authApi.getMe).toHaveBeenCalledTimes(1)
    expect(store.token).toBe('token-b')
    expect(store.identityStatus).toBe('loading')
    expect(store.user).toBeNull()
    expect(store.isAuthenticated).toBe(false)
    expect(workspaceStore.workspaces).toEqual([])
    expect(workspaceStore.currentWorkspace).toBeNull()
    expect(workspaceStore.units).toEqual([])
    expect(workspaceStore.selectedUnitIds).toEqual([])
    expect(workspaceStore.activeWorkspaceId).toBeNull()
    expect(workspaceStore.loading).toBe(false)

    detailA.resolve({ id: 'shared', name: 'Late workspace A' })
    unitsA.resolve({
      items: [{ id: 'unit-a', workspace_id: 'shared' }],
      total: 1,
    })
    await Promise.all([detailRequestA, unitsRequestA])
    expect(workspaceStore.currentWorkspace).toBeNull()
    expect(workspaceStore.units).toEqual([])

    identityB.resolve({
      id: 'user-b', username: 'user-b', email: 'b@test.com', is_active: true,
      created_at: '2024-01-01T00:00:00',
    })
    await loginB
    expect(store.user?.username).toBe('user-b')
    expect(store.isAuthenticated).toBe(true)
    expect(workspaceStore.currentWorkspace).toBeNull()
    expect(workspaceStore.units).toEqual([])
  })

  it('initialize is a no-op when already initialized', async () => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    await store.login({ username: 'testuser', password: 'password123' })
    expect(store.initialized).toBe(true)

    vi.mocked(authApi.getMe).mockClear()
    await store.initialize()
    expect(authApi.getMe).not.toHaveBeenCalled()
  })

  it('initialize validates a session-persisted token', async () => {
    const { authApi } = await import('@/api/auth')

    const store = useAuthStore()
    store.token = 'session-token'
    await store.initialize()

    expect(store.token).toBe('session-token')
    expect(store.user).not.toBeNull()
    expect(authApi.getMe).toHaveBeenCalled()
    expect(store.initialized).toBe(true)
  })

  it('keeps a persisted token but remains unauthenticated when startup identity validation is transiently unavailable', async () => {
    const { authApi } = await import('@/api/auth')
    const store = useAuthStore()
    const profileRequest = deferred<any>()
    store.token = 'persisted-token'
    vi.mocked(authApi.getMe).mockReturnValueOnce(profileRequest.promise)

    const initialization = store.initialize()
    expect(store.isAuthenticated).toBe(false)
    profileRequest.reject({ response: { status: 503 } })
    await initialization

    expect(store.token).toBe('persisted-token')
    expect(store.identityStatus).toBe('retryable_error')
    expect(store.initialized).toBe(true)
    expect(store.isAuthenticated).toBe(false)
    expect(sessionUtils.clearAccessToken).not.toHaveBeenCalled()
  })

  it('initialize without a session token does nothing extra', async () => {
    const { authApi } = await import('@/api/auth')

    const store = useAuthStore()
    await store.initialize()

    expect(store.token).toBeNull()
    expect(authApi.getMe).not.toHaveBeenCalled()
    expect(store.initialized).toBe(true)
  })

  it('initialize de-duplicates concurrent calls', async () => {
    const { authApi } = await import('@/api/auth')

    const store = useAuthStore()
    store.token = 'token-x'
    const p1 = store.initialize()
    const p2 = store.initialize()
    await Promise.all([p1, p2])

    // getMe should be called exactly once despite two concurrent initialize() calls
    expect(authApi.getMe).toHaveBeenCalledTimes(1)
  })

  it('logout is resilient when business stores are not registered', () => {
    // Build a fresh store without first installing the strategy/backtest/sim
    // stores. The catch block in logout() should swallow any thrown errors.
    const store = useAuthStore()
    expect(() => store.logout()).not.toThrow()
    expect(store.token).toBeNull()
  })
})
