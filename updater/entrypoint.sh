#!/bin/sh
set -eu

if [ -z "${DARKSTAR_UPDATER_TOKEN:-}" ]; then
    echo "ERROR: DARKSTAR_UPDATER_TOKEN is empty. Set it in .env (see docs/OPERATIONS.md)." >&2
    exit 1
fi
if [ -z "${DARKSTAR_REPO_DIR:-}" ]; then
    echo "ERROR: DARKSTAR_REPO_DIR is empty. Set it in .env to the absolute repo path." >&2
    exit 1
fi

cd /opt/darkstar
exec python -m updater.server
