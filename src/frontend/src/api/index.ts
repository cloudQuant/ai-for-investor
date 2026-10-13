import axios from 'axios'
import type { AxiosInstance, AxiosError, AxiosRequestConfig, InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus/es/components/message/index.mjs'

import {
  clearAccessToken,
  dispatchAuthExpired,
  getAccessToken,
} from '@/utils/session'
import { expireSession, getSessionGeneration, getToken } from '@/utils/tokenRef'
import i18n from '@/i18n'

/** Per-request controls for localized or explicitly handled API fallbacks. */
export interface ApiRequestConfig<D = unknown, P = unknown> extends AxiosRequestConfig<D, P> {
  /** The caller projects a closed, localized error code and owns user notification. */
  suppressErrorToast?: boolean
  suppressErrorMessage?: boolean
  skipRetry?: boolean
}

function tt(key: string): string {
  return i18n.global.t(key)
}

type ErrorField = {
  field?: string
  message?: string
  type?: string
}

type ApiErrorPayload = {
  detail?: unknown
  message?: unknown
  error?: unknown
  request_id?: unknown
  path?: unknown
  details?: {
    fields?: ErrorField[]
    [k: string]: unknown
  }
  [k: string]: unknown
}

interface ApiClient extends Omit<
  AxiosInstance,
  'request' | 'get' | 'delete' | 'post' | 'put' | 'patch'
> {
  request<T = unknown, D = unknown, P = unknown>(config: ApiRequestConfig<D, P>): Promise<T>
  get<T = unknown, D = unknown, P = unknown>(
    url: string,
    config?: ApiRequestConfig<D, P>,
  ): Promise<T>
  delete<T = unknown, D = unknown, P = unknown>(
    url: string,
    config?: ApiRequestConfig<D, P>,
  ): Promise<T>
  post<T = unknown, D = unknown, P = unknown>(
    url: string,
    data?: D,
    config?: ApiRequestConfig<D, P>,
  ): Promise<T>
  put<T = unknown, D = unknown, P = unknown>(
    url: string,
    data?: D,
    config?: ApiRequestConfig<D, P>,
  ): Promise<T>
  patch<T = unknown, D = unknown, P = unknown>(
    url: string,
    data?: D,
    config?: ApiRequestConfig<D, P>,
  ): Promise<T>
}

type SessionRequestConfig = InternalAxiosRequestConfig & {
  __sessionGeneration?: number
  __sessionToken?: string | null
  __retryCount?: number
  __isRetrying?: boolean
  suppressErrorToast?: boolean
  suppressErrorMessage?: boolean
  skipRetry?: boolean
}

class SupersededSessionRequestError extends Error {
  constructor() {
    super('Request belongs to a superseded session')
    this.name = 'SupersededSessionRequestError'
  }
}

export function isSupersededSessionRequestError(error: unknown): boolean {
  return error instanceof SupersededSessionRequestError
}

function isStaleSessionRequest(config: SessionRequestConfig | undefined): boolean {
  return config?.__sessionGeneration !== undefined
    && config.__sessionGeneration !== getSessionGeneration()
}

// --- Retry Interceptor Configuration ---

export interface RetryConfig {
  maxRetries: number
  initialDelay: number
  backoffFactor: number
  jitterRange: number
  retryableStatuses: number[]
  idempotentMethods: string[]
}

export const RETRY_CONFIG: RetryConfig = {
  maxRetries: 3,
  initialDelay: 1000,
  backoffFactor: 2,
  jitterRange: 0.1,
  retryableStatuses: [408, 429, 500, 502, 503, 504],
  idempotentMethods: ['GET', 'HEAD', 'OPTIONS', 'PUT', 'DELETE'],
}

/** Check if the error is retryable based on status code or network error */
export function isRetryableError(error: AxiosError): boolean {
  if (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED') {
    return true
  }
  const status = error.response?.status
  if (status && RETRY_CONFIG.retryableStatuses.includes(status)) {
    return true
  }
  return false
}

/** Check if the request method is idempotent (or POST with Idempotency-Key) */
export function isIdempotentRequest(config: InternalAxiosRequestConfig): boolean {
  const method = (config.method || '').toUpperCase()
  if (RETRY_CONFIG.idempotentMethods.includes(method)) {
    return true
  }
  // POST is retryable only if the request has an Idempotency-Key header
  if (method === 'POST') {
    const headers = config.headers
    if (headers && headers['Idempotency-Key']) {
      return true
    }
  }
  return false
}

/** Calculate delay with exponential backoff and ±10% jitter */
export function calculateRetryDelay(retryCount: number): number {
  const baseDelay = RETRY_CONFIG.initialDelay * Math.pow(RETRY_CONFIG.backoffFactor, retryCount)
  const jitter = baseDelay * RETRY_CONFIG.jitterRange * (2 * Math.random() - 1)
  return baseDelay + jitter
}

/** Sleep utility for retry delays */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function stringifyDetail(detail: unknown): string | undefined {
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI default 422 shape: [{loc, msg, type}, ...]
    const first = detail[0] as { msg?: unknown }
    if (typeof first?.msg === 'string') return first.msg
    return undefined
  }
  if (detail && typeof detail === 'object') {
    const msg = (detail as { message?: unknown }).message
    if (typeof msg === 'string') return msg
  }
  return undefined
}

function extractApiErrorMessage(payload: unknown): string {
  const data = (payload ?? {}) as ApiErrorPayload

  const msg =
    (typeof data.message === 'string' ? data.message : undefined) ??
    stringifyDetail(data.detail) ??
    (typeof data.detail === 'string' ? data.detail : undefined)

  if (msg) {
    const requestId = typeof data.request_id === 'string' ? data.request_id : undefined
    return requestId ? `${msg} (request_id: ${requestId})` : msg
  }

  const fields = data.details?.fields
  if (Array.isArray(fields) && fields.length > 0) {
    const first = fields[0]
    const field = typeof first.field === 'string' ? first.field : undefined
    const fieldMsg = typeof first.message === 'string' ? first.message : tt('apiClient.errFieldFallback')
    return field ? `${field}: ${fieldMsg}` : fieldMsg
  }

  return tt('apiClient.errGenericFailure')
}

/** Extract user-friendly error message from caught unknown values in catch blocks. */
export function getErrorMessage(e: unknown, fallback: string): string {
  if (e && typeof e === 'object' && 'response' in e) {
    const ax = e as { response?: { data?: unknown } }
    if (ax.response?.data) {
      const msg = extractApiErrorMessage(ax.response.data)
      if (msg !== tt('apiClient.errGenericFailure')) return msg
    }
  }
  if (e instanceof Error) return e.message || fallback
  return fallback
}

const env = (import.meta as ImportMeta & { env: Record<string, string | undefined> }).env

// 创建axios实例
const api = axios.create({
  baseURL: env.VITE_API_BASE_URL || '/api/v1',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
}) as ApiClient

// Request interceptor captures one session token and generation for its full lifetime.
api.interceptors.request.use(
  (rawConfig) => {
    const config = rawConfig as SessionRequestConfig
    if (config.__sessionGeneration === undefined) {
      const generation = getSessionGeneration()
      const token = getToken() || getAccessToken()
      if (generation !== getSessionGeneration()) {
        throw new SupersededSessionRequestError()
      }
      config.__sessionGeneration = generation
      config.__sessionToken = token
    } else if (config.__sessionGeneration !== getSessionGeneration()) {
      throw new SupersededSessionRequestError()
    }

    // Retries keep the token snapshot captured on the original request.
    const token = config.__sessionToken
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
api.interceptors.response.use(
  (response) => {
    const config = response.config as SessionRequestConfig | undefined
    if (isStaleSessionRequest(config)) {
      return Promise.reject(new SupersededSessionRequestError())
    }
    return response.data
  },
  async (error: AxiosError) => {
    const config = error.config as SessionRequestConfig | undefined

    if (isSupersededSessionRequestError(error) || isStaleSessionRequest(config)) {
      return Promise.reject(isSupersededSessionRequestError(error)
        ? error
        : new SupersededSessionRequestError())
    }

    // --- Retry Logic ---
    if (config && !config.skipRetry) {
      const retryCount = config.__retryCount || 0

      if (
        retryCount < RETRY_CONFIG.maxRetries &&
        isRetryableError(error) &&
        isIdempotentRequest(config)
      ) {
        config.__retryCount = retryCount + 1
        config.__isRetrying = true

        const delay = calculateRetryDelay(retryCount)
        await sleep(delay)

        return api.request(config)
      }
    }

    // --- Error Handling (only fires once after all retries exhausted) ---
    // Skip ElMessage if this was a retrying request that just completed its final retry
    const isRetrying = config?.__isRetrying && (config.__retryCount || 0) < RETRY_CONFIG.maxRetries
    if (isRetrying) {
      return Promise.reject(error)
    }

    if (config?.suppressErrorMessage) {
      return Promise.reject(error)
    }

    const status = error.response?.status
    const data = error.response?.data
    const msg = extractApiErrorMessage(data)
    const genericMsg = tt('apiClient.errGenericFailure')
    const isGenericMsg = msg === genericMsg
    const suppressErrorToast = config?.suppressErrorToast === true

    if (status === 401) {
      if (
        config?.__sessionGeneration !== undefined
        && config.__sessionToken
        && expireSession(config.__sessionGeneration)
      ) {
        clearAccessToken()
        dispatchAuthExpired()
      }
      if (!suppressErrorToast) {
        ElMessage.error(isGenericMsg ? tt('apiClient.errAuthExpired') : msg)
      }
    } else if (suppressErrorToast) {
      // Closed-projection callers render an allowlisted local message themselves.
    } else if (status === 403) {
      ElMessage.error(isGenericMsg ? tt('apiClient.errForbidden') : msg)
    } else if (status === 404) {
      ElMessage.error(isGenericMsg ? tt('apiClient.errNotFound') : msg)
    } else if (status === 500) {
      ElMessage.error(isGenericMsg ? tt('apiClient.errServerError') : msg)
    } else {
      ElMessage.error(msg)
    }

    return Promise.reject(error)
  }
)

export default api
