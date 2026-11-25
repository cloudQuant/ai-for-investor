import api from './index'
import type { UserInfo, LoginRequest, RegisterRequest, Token } from '@/types'

export const authApi = {
  async login(data: LoginRequest): Promise<Token> {
    return api.post<Token, LoginRequest>('/auth/login', data)
  },

  async register(data: RegisterRequest): Promise<UserInfo> {
    return api.post<UserInfo, RegisterRequest>('/auth/register', data)
  },

  async getMe(): Promise<UserInfo> {
    return api.get<UserInfo>('/auth/me', { suppressErrorToast: true })
  },

  async refresh(refreshToken: string): Promise<Token> {
    return api.post<Token, { refresh_token: string }>(
      '/auth/refresh',
      { refresh_token: refreshToken },
      { skipAuthRefresh: true, skipRetry: true, suppressErrorToast: true, suppressErrorMessage: true },
    )
  },
}
