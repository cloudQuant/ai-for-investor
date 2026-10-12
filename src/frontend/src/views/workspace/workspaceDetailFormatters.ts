export function parseWorkspaceTime(value: string | number | null | undefined): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value) {
    const timestamp = new Date(value).getTime()
    return Number.isNaN(timestamp) ? null : timestamp
  }
  return null
}

export function formatWorkspaceTime(value: string | number | null | undefined) {
  const timestamp = parseWorkspaceTime(value)
  return timestamp ? new Date(timestamp).toLocaleString() : ''
}

export function formatSignedNumber(value: number | null) {
  if (value === null) {
    return '-'
  }
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(2)}`
}
