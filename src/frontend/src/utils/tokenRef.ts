/**
 * In-memory token reference shared between auth store and API interceptor.
 * This module has NO imports to avoid circular dependencies.
 */

let _token: string | null = null
let _refreshToken: string | null = null
let _sessionGeneration = 0
let _tokenRefreshListener: ((accessToken: string, refreshToken: string | null) => void) | null = null

export function getToken(): string | null {
  return _token
}

export function getRefreshToken(): string | null {
  return _refreshToken
}

export function getSessionGeneration(): number {
  return _sessionGeneration
}

export function setRefreshToken(refreshToken: string | null): void {
  _refreshToken = refreshToken
}

export function setTokenRefreshListener(
  listener: ((accessToken: string, refreshToken: string | null) => void) | null,
): void {
  _tokenRefreshListener = listener
}

export function setToken(token: string | null): void {
  if (_token !== token) {
    _sessionGeneration += 1
  }
  _token = token
  if (!token) {
    _refreshToken = null
  }
}

/** Start a new login session even when the access token string is unchanged. */
export function beginSession(token: string, refreshToken: string | null = null): number {
  _sessionGeneration += 1
  _token = token
  _refreshToken = refreshToken
  return _sessionGeneration
}

/** Update tokens in-place for the matching session generation after refresh. */
export function applyRefreshedTokens(
  expectedGeneration: number,
  accessToken: string,
  refreshToken?: string | null,
): boolean {
  if (_sessionGeneration !== expectedGeneration) {
    return false
  }
  _token = accessToken
  if (refreshToken !== undefined) {
    _refreshToken = refreshToken
  }
  _tokenRefreshListener?.(accessToken, _refreshToken)
  return true
}

/** Invalidate a session only when the failing request still belongs to it. */
export function expireSession(expectedGeneration: number): boolean {
  if (_sessionGeneration !== expectedGeneration) {
    return false
  }

  _sessionGeneration += 1
  _token = null
  _refreshToken = null
  return true
}
