#!/usr/bin/env bash
# Build the DeployGuard dashboard SPA into frontend/dist
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/frontend"

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the dashboard UI" >&2
  exit 1
fi

if [ ! -d node_modules ]; then
  npm ci 2>/dev/null || npm install
fi

export HOME="$ROOT"
export NPM_CONFIG_CACHE="$ROOT/.npm-cache"
mkdir -p "$NPM_CONFIG_CACHE"

npm run build
echo "Dashboard built at frontend/dist"
