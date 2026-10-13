export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

export function containsRedactedSecret(value: unknown): boolean {
  if (typeof value === 'string') return value.trim() === '***'
  if (Array.isArray(value)) return value.some(item => containsRedactedSecret(item))
  if (!isRecord(value)) return false
  return Object.values(value).some(item => containsRedactedSecret(item))
}

export function optionalNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const number = Number(value)
    return Number.isFinite(number) ? number : null
  }
  return null
}

export function optionalBoolean(value: unknown, fallback = false) {
  if (typeof value === 'boolean') return value
  return fallback
}

export function parseResearchDate(value: string) {
  const trimmed = value.trim()
  if (!trimmed) return null
  const date = new Date(`${trimmed}T00:00:00Z`)
  return Number.isNaN(date.getTime()) ? null : date
}

export function stringFromUnknown(value: unknown, fallback = '') {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || fallback
}

export function routeQueryText(value: unknown) {
  if (Array.isArray(value)) return stringFromUnknown(value[0])
  return stringFromUnknown(value)
}

export function nullableString(value: unknown) {
  const text = typeof value === 'string' ? value.trim() : ''
  return text || null
}

export function stringArrayFromUnknown(value: unknown) {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    : []
}

export function uniqueTextItems(items: unknown[]) {
  return [...new Set(
    items
      .map(item => stringFromUnknown(item))
      .filter(Boolean)
  )]
}

export function arrayFromUnknown<T>(value: unknown): T[] {
  return Array.isArray(value) ? value.filter(isRecord) as T[] : []
}
