#!/usr/bin/env bash
# Darkstar startup script - auto-updates all dependencies
set -euo pipefail

cd "$(dirname "$0")/.."

echo "🔄 Updating dependencies..."

# Backend: Python requirements
if [ -d "venv" ]; then
  source venv/bin/activate
  pip install -q -r requirements.txt
  echo "✅ Python dependencies updated"
fi

# Frontend: npm packages  
if [ -d "frontend" ]; then
  npm --prefix frontend install --silent
  echo "✅ Frontend dependencies updated"
fi

# Root npm (concurrently, etc.)
npm install --silent
echo "✅ Root dependencies updated"

echo "🚀 Starting Darkstar..."
exec npm run dev
