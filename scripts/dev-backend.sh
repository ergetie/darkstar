#!/bin/bash
# scripts/dev-backend.sh
# Development runner for Backend (FastAPI + Uvicorn)



# Free port 5000 if already in use (prevents Address already in use)
fuser -k 5000/tcp > /dev/null 2>&1 || true

# Check for uv (High Performance)
if command -v uv >/dev/null 2>&1; then
    echo "⚡ Starting Backend with uv..."
    export PORT=${PORT:-5000}

    # Run config migration
    echo "Running config migrations..."
    uv run python -m backend.config_migration

    # Run database migrations (Alembic)
    echo "Running database migrations..."
    uv run alembic upgrade head

    # uv run automatically handles venv and environment
    uv run uvicorn backend.main:app --host 0.0.0.0 --port $PORT --reload --reload-dir backend --reload-dir planner --reload-dir executor --log-level info
else
    # Legacy / Standard Python Fallback
    echo "🐢 Starting Backend with standard python..."

    # Activate venv if it exists
    if [ -d "venv" ]; then
        source venv/bin/activate
    fi

    # Set PYTHONPATH
    export PYTHONPATH=.

    # Run with hot reload
    export PORT=${PORT:-5000}

    # Run config migration
    echo "Running config migrations..."
    python -m backend.config_migration

    # Run database migrations (Alembic)
    echo "Running database migrations..."
    alembic upgrade head

    uvicorn backend.main:app --host 0.0.0.0 --port $PORT --reload --reload-dir backend --reload-dir planner --reload-dir executor --log-level info
fi
