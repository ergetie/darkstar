#!/usr/bin/env bash
# Darkstar startup - auto-updates dependencies then starts
set -euo pipefail

cd /opt/darkstar
export HOME=/root

echo "🔄 Updating dependencies..."
npm install
npm --prefix frontend install

echo "🚀 Starting Darkstar..."
exec /opt/darkstar/node_modules/.bin/concurrently -k -n FRONTEND,BACKEND \
  "npm --prefix frontend run dev" \
  "bash scripts/dev-backend.sh"
