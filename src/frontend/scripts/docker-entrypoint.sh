#!/bin/sh
# Renders the SPA runtime config (/usr/share/nginx/html/config.js) from the
# FRONTEND_* environment, then hands off to the container command (nginx).
# Changing these needs only a container restart, never an image rebuild:
#   FRONTEND_APP_NAME, FRONTEND_API_BASE_URL, FRONTEND_MAX_UPLOAD_BYTES.
set -eu

CONFIG_PATH="/usr/share/nginx/html/config.js"

APP_NAME="${FRONTEND_APP_NAME:-GraphForge}"
API_BASE_URL="${FRONTEND_API_BASE_URL:-http://localhost:5087}"
MAX_UPLOAD_BYTES="${FRONTEND_MAX_UPLOAD_BYTES:-104857600}"

# Numeric guard: fall back to the default when unset or not a positive integer.
case "$MAX_UPLOAD_BYTES" in
  ''|*[!0-9]*|0) MAX_UPLOAD_BYTES="104857600" ;;
esac

# Escape backslashes and single quotes for single-quoted JS string literals.
escape_js() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e "s/'/\\\\'/g"
}

APP_NAME_ESCAPED="$(escape_js "$APP_NAME")"
API_BASE_URL_ESCAPED="$(escape_js "$API_BASE_URL")"

cat > "$CONFIG_PATH" <<EOF
/* Generated at container start from the FRONTEND_* environment. Do not edit. */
window.__APP_CONFIG__ = {
  appName: '${APP_NAME_ESCAPED}',
  apiBaseUrl: '${API_BASE_URL_ESCAPED}',
  maxUploadBytes: ${MAX_UPLOAD_BYTES},
};
EOF

exec "$@"
