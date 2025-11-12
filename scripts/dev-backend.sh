#!/usr/bin/env bash
set -euo pipefail
export FLASK_APP=backend.webapp
# Activate venv if present
if [ -d "venv" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi
python -m flask run --host 0.0.0.0 --port 5000
