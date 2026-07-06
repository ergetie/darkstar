from backend.core.logging import setup_logging

setup_logging()

# ruff: noqa: E402

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import socketio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Import routers
from backend.api.routers import (
    config,
    dashboard,
    energy,
    executor,
    forecast,
    ha,
    learning,
    legacy,
    loads,
    schedule,
    system,
    theme,
    water,
)
from backend.api.routers.analyst import router as analyst_router
from backend.api.routers.debug import router as debug_router
from backend.api.routers.executor import get_executor_instance
from backend.api.routers.forecast import forecast_router
from backend.api.routers.price_forecast import router as price_forecast_router
from backend.core.websockets import ws_manager

logger = logging.getLogger("darkstar.main")


# Import inputs for config loading
from backend.core.secrets import load_yaml
from backend.learning.store import LearningStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown events (FastAPI 0.93+)."""
    # Startup
    logger.info("🚀 Darkstar ASGI Server Starting...")

    # 0. Model Bootstrap (REV // A24)
    # Ensure ML models are seeded before anything else tries to load them
    try:
        from ml.bootstrap import ensure_active_models

        ensure_active_models()
    except Exception as e:
        logger.error(f"Model bootstrap failed: {e}")

    # 1. Container/Environment Debugging (Task 4)
    import os
    import sys

    cwd = Path.cwd()
    logger.info("📍 Startup Context:")
    logger.info(f"   CWD: {cwd}")
    logger.info(f"   Python: {sys.executable}")

    # Check for Alembic Config (Task 3)
    alembic_ini_path = cwd / "alembic.ini"
    if not alembic_ini_path.exists():
        # Fallback for HA add-on /app directory
        if Path("/app/alembic.ini").exists():
            alembic_ini_path = Path("/app/alembic.ini")
        # Fallback for relative to this file
        elif (Path(__file__).parent.parent / "alembic.ini").exists():
            alembic_ini_path = Path(__file__).parent.parent / "alembic.ini"

    logger.info(f"   Alembic Config: {alembic_ini_path} (exists: {alembic_ini_path.exists()})")

    # 2. Migration Check (Safeguard)
    # Migrations are now handled by docker-entrypoint.sh BEFORE FastAPI starts.
    # We just log the status here for visibility.
    try:
        db_path = os.getenv("DB_PATH", "data/planner_learning.db")
        if not Path(db_path).exists():
            logger.warning(f"Database file not found at {db_path}. Migration may have skipped.")
        else:
            logger.info(f"✅ Database found at {db_path}")
    except Exception as e:
        logger.error(f"Error during startup check: {e}")

    loop = asyncio.get_running_loop()
    ws_manager.set_loop(loop)

    # Start background scheduler (Rev ARC8)
    from backend.services.scheduler_service import scheduler_service

    await scheduler_service.start()

    # Start observation recorder (REV // Complete Cost Reality Fix)
    from backend.services.recorder_service import recorder_service

    await recorder_service.start()

    # Start runtime invariant monitors (stabilization-review-2, read-only)
    try:
        from backend.monitors import invariant_monitors

        await invariant_monitors.start()
    except Exception as e:
        # fail-open: monitors must never block startup (design D4)
        logger.error("Failed to start invariant monitors: %s", e)

    executor_instance = None
    try:
        executor_instance = get_executor_instance()
        if executor_instance:
            from executor.config import check_mock_entities

            check_mock_entities(executor_instance.config)

            if executor_instance.config.enabled:
                executor_instance.start()
                logger.info(
                    "✅ Executor started (interval: %ds, shadow_mode: %s)",
                    executor_instance.config.interval_seconds,
                    executor_instance.config.shadow_mode,
                )
            else:
                logger.info("⏸️  Executor initialized but disabled in config")
        else:
            logger.warning("Executor could not be initialized (check logs)")
    except Exception as e:
        logger.error("Failed to initialize executor: %s", e, exc_info=True)
        # Don't crash the app if executor fails - other services can still run
        executor_instance = None

    # Deferred import: ha_socket depends on ws_manager being fully initialized
    from backend.ha_socket import start_ha_socket_client

    start_ha_socket_client()

    # Initialize Async LearningStore (REV ARC10)
    try:
        config = load_yaml("config.yaml")
        # Respect DB_PATH env var if present (for consistency with Alembic)
        db_path = os.getenv("DB_PATH") or str(
            config.get("learning", {}).get("sqlite_path", "data/planner_learning.db")
        )
        tz_name = str(config.get("timezone", "Europe/Stockholm"))
        import pytz

        store = LearningStore(db_path, pytz.timezone(tz_name))
        await store.ensure_wal_mode()
        app.state.learning_store = store
        logger.info(f"✅ LearningStore initialized (Async) at {db_path}")

        from ml.price_forecast import cleanup_price_forecast_duplicates

        deleted = cleanup_price_forecast_duplicates(db_path)
        if deleted > 0:
            logger.info(f"🧹 Cleaned up {deleted} duplicate price forecast rows")
    except Exception as e:
        logger.error(f"Failed to initialize LearningStore: {e}")
        # We can't easily fail here without breaking the app, but partial functionality might work?
        # For now, let's allow it but semantic routes will 500.
        app.state.learning_store = None

    yield  # Server is running

    # Shutdown
    logger.info("👋 Darkstar ASGI Server Shutting Down...")

    # Close shared HA HTTP client
    try:
        from backend.core.ha_client import close_ha_http_client

        await close_ha_http_client()
    except Exception as e:
        logger.error("Failed to close HA HTTP client: %s", e)

    # Close LearningStore
    if hasattr(app.state, "learning_store") and app.state.learning_store:
        await app.state.learning_store.close()
        logger.info("✅ LearningStore closed")

    # Stop executor
    if executor_instance:
        try:
            executor_instance.stop()
            logger.info("✅ Executor stopped")
        except Exception as e:
            logger.error("Failed to stop executor: %s", e, exc_info=True)

    await scheduler_service.stop()

    from backend.services.recorder_service import recorder_service

    await recorder_service.stop()

    try:
        from backend.monitors import invariant_monitors

        await invariant_monitors.stop()
    except Exception as e:
        logger.error("Failed to stop invariant monitors: %s", e)

    from backend.ha_socket import stop_ha_socket_client

    stop_ha_socket_client()


def get_base_path(request: Request) -> str:
    """Get the base path for frontend assets.

    When running under HA Ingress, the X-Ingress-Path header contains
    the path prefix. Otherwise, use root path.
    """
    ingress_path = request.headers.get("X-Ingress-Path", "")
    if ingress_path:
        # Ensure trailing slash for base href
        return ingress_path if ingress_path.endswith("/") else ingress_path + "/"
    return "/"

    return "/"


def validate_path(base_dir: Path, requested_path: str) -> Path:
    """Validate that the requested path is within the base directory.

    Args:
        base_dir: The trusted base directory (e.g., static files).
        requested_path: The potentially unsafe relative path.

    Returns:
        Path: The resolved absolute path if safe.

    Raises:
        HTTPException(404): If path traversal is detected.
    """
    try:
        # Join and resolve
        target = base_dir / requested_path
        resolved = target.resolve()

        # Verify strict containment
        # We check both:
        # 1. Is base_dir a parent of resolved?
        # 2. Is resolved exactly base_dir? (Accessing root static dir)
        base_resolved = base_dir.resolve()

        if base_resolved not in resolved.parents and resolved != base_resolved:
            raise HTTPException(status_code=404, detail="Not found")

        return resolved
    except (ValueError, OSError):
        raise HTTPException(status_code=404, detail="Not found") from None


def create_app() -> socketio.ASGIApp:
    """Factory to create the ASGI app."""

    # 1. Create FastAPI App
    from backend.api.routers.system import _get_git_version  # type: ignore[reportPrivateUsage]

    app = FastAPI(
        title="Darkstar Energy Manager",
        version=_get_git_version(),
        description="Next-Gen AI Energy Manager",
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
    app.include_router(dashboard.router)
    app.include_router(system.router)
    app.include_router(theme.router)
    app.include_router(schedule.router)
    app.include_router(forecast.router)
    app.include_router(executor.router)
    app.include_router(config.router)
    app.include_router(ha.router)
    app.include_router(ha.router_misc)
    app.include_router(energy.router)
    app.include_router(water.router)
    app.include_router(legacy.router)
    app.include_router(learning.router)
    app.include_router(loads.router)

    # Mount additional routers
    app.include_router(forecast_router)
    app.include_router(debug_router)
    app.include_router(analyst_router)
    app.include_router(price_forecast_router)

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

    # 5. Mount Static Files (Frontend) with SPA fallback
    # For production: serves built React app with client-side routing support
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        from fastapi.responses import FileResponse

        # Mount static assets (JS, CSS, etc.)
        app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

        # Cache the index.html template content
        _index_html_cache: str | None = None

        def get_index_html() -> str:
            """Read and cache index.html content."""
            nonlocal _index_html_cache
            if _index_html_cache is None:
                _index_html_cache = (static_dir / "index.html").read_text()
            return _index_html_cache

        @app.get("/{full_path:path}")
        async def serve_spa(full_path: str, request: Request):  # type: ignore[reportUnusedFunction]
            """Serve index.html for all routes (SPA fallback).

            For HA Ingress support, dynamically injects <base href> tag
            based on X-Ingress-Path header.
            """
            # Prevent API routes from being intercepted by SPA catch-all
            if full_path.startswith("api/") or full_path == "api":
                raise HTTPException(status_code=404, detail="API route not found")

            # Security: Prevent directory traversal attacks
            # checking logic extracted to validate_path for testability
            _ = validate_path(static_dir, full_path)

            # If requesting a specific file that exists, serve it directly
            file_path = static_dir / full_path
            if file_path.is_file():
                return FileResponse(file_path)

            # For SPA routes, inject dynamic base href for HA Ingress support
            base_path = get_base_path(request)
            html_content = get_index_html()

            # Insert <base href> after opening <head> tag
            modified_html = html_content.replace(
                "<head>",
                f'<head>\n  <base href="{base_path}" />',
                1,  # Only replace first occurrence
            )
            return HTMLResponse(content=modified_html, media_type="text/html")
    else:
        logger.warning(f"Static directory not found at {static_dir}. Frontend may not be served.")

    # 6. Wrap with Socket.IO ASGI App
    # This intercepts /socket.io requests and passes others to FastAPI
    socket_app = socketio.ASGIApp(ws_manager.sio, other_asgi_app=app)

    return socket_app


# The entry point for uvicorn
# Usage: uvicorn backend.main:app
app: socketio.ASGIApp = create_app()
