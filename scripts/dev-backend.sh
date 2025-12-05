#!/usr/bin/env bash
set -euo pipefail

export FLASK_APP=backend.webapp
export PYTHONPATH="${PYTHONPATH:-.}:."

# Activate venv if present
if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
  # Auto-install/update requirements on startup
  pip install -q -r requirements.txt
fi

# Start in-app scheduler in the background for dev
python -m backend.scheduler &
SCHED_PID=$!

# Start live observation recorder (15-minute cadence) in the background for dev
python -m backend.recorder &
REC_PID=$!

cleanup() {
  # Try to stop scheduler gracefully
  if kill -0 "$SCHED_PID" 2>/dev/null; then
    kill "$SCHED_PID" 2>/dev/null || true
    wait "$SCHED_PID" 2>/dev/null || true
  fi
  # Try to stop recorder gracefully
  if kill -0 "$REC_PID" 2>/dev/null; then
    kill "$REC_PID" 2>/dev/null || true
    wait "$REC_PID" 2>/dev/null || true
  fi
}

trap cleanup INT TERM

# Run Flask API in the foreground
python -m flask run --host 0.0.0.0 --port 5000

# If Flask exits, clean up scheduler as well
cleanup
