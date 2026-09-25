const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

/** Human-readable file size, e.g. `1.4 MB`. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—'
  if (bytes === 0) return '0 B'

  const exponent = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    BYTE_UNITS.length - 1,
  )
  const value = bytes / 1024 ** exponent
  const digits = exponent === 0 || value >= 100 ? 0 : 1
  return `${value.toFixed(digits)} ${BYTE_UNITS[exponent]}`
}

const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
})

const dateFormat = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' })

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : dateTimeFormat.format(date)
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : dateFormat.format(date)
}

const relativeFormat = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })

const RELATIVE_STEPS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 365 * 24 * 60 * 60 * 1000],
  ['month', 30 * 24 * 60 * 60 * 1000],
  ['day', 24 * 60 * 60 * 1000],
  ['hour', 60 * 60 * 1000],
  ['minute', 60 * 1000],
]

export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return '—'

  const diff = date.getTime() - Date.now()
  for (const [unit, step] of RELATIVE_STEPS) {
    if (Math.abs(diff) >= step) {
      return relativeFormat.format(Math.round(diff / step), unit)
    }
  }
  return relativeFormat.format(Math.round(diff / 1000), 'second')
}

/** Title-cases a snake_case wire value for display, e.g. `api_key` -> `Api key`. */
export function humanizeEnum(value: string): string {
  const spaced = value.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}
