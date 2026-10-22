#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared is not installed; install it from the official Cloudflare distribution first." >&2
  exit 1
fi

# Refuse to publish the local listener unless the configured bearer token exists.
"$ROOT/.venv/bin/python" - <<'PY'
import gateway
import os
if not gateway.GATEWAY_TOKEN_ENV or not os.environ.get(gateway.GATEWAY_TOKEN_ENV):
    raise SystemExit("Public tunnel refused: configure server.gateway_token_env and its non-empty .env value first.")
PY

curl --noproxy '*' --fail --silent http://127.0.0.1:18881/health >/dev/null
exec cloudflared tunnel --url http://127.0.0.1:18881
