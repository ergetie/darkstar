#!/bin/bash
set -e

# ==============================================================================
# Darkstar Production Entrypoint
# Manages: Flask API, Scheduler, Recorder
# ==============================================================================

export PYTHONPATH="${PYTHONPATH:-.}:/app"
export PYTHONUNBUFFERED=1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# PID tracking
FLASK_PID=""
SCHEDULER_PID=""
RECORDER_PID=""

cleanup() {
    log "Received shutdown signal, stopping services..."
    
    # Stop Flask first (graceful)
    if [ -n "$FLASK_PID" ] && kill -0 "$FLASK_PID" 2>/dev/null; then
        log "Stopping Flask API..."
        kill -TERM "$FLASK_PID" 2>/dev/null || true
    fi
    
    # Stop scheduler
    if [ -n "$SCHEDULER_PID" ] && kill -0 "$SCHEDULER_PID" 2>/dev/null; then
        log "Stopping Scheduler..."
        kill -TERM "$SCHEDULER_PID" 2>/dev/null || true
    fi
    
    # Stop recorder
    if [ -n "$RECORDER_PID" ] && kill -0 "$RECORDER_PID" 2>/dev/null; then
        log "Stopping Recorder..."
        kill -TERM "$RECORDER_PID" 2>/dev/null || true
    fi
    
    # Wait for all to exit (max 10 seconds)
    wait 2>/dev/null || true
    log "Shutdown complete."
    exit 0
}

trap cleanup SIGTERM SIGINT SIGHUP

log "=========================================="
log "  Darkstar Energy Manager v2.0.0"
log "=========================================="

# Check for required config files
# NOTE: Docker creates DIRECTORIES when bind mount sources don't exist!
# If you see these errors, delete the directory and create the file.
if [ -d "/app/config.yaml" ]; then
    log "ERROR: /app/config.yaml is a DIRECTORY, not a file!"
    log "This happens when Docker starts without the source file existing."
    log "FIX: On host, run: rm -rf ./config.yaml && cp config.default.yaml config.yaml"
    exit 1
fi

if [ ! -f "/app/config.yaml" ]; then
    log "ERROR: /app/config.yaml not found. Mount your config file."
    log "HINT: Copy config.default.yaml to config.yaml and customize it."
    exit 1
fi

if [ -d "/app/secrets.yaml" ]; then
    log "ERROR: /app/secrets.yaml is a DIRECTORY, not a file!"
    log "FIX: On host, run: rm -rf ./secrets.yaml && cp secrets.example.yaml secrets.yaml"
    exit 1
fi

if [ ! -f "/app/secrets.yaml" ]; then
    log "ERROR: /app/secrets.yaml not found. Mount your secrets file."
    exit 1
fi

log "Config files found."

# Initialize schedule.json if missing or corrupted (e.g., was a directory)
if [ ! -f "/app/schedule.json" ] || [ -d "/app/schedule.json" ]; then
    rm -rf /app/schedule.json 2>/dev/null || true
    echo '{"schedule": [], "meta": {"initialized": true}}' > /app/schedule.json
    log "Created empty schedule.json (planner will populate it)"
fi

# Start Scheduler (background)
log "Starting Scheduler (hourly planner runs)..."
python -m backend.scheduler 2>&1 | while read line; do echo "[SCHEDULER] $line"; done &
SCHEDULER_PID=$!
log "Scheduler started (PID: $SCHEDULER_PID)"

# Start Recorder (background)
log "Starting Recorder (15-min observation logging)..."
python -m backend.recorder 2>&1 | while read line; do echo "[RECORDER] $line"; done &
RECORDER_PID=$!
log "Recorder started (PID: $RECORDER_PID)"

# Brief pause to let background services initialize
sleep 2

# Start Darkstar API with FastAPI/Uvicorn (Rev ARC1)
log "Starting Darkstar ASGI Server (Uvicorn) on port 5000..."
uvicorn backend.main:app --host 0.0.0.0 --port 5000 --log-level info &
FLASK_PID=$!
log "Darkstar started (PID: $FLASK_PID)"

log "=========================================="
log "  All services running. Ready."
log "=========================================="

# Monitor processes - exit if any critical process dies
while true; do
    # Check Flask (critical)
    if ! kill -0 "$FLASK_PID" 2>/dev/null; then
        log "ERROR: Flask API exited unexpectedly!"
        cleanup
        exit 1
    fi
    
    # Check Scheduler (important but not critical)
    if ! kill -0 "$SCHEDULER_PID" 2>/dev/null; then
        log "WARNING: Scheduler exited. Restarting..."
        python -m backend.scheduler 2>&1 | while read line; do echo "[SCHEDULER] $line"; done &
        SCHEDULER_PID=$!
        log "Scheduler restarted (PID: $SCHEDULER_PID)"
    fi
    
    # Check Recorder (important but not critical)
    if ! kill -0 "$RECORDER_PID" 2>/dev/null; then
        log "WARNING: Recorder exited. Restarting..."
        python -m backend.recorder 2>&1 | while read line; do echo "[RECORDER] $line"; done &
        RECORDER_PID=$!
        log "Recorder restarted (PID: $RECORDER_PID)"
    fi
    
    sleep 30
done
