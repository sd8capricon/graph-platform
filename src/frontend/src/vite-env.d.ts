/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_APP_NAME?: string
  readonly VITE_API_BASE_URL?: string
  readonly VITE_MAX_UPLOAD_BYTES?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

/**
 * Runtime configuration exposed via `public/config.js`. In Docker the
 * container entrypoint renders that file at startup from the `FRONTEND_*`
 * environment; otherwise the committed placeholder applies. Every field is
 * optional: `src/app/env.ts` falls back to the `VITE_*` build-time value
 * (or a hard default) per field.
 */
interface AppRuntimeConfig {
  appName?: unknown
  apiBaseUrl?: unknown
  maxUploadBytes?: unknown
}

interface Window {
  __APP_CONFIG__?: AppRuntimeConfig
}
