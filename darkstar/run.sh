#!/usr/bin/env bash
# Darkstar Energy Manager - Home Assistant Add-on Entrypoint
set -e

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
}

# Locations (overridable for tests)
APP_DIR="${APP_DIR:-/app}"
CONFIG_DIR="${CONFIG_DIR:-/config/darkstar}"
SHARE_DIR="${SHARE_DIR:-/share/darkstar}"
PYTHON="${PYTHON:-/usr/local/bin/python3.12}"

# Read options from HA Add-on config
CONFIG_PATH="${CONFIG_PATH:-/data/options.json}"

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
mkdir -p "$CONFIG_DIR"

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
    if [ ! -f "$CONFIG_DIR/secrets.yaml" ]; then
        cp "$APP_DIR/secrets.example.yaml" "$CONFIG_DIR/secrets.yaml"
        log "Created secrets template at $CONFIG_DIR/secrets.yaml"
        log "Please edit $CONFIG_DIR/secrets.yaml with your HA token!"
    fi
fi

# =============================================================================
# CONFIG.YAML SETUP
# =============================================================================

if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    cp "$APP_DIR/config.default.yaml" "$CONFIG_DIR/config.yaml"
    log "Created default config at $CONFIG_DIR/config.yaml"
fi

# Migrate config.yaml, merge the Supervisor token into secrets.yaml and apply
# Add-on UI options (logic and tests live in backend/addon_bootstrap.py)
python3 -m backend.addon_bootstrap

# Symlink config files to app directory
ln -sf "$CONFIG_DIR/config.yaml" "$APP_DIR/config.yaml"
ln -sf "$CONFIG_DIR/secrets.yaml" "$APP_DIR/secrets.yaml"

# Create data directory for persistent storage
mkdir -p "$SHARE_DIR"
ln -sf "$SHARE_DIR" "$APP_DIR/data"



# -----------------------------------------------------------------------------
# DATABASE MIGRATION (ALEMBIC)
# -----------------------------------------------------------------------------
# backend.db_safety backs the database up before a migration (or the one-time
# storage-format switch), restores that backup if the migration fails, and
# compacts the file afterwards. Same flow as scripts/docker-entrypoint.sh.
# This prevents "no such column" errors when upgrading to versions with new schema.
export DB_PATH="$SHARE_DIR/planner_learning.db"

if [ -f "$APP_DIR/alembic.ini" ]; then
    log "Checking database state..."
    # stdout is the backup path (empty when nothing was backed up); logs go to stderr.
    if ! DB_BACKUP=$("$PYTHON" -m backend.db_safety pre-migrate); then
        log "❌ ERROR: Database backup failed, migration aborted. Database left untouched."
        exit 1
    fi

    log "Running database migrations..."
    # Output goes to a file (on the share, not RAM-backed /tmp) and is logged
    # afterwards, so alembic's real exit code is tested instead of a pipe's.
    ALEMBIC_LOG="$SHARE_DIR/alembic-upgrade.log"
    if "$PYTHON" -m alembic upgrade head >"$ALEMBIC_LOG" 2>&1; then
        ALEMBIC_OK=1
    else
        ALEMBIC_OK=0
    fi
    while IFS= read -r line || [ -n "$line" ]; do log "[ALEMBIC] $line"; done <"$ALEMBIC_LOG"
    rm -f "$ALEMBIC_LOG"

    if [ "$ALEMBIC_OK" != "1" ]; then
        log "❌ ERROR: Database migration failed!"
        if [ -n "$DB_BACKUP" ]; then
            if "$PYTHON" -m backend.db_safety restore "$DB_BACKUP"; then
                log "Database restored from backup $DB_BACKUP"
            else
                log "❌ ERROR: Automatic restore failed! Restore manually from $DB_BACKUP"
                log "Recovery: python3 -m backend.db_safety restore $DB_BACKUP"
            fi
        fi
        log "The container will now exit to prevent starting with an inconsistent database state."
        exit 1
    fi
    log "✅ Database migrations complete."

    # One-time prune and shrink. Never blocks start-up.
    "$PYTHON" -m backend.db_safety compact "$DB_BACKUP" ||
        log "⚠️  WARNING: Database compaction failed, continuing."
else
    log "⚠️  WARNING: $APP_DIR/alembic.ini not found, skipping database migrations."
    log "HINT: This may cause errors if the database schema is outdated."
fi

# -----------------------------------------------------------------------------
# LEGACY CODE DETECTION (REV ARC11)
# -----------------------------------------------------------------------------
# Ensure we aren't accidentally running old sync code after the ARC11 migration
if grep -q "store.Session()" "$APP_DIR/backend/learning/store.py" 2>/dev/null; then
    log "CRITICAL ERROR: Legacy sync code detected in store.py!"
    log "The ARC11 migration requires a clean async codebase."
    log "Please pull the latest changes and ensure 'store.Session' is removed."
    exit 1
fi

log "Bootstrapping complete. Starting server..."

# Start FastAPI via Uvicorn
exec uvicorn backend.main:app --host 0.0.0.0 --port 5000 --log-level "$LOG_LEVEL"
