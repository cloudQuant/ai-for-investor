/**
 * API 模块测试
 */
import { AxiosError } from 'axios'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

import { AUTH_EXPIRED_EVENT } from '@/utils/session'
import { beginSession, getSessionGeneration, setToken } from '@/utils/tokenRef'

// The auth store persists its session-scoped Pinia payload under this key.
const sessionStorageMock = (() => {
  let store: Record<string, string> = {}
  return {
    getItem: vi.fn((key: string) => store[key] || null),
    setItem: vi.fn((key: string, value: string) => { store[key] = value }),
    removeItem: vi.fn((key: string) => { delete store[key] }),
    clear: vi.fn(() => { store = {} }),
  }
})()
Object.defineProperty(global, 'sessionStorage', { value: sessionStorageMock })

// Mock Element Plus
vi.mock('element-plus/es/components/message/index.mjs', () => ({
  ElMessage: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}))

// Mock i18n: return Chinese fallback strings used by api/index.ts so existing
// assertions stay locale-stable across iteration 176 §C i18n refactor.
vi.mock('@/i18n', () => ({
  default: {
    global: {
      t: (key: string) => {
        const map: Record<string, string> = {
          'apiClient.errFieldFallback': '参数错误',
          'apiClient.errGenericFailure': '请求失败',
          'apiClient.errAuthExpired': '登录已过期，请重新登录',
          'apiClient.errForbidden': '没有权限访问',
          'apiClient.errNotFound': '资源不存在',
          'apiClient.errServerError': '服务器错误',
        }
        return map[key] ?? key
      },
    },
  },
}))

describe('API module', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorageMock.clear()
    setToken(null)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('基础配置', () => {
    it('应该导出默认的 axios 实例', async () => {
      const api = (await import('@/api/index')).default
      expect(api).toBeDefined()
      expect(api.defaults.baseURL).toBe('/api/v1')
      expect(api.defaults.timeout).toBe(30000)
    })

    it('应该设置正确的默认 headers', async () => {
      const api = (await import('@/api/index')).default
      expect(api.defaults.headers['Content-Type']).toBe('application/json')
    })
  })

  describe('拦截器', () => {
    it('应该注册请求拦截器', async () => {
      const api = (await import('@/api/index')).default
      expect(api.interceptors.request).toBeDefined()
      expect(api.interceptors.response).toBeDefined()
    })

    it('请求拦截器数量应该大于0', async () => {
      const api = (await import('@/api/index')).default
      expect((api.interceptors.request as any).handlers.length).toBeGreaterThan(0)
    })

    it('响应拦截器数量应该大于0', async () => {
      const api = (await import('@/api/index')).default
      expect((api.interceptors.response as any).handlers.length).toBeGreaterThan(0)
    })
  })

  describe('Token 处理', () => {
    it('应该能够从 sessionStorage 获取 Pinia auth token', () => {
      sessionStorageMock.setItem('auth', JSON.stringify({ token: 'test-token-123' }))
      expect(sessionStorageMock.getItem('auth')).toContain('test-token-123')
    })

    it('sessionStorage 没有 auth payload 时应该返回 null', () => {
      expect(sessionStorageMock.getItem('auth')).toBeNull()
    })

    it('应该能够清除 auth payload', () => {
      sessionStorageMock.setItem('auth', JSON.stringify({ token: 'test-token-123' }))
      sessionStorageMock.removeItem('auth')
      expect(sessionStorageMock.getItem('auth')).toBeNull()
    })
  })

  describe('请求拦截器逻辑', () => {
    it('should add token to request headers when token exists', async () => {
      const api = (await import('@/api/index')).default
      sessionStorageMock.setItem('auth', JSON.stringify({ token: 'my-jwt-token' }))
      const handler = (api.interceptors.request as any).handlers[0]
      const config = { headers: {} as any }
      const result = handler.fulfilled(config)
      expect(result.headers.Authorization).toBe('Bearer my-jwt-token')
    })

    it('should not add Authorization when no token', async () => {
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.request as any).handlers[0]
      const config = { headers: {} as any }
      const result = handler.fulfilled(config)
      expect(result.headers.Authorization).toBeUndefined()
    })

    it('request error handler rejects', async () => {
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.request as any).handlers[0]
      const err = new Error('req error')
      await expect(handler.rejected(err)).rejects.toThrow('req error')
    })

    it('rejects a request config after its captured session has been replaced', async () => {
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.request as any).handlers[0]
      beginSession('token-a')
      const config = handler.fulfilled({ headers: {} })
      expect(config.headers.Authorization).toBe('Bearer token-a')

      beginSession('token-b')

      expect(() => handler.fulfilled(config)).toThrow('Request belongs to a superseded session')
    })
  })

  describe('响应拦截器逻辑', () => {
    it('should return response.data on success', async () => {
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const result = handler.fulfilled({ data: { foo: 'bar' }, status: 200 })
      expect(result).toEqual({ foo: 'bar' })
    })

    it('should handle 401 error', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      sessionStorageMock.setItem('auth', JSON.stringify({ token: 'my-jwt-token' }))
      const error = {
        config: {
          __sessionGeneration: getSessionGeneration(),
          __sessionToken: 'my-jwt-token',
        },
        response: { status: 401, data: {} },
      }
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
        'auth',
        expect.stringContaining('"token":null'),
      )
      expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({ type: AUTH_EXPIRED_EVENT }))
      expect(ElMessage.error).toHaveBeenCalledWith('登录已过期，请重新登录')
    })

    it('should handle 403 error', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const error = { response: { status: 403, data: {} } }
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(ElMessage.error).toHaveBeenCalledWith('没有权限访问')
    })

    it('should handle 404 error', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const error = { response: { status: 404, data: {} } }
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(ElMessage.error).toHaveBeenCalledWith('资源不存在')
    })

    it('should handle 500 error', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const error = { response: { status: 500, data: {} } }
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(ElMessage.error).toHaveBeenCalledWith('服务器错误')
    })

    it('should handle generic error with detail', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const error = { response: { status: 422, data: { detail: '验证错误' } } }
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(ElMessage.error).toHaveBeenCalledWith('验证错误')
    })

    it('should handle generic error without detail', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const error = { response: { status: 422, data: {} } }
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(ElMessage.error).toHaveBeenCalledWith('请求失败')
    })

    it('rejects an error without showing a toast when the caller suppresses messages', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const error = {
        config: { suppressErrorMessage: true },
        response: { status: 500, data: { detail: 'handled by caller' } },
      }

      await expect(handler.rejected(error)).rejects.toBe(error)

      expect(ElMessage.error).not.toHaveBeenCalled()
    })

    it.each([
      [403, 's3://private-bucket/raw-holdout'],
      [500, '/srv/research/internal.sqlite'],
    ])('suppresses raw server text for an approval-owned %i error', async (status, detail) => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const originalAdapter = api.defaults.adapter
      api.defaults.adapter = async (config) => {
        const response = {
          status,
          statusText: 'approval probe rejected',
          data: { detail },
          headers: {},
          config,
        }
        throw new AxiosError('approval probe rejected', undefined, config, undefined, response)
      }

      try {
        await expect(api.post('/approval-probe', {}, { suppressErrorToast: true })).rejects.toThrow(
          'approval probe rejected',
        )
      } finally {
        api.defaults.adapter = originalAdapter
      }

      expect(ElMessage.error).not.toHaveBeenCalled()
    })

    it('keeps ordinary API error toasts enabled through the real interceptor chain', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const originalAdapter = api.defaults.adapter
      api.defaults.adapter = async (config) => {
        const response = {
          status: 500,
          statusText: 'ordinary request rejected',
          data: { detail: 'ordinary failure' },
          headers: {},
          config,
        }
        throw new AxiosError('ordinary request rejected', undefined, config, undefined, response)
      }

      try {
        await expect(api.post('/ordinary-probe', {})).rejects.toThrow('ordinary request rejected')
      } finally {
        api.defaults.adapter = originalAdapter
      }

      expect(ElMessage.error).toHaveBeenCalledWith('ordinary failure')
    })

    it('still expires the auth session when a closed projector suppresses a 401 toast', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      sessionStorageMock.setItem('auth', JSON.stringify({ token: 'approval-token' }))
      const error = {
        config: {
          suppressErrorToast: true,
          __sessionGeneration: getSessionGeneration(),
          __sessionToken: 'approval-token',
        },
        response: { status: 401, data: { detail: 'file:///private/token' } },
      }

      await expect(handler.rejected(error)).rejects.toBe(error)

      expect(sessionStorageMock.setItem).toHaveBeenCalledWith(
        'auth',
        expect.stringContaining('"token":null'),
      )
      expect(dispatchSpy).toHaveBeenCalledWith(
        expect.objectContaining({ type: AUTH_EXPIRED_EVENT }),
      )
      expect(ElMessage.error).not.toHaveBeenCalled()
    })

    it('ignores a late 401 from session A after session B starts', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const originalAdapter = api.defaults.adapter
      const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
      let rejectAdapter!: (error: unknown) => void
      let requestConfig: any
      let markStarted!: () => void
      const started = new Promise<void>((resolve) => { markStarted = resolve })

      api.defaults.adapter = (config) => new Promise((_, reject) => {
        requestConfig = config
        rejectAdapter = reject
        markStarted()
      })

      try {
        beginSession('token-a')
        sessionStorageMock.setItem('auth', JSON.stringify({ token: 'token-a' }))
        const requestA = api.get('/session-a', { skipRetry: true })
        await started
        expect(requestConfig.headers.Authorization).toBe('Bearer token-a')

        beginSession('token-b')
        sessionStorageMock.setItem('auth', JSON.stringify({ token: 'token-b' }))
        const response = {
          status: 401,
          statusText: 'expired A',
          data: {},
          headers: {},
          config: requestConfig,
        }
        rejectAdapter(new AxiosError('expired A', undefined, requestConfig, undefined, response))

        await expect(requestA).rejects.toThrow('superseded session')
        expect(sessionStorageMock.getItem('auth')).toContain('token-b')
        expect(dispatchSpy).not.toHaveBeenCalledWith(
          expect.objectContaining({ type: AUTH_EXPIRED_EVENT }),
        )
        expect(ElMessage.error).not.toHaveBeenCalled()
      } finally {
        api.defaults.adapter = originalAdapter
      }
    })

    it('does not return a late success from session A to session B', async () => {
      const api = (await import('@/api/index')).default
      const originalAdapter = api.defaults.adapter
      let resolveAdapter!: (response: any) => void
      let requestConfig: any
      let markStarted!: () => void
      const started = new Promise<void>((resolve) => { markStarted = resolve })

      api.defaults.adapter = (config) => new Promise((resolve) => {
        requestConfig = config
        resolveAdapter = resolve
        markStarted()
      })

      try {
        beginSession('token-a')
        const requestA = api.get('/session-a-success')
        await started
        beginSession('token-b')
        resolveAdapter({
          data: { account: 'A' },
          status: 200,
          statusText: 'OK',
          headers: {},
          config: requestConfig,
        })

        await expect(requestA).rejects.toThrow('superseded session')
      } finally {
        api.defaults.adapter = originalAdapter
      }
    })

    it('does not retry a transient response under a replacement session', async () => {
      const api = (await import('@/api/index')).default
      const { RETRY_CONFIG } = await import('@/api/index')
      const originalAdapter = api.defaults.adapter
      const originalDelay = RETRY_CONFIG.initialDelay
      const originalJitter = RETRY_CONFIG.jitterRange
      let rejectAdapter!: (error: unknown) => void
      let requestConfig: any
      let markStarted!: () => void
      let adapterCalls = 0
      const started = new Promise<void>((resolve) => { markStarted = resolve })

      vi.useFakeTimers()
      RETRY_CONFIG.initialDelay = 1000
      RETRY_CONFIG.jitterRange = 0
      api.defaults.adapter = (config) => {
        adapterCalls += 1
        if (adapterCalls > 1) {
          return Promise.resolve({
            data: { account: 'unexpected-retry' },
            status: 200,
            statusText: 'OK',
            headers: {},
            config,
          })
        }
        return new Promise((_, reject) => {
          requestConfig = config
          rejectAdapter = reject
          markStarted()
        })
      }

      try {
        beginSession('token-a')
        const requestA = api.get('/retry-session-a')
        await started
        const rejectedRequest = expect(requestA).rejects.toThrow('superseded session')
        const response = {
          status: 503,
          statusText: 'unavailable',
          data: {},
          headers: {},
          config: requestConfig,
        }
        rejectAdapter(new AxiosError('unavailable', undefined, requestConfig, undefined, response))
        await Promise.resolve()
        await Promise.resolve()

        beginSession('token-b')
        await vi.advanceTimersByTimeAsync(1000)
        await rejectedRequest
        expect(adapterCalls).toBe(1)
        expect(requestConfig.headers.Authorization).toBe('Bearer token-a')
      } finally {
        api.defaults.adapter = originalAdapter
        RETRY_CONFIG.initialDelay = originalDelay
        RETRY_CONFIG.jitterRange = originalJitter
        vi.useRealTimers()
      }
    })
  })

  describe('API 导出', () => {
    it('应该有默认导出', async () => {
      const module = await import('@/api/index')
      expect(module.default).toBeDefined()
    })
  })

  describe('getErrorMessage helper', () => {
    it('returns fallback for unknown shape', async () => {
      const { getErrorMessage } = await import('@/api/index')
      expect(getErrorMessage('plain string', 'fallback')).toBe('fallback')
      expect(getErrorMessage(null, 'fallback')).toBe('fallback')
      expect(getErrorMessage(undefined, 'fallback')).toBe('fallback')
    })

    it('returns Error.message when given an Error instance', async () => {
      const { getErrorMessage } = await import('@/api/index')
      expect(getErrorMessage(new Error('boom'), 'fallback')).toBe('boom')
    })

    it('falls back when Error has empty message', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const err = new Error('')
      expect(getErrorMessage(err, 'fallback')).toBe('fallback')
    })

    it('returns axios response message when available', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { message: 'server says hi' } } }
      expect(getErrorMessage(e, 'fallback')).toBe('server says hi')
    })

    it('appends request_id when present', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { message: 'failed', request_id: 'req-123' } } }
      expect(getErrorMessage(e, 'fallback')).toBe('failed (request_id: req-123)')
    })

    it('extracts FastAPI 422 array detail', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { detail: [{ loc: ['body', 'foo'], msg: 'is required', type: 'value_error.missing' }] } } }
      expect(getErrorMessage(e, 'fallback')).toBe('is required')
    })

    it('handles object detail with message', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { detail: { message: 'nested object' } } } }
      expect(getErrorMessage(e, 'fallback')).toBe('nested object')
    })

    it('handles string detail directly', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { detail: 'string detail' } } }
      expect(getErrorMessage(e, 'fallback')).toBe('string detail')
    })

    it('extracts field-level error from details.fields', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { details: { fields: [{ field: 'username', message: 'too short' }] } } } }
      expect(getErrorMessage(e, 'fallback')).toBe('username: too short')
    })

    it('uses field-fallback when message missing in field error', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { details: { fields: [{ field: 'email' }] } } } }
      expect(getErrorMessage(e, 'fallback')).toBe('email: 参数错误')
    })

    it('uses field message alone when field name missing', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { details: { fields: [{ message: 'invalid' }] } } } }
      expect(getErrorMessage(e, 'fallback')).toBe('invalid')
    })

    it('falls back to user-provided message when extracted text equals generic 请求失败', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: {} } } // would extract '请求失败'
      // generic message should NOT be returned; fallback used instead
      expect(getErrorMessage(e, 'my fallback')).toBe('my fallback')
    })

    it('returns extracted msg when not generic', async () => {
      const { getErrorMessage } = await import('@/api/index')
      const e = { response: { data: { message: 'specific' } } }
      expect(getErrorMessage(e, 'my fallback')).toBe('specific')
    })
  })

  describe('Retry behavior on response interceptor', () => {
    it('retries an idempotent request after a transient response', async () => {
      const api = (await import('@/api/index')).default
      const { RETRY_CONFIG } = await import('@/api/index')
      const handler = (api.interceptors.response as any).handlers[0]
      const originalDelay = RETRY_CONFIG.initialDelay
      const originalJitter = RETRY_CONFIG.jitterRange
      const config = {
        method: 'GET',
        headers: {},
        __retryCount: 0,
        __sessionGeneration: getSessionGeneration(),
        __sessionToken: null,
      } as any
      const response = {
        status: 503,
        statusText: 'Service Unavailable',
        data: {},
        headers: {},
        config,
      }
      const error = new AxiosError('temporarily unavailable', undefined, config, undefined, response)

      vi.useFakeTimers()
      RETRY_CONFIG.initialDelay = 0
      RETRY_CONFIG.jitterRange = 0
      const retryRequest = vi.spyOn(api, 'request').mockResolvedValue({ ok: true } as never)
      try {
        const retryResult = handler.rejected(error)
        await vi.runAllTimersAsync()

        await expect(retryResult).resolves.toEqual({ ok: true })
        expect(retryRequest).toHaveBeenCalledWith(config)
        expect(config.__retryCount).toBe(1)
        expect(config.__isRetrying).toBe(true)
      } finally {
        retryRequest.mockRestore()
        RETRY_CONFIG.initialDelay = originalDelay
        RETRY_CONFIG.jitterRange = originalJitter
        vi.useRealTimers()
      }
    })

    it('should not duplicate ElMessage on retried failures (skip generic)', async () => {
      const { ElMessage } = await import('element-plus/es/components/message/index.mjs')
      const api = (await import('@/api/index')).default
      const handler = (api.interceptors.response as any).handlers[0]

      // Configure error to look like an in-progress retry where final retry exhausted
      const error = {
        config: { __isRetrying: true, __retryCount: 5 },
        response: { status: 500, data: {} },
      }
      // Since __retryCount (5) >= maxRetries (3), the early-skip branch fires
      // and ElMessage.error is called.
      await expect(handler.rejected(error)).rejects.toBe(error)
      expect(ElMessage.error).toHaveBeenCalled()
    })
  })
})
