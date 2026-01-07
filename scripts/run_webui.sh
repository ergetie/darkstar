#!/usr/bin/env bash
# --- run_webui.sh ---
# Launch the Darkstar Web UI easily.

# Navigate to project directory
cd "/home/s/sync/documents/projects/darkstar/" || exit 1

# Activate the virtual environment
source venv/bin/activate

# Optional: print a nice header
echo "🚀 Starting Darkstar Web UI..."
echo "   Press Ctrl+C to stop."

# Start FastAPI app (React frontend + backend APIs)
export PORT=${PORT:-5000}
uvicorn backend.main:app --host 0.0.0.0 --port $PORT --reload --log-level info
