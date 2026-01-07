#!/bin/bash
# scripts/dev-backend.sh
# Development runner for Backend (FastAPI + Uvicorn)



# Free port 5000 if already in use (prevents Address already in use)
fuser -k 5000/tcp > /dev/null 2>&1 || true

# Activate venv if it exists
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Set PYTHONPATH
export PYTHONPATH=.

# Run with hot reload
export PORT=${PORT:-5000}
uvicorn backend.main:app --host 0.0.0.0 --port $PORT --reload --log-level info
