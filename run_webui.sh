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

# Start Flask app (React frontend + backend APIs)
export FLASK_APP=backend.webapp
export FLASK_ENV=development

# Free port 5000 if already in use
if lsof -i:5000 >/dev/null 2>&1; then
  echo "⚠️  Port 5000 already in use — liberation in progress..."
  PID=$(lsof -ti:5000)
  kill "$PID" 2>/dev/null
  sleep 1
fi

flask run --reload --host 0.0.0.0 --port 5000
