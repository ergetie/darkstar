#!/usr/bin/env bash
set -e

source venv/bin/activate

echo "🔍 Running Ruff linter..."
ruff check .

echo "🎨 Running Ruff formatter..."
ruff format --check .

echo "📝 Running Pyright type checker..."
pyright .

echo "✅ All checks passed!"
