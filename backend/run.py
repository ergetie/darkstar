import eventlet
eventlet.monkey_patch()

import os
import logging
from backend.webapp import app
from backend.extensions import socketio

# Configure logging for the runner
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("darkstar.run")

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Starting Darkstar with WebSockets on port {port}...")
    socketio.run(app, host='0.0.0.0', port=port, log_output=True)
