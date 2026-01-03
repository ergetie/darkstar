import logging
import os

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("darkstar.run")

    port = int(os.environ.get("PORT", 5000))
    logger.info(f"🚀 Starting Darkstar (Rev ARC1) with Uvicorn on port {port}...")

    # Run Uvicorn specifically
    uvicorn.run("backend.main:app", host="0.0.0.0", port=port, reload=True, log_level="info")
