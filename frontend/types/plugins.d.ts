import { ComputedRef } from 'vue'

interface AuthPlugin {
  isLoggedIn: ComputedRef<boolean>
  user: ComputedRef<any>
  accessToken: ComputedRef<string | null>
}

interface ApiClient {
  get: (path: string, params?: Record<string, any>) => Promise<any>
  post: (path: string, body?: any) => Promise<any>
  patch: (path: string, body?: any) => Promise<any>
  delete: (path: string) => Promise<any>
}

declare module '#app' {
  interface NuxtApp {
    $api: ApiClient
    $auth: AuthPlugin
  }
}

export {}