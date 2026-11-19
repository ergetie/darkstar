import asyncio
import logging
from typing import Any

import socketio
from socketio import AsyncServer

logger = logging.getLogger("darkstar.websockets")

# The connect/disconnect handlers are registered with Socket.IO and called implicitly


class WebSocketManager:
    """
    Singleton manager for the Socket.IO AsyncServer.
    Handles the bridge between synchronous threads (Executor) and the async event loop.
    """

    _instance: "WebSocketManager | None" = None
    sio: AsyncServer
    loop: asyncio.AbstractEventLoop | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize AsyncServer in ASGI mode
            # REV F11 DEBUG: Enable verbose logging
            cls._instance.sio = socketio.AsyncServer(
                async_mode="asgi",
                cors_allowed_origins=[],  # No CORS headers; cross-site guard lives in FetchSiteGuard
                logger=False,  # Disable Socket.IO logging (Rev F21)
                engineio_logger=False,  # Disable Engine.IO logging (Rev F21)
            )
            cls._instance.loop = None

            # Register connect/disconnect handlers for debugging
            cls._instance._register_debug_handlers()
        return cls._instance

    def _register_debug_handlers(self):
        """Register Socket.IO event handlers for debugging."""

        @self.sio.event  # type: ignore[misc]
        async def connect(sid: str, environ: dict[str, Any]) -> None:  # type: ignore[reportUnusedFunction]
            """Log client connections with request details."""
            path = environ.get("PATH_INFO", "unknown")
            query = environ.get("QUERY_STRING", "")
            headers = {k: v for k, v in environ.items() if k.startswith("HTTP_")}
            logger.info(f"🔌 Socket.IO client CONNECTED: sid={sid}")
            logger.info(f"   PATH_INFO: {path}")
            logger.info(f"   QUERY_STRING: {query}")
            logger.info(
                f"   Headers: X-Ingress-Path={headers.get('HTTP_X_INGRESS_PATH', 'not present')}"
            )

        @self.sio.event  # type: ignore[misc]
        async def disconnect(sid: str) -> None:  # type: ignore[reportUnusedFunction]
            """Log client disconnections."""
            logger.info(f"🔌 Socket.IO client DISCONNECTED: sid={sid}")

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Capture the running event loop on startup."""
        self.loop = loop
        logger.info("WebSocketManager: Event loop captured.")

    async def emit(self, event: str, data: Any, to: str | None = None) -> None:
        """
        Emit an event from an async context (e.g. FastAPI route).
        """
        try:
            await self.sio.emit(event, data, to=to)  # type: ignore[reportUnknownMemberType]
        except Exception as e:
            logger.error(f"WebSocketManager: Failed to emit '{event}': {e}", exc_info=True)

    def emit_sync(self, event: str, data: Any, to: str | None = None):
        """
        Emit an event from a synchronous context (e.g. Executor thread).
        This schedules the emit coroutine on the main event loop.
        """
        if self.loop is None or self.loop.is_closed():
            # This might happen during shutdown or if called before startup
            if self.loop is None:
                logger.warning(
                    f"WebSocketManager: emit_sync('{event}') called before loop capture."
                )
            return

        try:
            asyncio.run_coroutine_threadsafe(
                self.sio.emit(event, data, to=to),  # type: ignore[reportUnknownMemberType]
                self.loop,  # type: ignore[reportUnknownArgumentType]
            )
        except Exception as e:
            logger.error(f"WebSocketManager: Failed to schedule emit_sync('{event}'): {e}")

    async def invalidate_and_push(self, cache_key: str, event: str, data: Any) -> None:
        """Invalidate cache and push event to clients."""
        from backend.core.cache import cache

        await cache.invalidate(cache_key)
        await self.emit(event, data)


# Global instance
ws_manager = WebSocketManager()
