import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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
from backend.api.routers.analyst import router as analyst_router
from backend.api.routers.debug import router as debug_router
from backend.api.routers.forecast import forecast_router
from backend.core.websockets import ws_manager

# Configure Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("darkstar.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events (FastAPI 0.93+)."""
    # Startup
    logger.info("🚀 Darkstar ASGI Server Starting (Rev ARC8)...")
    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)

    # Start background scheduler (Rev ARC8)
    from backend.services.scheduler_service import scheduler_service

    await scheduler_service.start()

    # Deferred import: ha_socket depends on ws_manager being fully initialized
    from backend.ha_socket import start_ha_socket_client

    start_ha_socket_client()

    yield  # Server is running

    # Shutdown
    logger.info("👋 Darkstar ASGI Server Shutting Down...")
    await scheduler_service.stop()


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

    # 3. Timing Middleware for Performance Monitoring (Rev PERF1)
    from backend.middleware.timing import TimingMiddleware

    app.add_middleware(TimingMiddleware)


    # 4. Mount Routers
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

    # Mount additional routers
    app.include_router(forecast_router)
    app.include_router(debug_router)
    app.include_router(analyst_router)

    # 4. Health Check - Using comprehensive HealthChecker
    @app.get("/api/health")
    async def health_check():  # type: ignore[reportUnusedFunction]
        """
        Return system health status.
        Uses sync function (not async) because HealthChecker uses blocking I/O.
        FastAPI runs sync handlers in threadpool automatically.
        """
        try:
            # Deferred import: health module has heavy dependencies (httpx, aiosqlite)
            from backend.health import get_health_status

            status = await get_health_status()
            result = status.to_dict()
        except Exception as e:
            # Fallback if health check itself fails

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
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
    else:
        logger.warning(f"Static directory not found at {static_dir}. Frontend may not be served.")

    # 6. Wrap with Socket.IO ASGI App
    # This intercepts /socket.io requests and passes others to FastAPI
    socket_app = socketio.ASGIApp(ws_manager.sio, other_asgi_app=app)

    return socket_app


# The entry point for uvicorn
# Usage: uvicorn backend.main:app
app: socketio.ASGIApp = create_app()
