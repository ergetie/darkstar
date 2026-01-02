import asyncio
import logging
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import socketio

from backend.core.websockets import ws_manager

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("darkstar.main")

def create_app() -> socketio.ASGIApp:
    """Factory to create the ASGI app."""
    
    # 1. Create FastAPI App
    app = FastAPI(
        title="Darkstar Energy Manager",
        version="2.0.0",
        description="Next-Gen AI Energy Manager (Rev ARC1)"
    )

    # 2. CORS (Permissive for local dev)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Startup Event: Capture Event Loop for WebSocket Bridge
    @app.on_event("startup")
    async def startup_event():
        logger.info("🚀 Darkstar ASGI Server Starting (Rev ARC1)...")
        loop = asyncio.get_running_loop()
        ws_manager.set_loop(loop)

    # 4. Health Check (Basic) - Will be expanded later
    @app.get("/api/health")
    async def health_check():
        return {"status": "ok", "mode": "fastapi", "rev": "ARC1"}

    # 5. Mount Static Files (Frontend)
    # We expect 'backend/static' to contain the built React app (or symlinks in dev)
    # In 'pnpm run dev', Vite serves frontend, but for production or hybrid dev, we keep this.
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.exists(static_dir):
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    else:
        logger.warning(f"Static directory not found at {static_dir}. Frontend may not be served.")

    # 6. Wrap with Socket.IO ASGI App
    # This intercepts /socket.io requests and passes others to FastAPI
    socket_app = socketio.ASGIApp(ws_manager.sio, other_asgi_app=app)
    
    return socket_app

# The entry point for uvicorn
# Usage: uvicorn backend.main:app
app = create_app()
