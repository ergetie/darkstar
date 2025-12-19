#!/usr/bin/env bashrc
# Darkstar Energy Manager - Home Assistant Add-on Entrypoint
set -e

# Read options from HA Add-on config
CONFIG_PATH=/data/options.json

if [ -f "$CONFIG_PATH" ]; then
    TIMEZONE=$(jq -r '.timezone // "Europe/Stockholm"' "$CONFIG_PATH")
    LOG_LEVEL=$(jq -r '.log_level // "info"' "$CONFIG_PATH")
else
    TIMEZONE="Europe/Stockholm"
    LOG_LEVEL="info"
fi

# Set timezone
export TZ="$TIMEZONE"

# Set log level
export LOG_LEVEL="$LOG_LEVEL"

# Copy default config if user hasn't provided one
if [ ! -f /config/darkstar/config.yaml ]; then
    mkdir -p /config/darkstar
    cp /app/config.default.yaml /config/darkstar/config.yaml
    echo "Created default config at /config/darkstar/config.yaml"
fi

if [ ! -f /config/darkstar/secrets.yaml ]; then
    cp /app/secrets.example.yaml /config/darkstar/secrets.yaml
    echo "Created secrets template at /config/darkstar/secrets.yaml"
    echo "Please edit /config/darkstar/secrets.yaml with your HA token!"
fi

# Symlink config files to app directory
ln -sf /config/darkstar/config.yaml /app/config.yaml
ln -sf /config/darkstar/secrets.yaml /app/secrets.yaml

# Create data directory for persistent storage
mkdir -p /share/darkstar
ln -sf /share/darkstar /app/data

echo "Starting Darkstar Energy Manager..."
echo "  Timezone: $TIMEZONE"
echo "  Log Level: $LOG_LEVEL"
echo "  Web UI: http://localhost:5000"

# Start Flask
exec python -m flask run --host=0.0.0.0 --port=5000
