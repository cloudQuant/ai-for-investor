export default defineNuxtPlugin(() => {
  const config = useRuntimeConfig()
  const authStore = useAuthStore()

  const api = async (path: string, options: Record<string, any> = {}) => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...options.headers,
    }

    if (authStore.accessToken) {
      headers['Authorization'] = `Bearer ${authStore.accessToken}`
    }

    const response = await fetch(`${config.public.apiBase}${path}`, {
      ...options,
      headers,
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || data.error?.message || 'Request failed')
    }

    return data
  }

  const apiClient = {
    get: (path: string, params?: Record<string, any>) => {
      const query = params ? '?' + new URLSearchParams(params as any).toString() : ''
      return api(`${path}${query}`)
    },
    post: (path: string, body?: any) => api(path, { method: 'POST', body: JSON.stringify(body) }),
    patch: (path: string, body?: any) => api(path, { method: 'PATCH', body: JSON.stringify(body) }),
    delete: (path: string) => api(path, { method: 'DELETE' }),
  }

  return {
    provide: {
      api: apiClient,
    },
  }
})