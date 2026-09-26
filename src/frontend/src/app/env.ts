/**
 * Reads and validates the client configuration once, at module load.
 *
 * Precedence per field: the container-generated `/config.js`
 * (`window.__APP_CONFIG__`, rendered at container start from the `FRONTEND_*`
 * environment) wins; the Vite build-time `VITE_*` variables are the fallback
 * for `vite dev` and for statically-hosted builds served without the
 * entrypoint.
 *
 * Every other module imports the resolved values rather than touching
 * `import.meta.env` or `window` directly, so a missing or malformed value
 * surfaces here instead of as a confusing failure deep inside a request.
 */
function readRuntimeConfig(): AppRuntimeConfig | undefined {
  if (typeof window === 'undefined') return undefined
  const config = window.__APP_CONFIG__
  return config && typeof config === 'object' ? config : undefined
}

function readString(raw: unknown, fallback: string): string {
  return typeof raw === 'string' && raw.trim() ? raw.trim() : fallback
}

function readNumber(raw: unknown, fallback: number): number {
  const parsed = readPositiveNumber(raw)
  return parsed ?? fallback
}

/** Returns `undefined` (rather than a default) so callers can chain fallbacks. */
function readPositiveNumber(raw: unknown): number | undefined {
  if (typeof raw === 'number') {
    return Number.isFinite(raw) && raw > 0 ? raw : undefined
  }
  if (typeof raw !== 'string' || !raw) return undefined
  const parsed = Number(raw)
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined
}

const runtime = readRuntimeConfig()

const rawBaseUrl = readString(runtime?.apiBaseUrl, import.meta.env.VITE_API_BASE_URL?.trim() || '/')

export const env = {
  appName: readString(runtime?.appName, import.meta.env.VITE_APP_NAME?.trim() || 'GraphForge'),
  /** Always ends with a slash so `new URL(path, apiBaseUrl)` keeps the whole path. */
  apiBaseUrl: rawBaseUrl.endsWith('/') ? rawBaseUrl : `${rawBaseUrl}/`,
  maxUploadBytes:
    readPositiveNumber(runtime?.maxUploadBytes) ??
    readNumber(import.meta.env.VITE_MAX_UPLOAD_BYTES, 100 * 1024 * 1024),
} as const
