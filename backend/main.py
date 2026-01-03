import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import UTC

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import events to register handlers
# Import routers
from backend.api.routers import (
    config,
    executor,
    forecast,
    learning,
    legacy,
    schedule,
    services,
    system,
    theme,
)
from backend.core.websockets import ws_manager

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("darkstar.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events (FastAPI 0.93+)."""
    # Startup
    logger.info("🚀 Darkstar ASGI Server Starting (Rev ARC1)...")
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)

    # Start HA WebSocket Client (Background)
    from backend.ha_socket import start_ha_socket_client

    start_ha_socket_client()

    yield  # Server is running

    # Shutdown
    logger.info("👋 Darkstar ASGI Server Shutting Down...")


def create_app() -> socketio.ASGIApp:
    """Factory to create the ASGI app."""

    # 1. Create FastAPI App
    app = FastAPI(
        title="Darkstar Energy Manager",
        version="2.0.0",
        description="Next-Gen AI Energy Manager (Rev ARC1)",
        lifespan=lifespan,
    )

    # 2. CORS (Permissive for local dev)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Mount Routers
    app.include_router(system.router)
    app.include_router(theme.router)
    app.include_router(schedule.router)
    app.include_router(forecast.router)
    app.include_router(executor.router)
    app.include_router(config.router)
    app.include_router(services.router_ha)
    app.include_router(services.router_services)
    app.include_router(legacy.router)
    app.include_router(learning.router)

    # Mount forecast_router for /api/forecast/* endpoints
    from backend.api.routers.forecast import forecast_router

    app.include_router(forecast_router)

    # Mount debug router for /api/debug/* and /api/history/* endpoints
    from backend.api.routers.debug import router as debug_router

    app.include_router(debug_router)

    # 4. Health Check - Using comprehensive HealthChecker
    @app.get("/api/health")
    def health_check():
        """
        Return system health status.
        Uses sync function (not async) because HealthChecker uses blocking I/O.
        FastAPI runs sync handlers in threadpool automatically.
        """
        try:
            from backend.health import get_health_status

            status = get_health_status()
            result = status.to_dict()
        except Exception as e:
            # Fallback if health check itself fails
            from datetime import datetime

            result = {
                "healthy": False,
                "issues": [
                    {
                        "category": "health_check",
                        "severity": "critical",
                        "message": f"Health check failed: {e}",
                        "guidance": "Check backend logs for details.",
                        "entity_id": None,
                    }
                ],
                "checked_at": datetime.now(UTC).isoformat(),
                "critical_count": 1,
                "warning_count": 0,
            }
        # Add backwards-compatible fields
        result["status"] = "ok" if result["healthy"] else "unhealthy"
        result["mode"] = "fastapi"
        result["rev"] = "ARC1"
        return result

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
