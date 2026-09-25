/**
 * Reads and validates the client environment once, at module load.
 *
 * Every other module imports the resolved values rather than touching
 * `import.meta.env`, so a missing or malformed variable surfaces here instead
 * of as a confusing failure deep inside a request.
 */
function readNumber(raw: string | undefined, fallback: number): number {
  if (!raw) return fallback
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback
}

const rawBaseUrl = import.meta.env.VITE_API_BASE_URL?.trim() || '/'

export const env = {
  appName: import.meta.env.VITE_APP_NAME?.trim() || 'GraphForge',
  /** Always ends with a slash so `new URL(path, apiBaseUrl)` keeps the whole path. */
  apiBaseUrl: rawBaseUrl.endsWith('/') ? rawBaseUrl : `${rawBaseUrl}/`,
  maxUploadBytes: readNumber(import.meta.env.VITE_MAX_UPLOAD_BYTES, 100 * 1024 * 1024),
} as const
