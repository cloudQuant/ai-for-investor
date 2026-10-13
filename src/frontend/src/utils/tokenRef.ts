/**
 * In-memory token reference shared between auth store and API interceptor.
 * This module has NO imports to avoid circular dependencies.
 */

let _token: string | null = null
let _sessionGeneration = 0

export function getToken(): string | null {
  return _token
}

export function getSessionGeneration(): number {
  return _sessionGeneration
}

export function setToken(token: string | null): void {
  if (_token !== token) {
    _sessionGeneration += 1
  }
  _token = token
}

/** Start a new login session even when the access token string is unchanged. */
export function beginSession(token: string): number {
  _sessionGeneration += 1
  _token = token
  return _sessionGeneration
}

/** Invalidate a session only when the failing request still belongs to it. */
export function expireSession(expectedGeneration: number): boolean {
  if (_sessionGeneration !== expectedGeneration) {
    return false
  }

  _sessionGeneration += 1
  _token = null
  return true
}
