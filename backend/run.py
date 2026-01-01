import eventlet
eventlet.monkey_patch()

import os
import logging
import sys
# Project root is assumed to be in PYTHONPATH

# Configure logging for the runner
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("darkstar.run")

# Import after monkey_patching
from backend.webapp import app
from backend.extensions import socketio

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Starting Darkstar with WebSockets on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, log_output=True)
