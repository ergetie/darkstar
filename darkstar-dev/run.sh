#!/usr/bin/env bash
# Darkstar Energy Manager - Home Assistant Add-on Entrypoint
set -e

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Read options from HA Add-on config
CONFIG_PATH=/data/options.json

TIMEZONE=""
LOG_LEVEL="info"
if [ -f "$CONFIG_PATH" ]; then
    TIMEZONE=$(jq -r '.timezone // empty' "$CONFIG_PATH")
    LOG_LEVEL=$(jq -r '.log_level // "info"' "$CONFIG_PATH")
fi

# Timezone is optional: only export TZ when the user set it
if [ -n "$TIMEZONE" ]; then
    export TZ="$TIMEZONE"
fi
export LOG_LEVEL="$LOG_LEVEL"

# Create config directory
mkdir -p /config/darkstar

# =============================================================================
# AUTO-DETECT HA CONNECTION (SUPERVISOR_TOKEN)
# =============================================================================
# When running as HA Add-on, SUPERVISOR_TOKEN is automatically available
# and we can use http://supervisor/core as the HA API endpoint

if [ -n "$SUPERVISOR_TOKEN" ]; then
    log "HA Add-on detected - auto-configuring connection..."
    # secrets.yaml is merged (token refreshed, user keys preserved) by
    # backend.addon_bootstrap below; it is never overwritten here.
else
    # Standalone mode - copy template if missing
    if [ ! -f /config/darkstar/secrets.yaml ]; then
        cp /app/secrets.example.yaml /config/darkstar/secrets.yaml
        log "Created secrets template at /config/darkstar/secrets.yaml"
        log "Please edit /config/darkstar/secrets.yaml with your HA token!"
    fi
fi

# =============================================================================
# CONFIG.YAML SETUP
# =============================================================================

if [ ! -f /config/darkstar/config.yaml ]; then
    cp /app/config.default.yaml /config/darkstar/config.yaml
    log "Created default config at /config/darkstar/config.yaml"
fi

# Migrate config.yaml, merge the Supervisor token into secrets.yaml and apply
# Add-on UI options (logic and tests live in backend/addon_bootstrap.py)
python3 -m backend.addon_bootstrap

# Symlink config files to app directory
ln -sf /config/darkstar/config.yaml /app/config.yaml
ln -sf /config/darkstar/secrets.yaml /app/secrets.yaml

# Create data directory for persistent storage
mkdir -p /share/darkstar
ln -sf /share/darkstar /app/data



# -----------------------------------------------------------------------------
# DATABASE MIGRATION (ALEMBIC)
# -----------------------------------------------------------------------------
# Run Alembic migrations to ensure database schema is current.
# This prevents "no such column" errors when upgrading to versions with new schema.
log "Running database migrations..."
export DB_PATH=/share/darkstar/planner_learning.db

if [ -f /app/alembic.ini ]; then
    # Run migration with proper error handling and logging
    if /usr/local/bin/python3.12 -m alembic upgrade head 2>&1 | while read -r line; do log "[ALEMBIC] $line"; done; then
        log "✅ Database migrations complete."
    else
        log "❌ ERROR: Database migration failed!"
        log "Recovery: Check the logs above for detailed error information."
        log "The container will now exit to prevent starting with an inconsistent database state."
        exit 1
    fi
else
    log "⚠️  WARNING: /app/alembic.ini not found, skipping database migrations."
    log "HINT: This may cause errors if the database schema is outdated."
fi

# -----------------------------------------------------------------------------
# LEGACY CODE DETECTION (REV ARC11)
# -----------------------------------------------------------------------------
# Ensure we aren't accidentally running old sync code after the ARC11 migration
if grep -q "store.Session()" /app/backend/learning/store.py 2>/dev/null; then
    log "CRITICAL ERROR: Legacy sync code detected in store.py!"
    log "The ARC11 migration requires a clean async codebase."
    log "Please pull the latest changes and ensure 'store.Session' is removed."
    exit 1
fi

log "Bootstrapping complete. Starting server..."

# Start FastAPI via Uvicorn
exec uvicorn backend.main:app --host 0.0.0.0 --port 5000 --log-level "$LOG_LEVEL"
