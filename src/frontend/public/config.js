/*
 * Placeholder runtime configuration for local dev (`vite dev`) and statically
 * hosted builds. In Docker this file is overwritten at container start by
 * src/frontend/scripts/docker-entrypoint.sh from the FRONTEND_* environment — the built
 * assets never embed these values.
 */
window.__APP_CONFIG__ = {
  appName: 'GraphForge',
  apiBaseUrl: 'http://localhost:5087',
  maxUploadBytes: 104857600,
};
