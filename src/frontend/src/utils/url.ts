/**
 * Safely opens external HTTP(S) URLs in a new tab while blocking dangerous schemes.
 */
export function openSafeExternalUrl(rawUrl: unknown): boolean {
  const articleUrl = String(rawUrl ?? '').trim()
  if (!articleUrl) return false
  try {
    const origin = typeof window !== 'undefined' ? window.location.origin : 'https://localhost'
    const parsed = new URL(articleUrl, origin)
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return false
    window.open(parsed.href, '_blank', 'noopener,noreferrer')
    return true
  } catch {
    return false
  }
}

/**
 * Validate a local artifact path and build a safe file:// URI.
 * Rejects control characters and non-local URI schemes (e.g. javascript:, data:).
 */
function hasControlChar(value: string): boolean {
  for (let i = 0; i < value.length; i += 1) {
    const code = value.charCodeAt(i)
    if (code < 0x20 || code === 0x7f) return true
  }
  return false
}

export function buildSafeFileUrl(rawPath: unknown): string | null {
  const text = String(rawPath ?? '').trim()
  if (!text || hasControlChar(text)) return null
  if (/^[a-z][a-z0-9+.-]*:/i.test(text) && !/^[a-zA-Z]:[\\/]/.test(text)) {
    return null
  }
  const normalized = text.replace(/\\/g, '/')
  return `file://${encodeURI(normalized)}`
}
