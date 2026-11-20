#!/bin/bash
set -e

# ==============================================================================
# Darkstar Production Entrypoint
# Manages: FastAPI Server (with in-process scheduler, recorder, executor)
# ==============================================================================

APP_DIR="${APP_DIR:-/app}"
export PYTHONPATH="${PYTHONPATH:-.}:$APP_DIR"
export PYTHONUNBUFFERED=1

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# PID tracking
API_PID=""

cleanup() {
    log "Received shutdown signal, stopping services..."

    # Stop FastAPI server (graceful shutdown handles scheduler, recorder, executor)
    if [ -n "$API_PID" ] && kill -0 "$API_PID" 2>/dev/null; then
        log "Stopping FastAPI Server..."
        kill -TERM "$API_PID" 2>/dev/null || true
    fi

    # Wait for all to exit (max 10 seconds)
    wait 2>/dev/null || true
    log "Shutdown complete."
    exit 0
}

trap cleanup SIGTERM SIGINT SIGHUP

APP_VERSION=$(cat "$APP_DIR/VERSION" 2>/dev/null || echo "unknown")
log "=========================================="
log "  Darkstar Energy Manager ${APP_VERSION}"
log "=========================================="

# Check for required config files
# NOTE: Docker creates DIRECTORIES when bind mount sources don't exist!
# If you see these errors, delete the directory and create the file.
if [ -d "$APP_DIR/config.yaml" ]; then
    log "ERROR: $APP_DIR/config.yaml is a DIRECTORY, not a file!"
    log "This happens when Docker starts without the source file existing."
    log "FIX: On host, run: rm -rf ./config.yaml && cp config.default.yaml config.yaml"
    exit 1
fi

if [ ! -f "$APP_DIR/config.yaml" ]; then
    log "ERROR: $APP_DIR/config.yaml not found. Mount your config file."
    log "HINT: Copy config.default.yaml to config.yaml and customize it."
    exit 1
fi

if [ -d "$APP_DIR/secrets.yaml" ]; then
    log "ERROR: $APP_DIR/secrets.yaml is a DIRECTORY, not a file!"
    log "FIX: On host, run: rm -rf ./secrets.yaml && cp secrets.example.yaml secrets.yaml"
    exit 1
fi

if [ ! -f "$APP_DIR/secrets.yaml" ]; then
    log "ERROR: $APP_DIR/secrets.yaml not found. Mount your secrets file."
    exit 1
fi

log "Config files found."

# 1. Config Migration
log "Running config migrations..."
if ! python3 -m backend.config_migration; then
    log "ERROR: Config migration failed!"
    exit 1
fi
log "Config migration complete."

# 2. Database Migration
# backend.db_safety backs the database up before a migration (or the one-time
# storage-format switch), restores that backup if the migration fails, and
# compacts the file afterwards. The database path is resolved the same way the
# application does it (DB_PATH, learning.sqlite_path, data/planner_learning.db).
log "Checking database state..."
if [ -f "$APP_DIR/alembic.ini" ]; then
    # stdout is the backup path (empty when nothing was backed up); logs go to stderr.
    if ! DB_BACKUP=$(python3 -m backend.db_safety pre-migrate); then
        log "ERROR: Database backup failed, migration aborted. Database left untouched."
        exit 1
    fi

    log "Running database migrations (Alembic)..."
    if ! alembic upgrade head; then
        log "ERROR: Database migration failed!"
        if [ -n "$DB_BACKUP" ]; then
            if python3 -m backend.db_safety restore "$DB_BACKUP"; then
                log "Database restored from backup $DB_BACKUP"
            else
                log "ERROR: Automatic restore failed! Restore manually from $DB_BACKUP"
                log "RECOVERY: python3 -m backend.db_safety restore $DB_BACKUP"
            fi
        fi
        exit 1
    fi
    log "Database migration complete."

    # One-time prune and shrink. Never blocks start-up.
    python3 -m backend.db_safety compact "$DB_BACKUP" ||
        log "WARNING: Database compaction failed, continuing."
else
    log "WARNING: $APP_DIR/alembic.ini not found, skipping DB migrations."
    log "HINT: Ensure alembic.ini is present in the container root."
fi

# Initialize schedule.json if missing or corrupted (e.g., was a directory)
if [ ! -f "$APP_DIR/schedule.json" ] || [ -d "$APP_DIR/schedule.json" ]; then
    rm -rf "$APP_DIR/schedule.json" 2>/dev/null || true
    echo '{"schedule": [], "meta": {"initialized": true}}' > "$APP_DIR/schedule.json"
    log "Created empty schedule.json (planner will populate it)"
fi

# Start Darkstar FastAPI Server (includes in-process scheduler + executor)
log "Starting Darkstar ASGI Server (Uvicorn) on port 5000..."
log "  - Scheduler: Auto-starts if config.automation.enable_scheduler=true"
log "  - Recorder: Runs in-process"
log "  - Executor: Auto-starts if config.executor.enabled=true"
uvicorn backend.main:app --host 0.0.0.0 --port 5000 --log-level info &
API_PID=$!
log "Darkstar started (PID: $API_PID)"

log "=========================================="
log "  All services running. Ready."
log "=========================================="

# Monitor processes - exit if any critical process dies
while true; do
    # Check FastAPI Server (critical - includes scheduler + executor)
    if ! kill -0 "$API_PID" 2>/dev/null; then
        log "ERROR: FastAPI Server exited unexpectedly!"
        cleanup
        exit 1
    fi

    sleep 30
done
