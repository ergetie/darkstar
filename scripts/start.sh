#!/usr/bin/env bash
# Darkstar startup - auto-updates all dependencies then starts
set -euo pipefail

cd "$(dirname "$0")/.."

echo "🔄 Updating dependencies..."

# Frontend npm packages
npm --prefix frontend install --silent 2>/dev/null || npm --prefix frontend install

# Root npm (concurrently)
npm install --silent 2>/dev/null || npm install

echo "🚀 Starting Darkstar..."

# dev-backend.sh handles Python requirements + backend
# concurrently runs frontend + backend together
exec npm run dev
