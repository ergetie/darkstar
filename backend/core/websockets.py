import asyncio
import logging
from typing import Any

import socketio

logger = logging.getLogger("darkstar.websockets")


class WebSocketManager:
    """
    Singleton manager for the Socket.IO AsyncServer.
    Handles the bridge between synchronous threads (Executor) and the async event loop.
    """

    _instance: "WebSocketManager | None" = None
    sio: socketio.AsyncServer
    loop: asyncio.AbstractEventLoop | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            # Initialize AsyncServer in ASGI mode
            cls._instance.sio = socketio.AsyncServer(
                async_mode="asgi",
                cors_allowed_origins="*",
                logger=False,  # Set to True for verbose debug
                engineio_logger=False,
            )
            cls._instance.loop = None
        return cls._instance

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Capture the running event loop on startup."""
        self.loop = loop
        logger.info("WebSocketManager: Event loop captured.")

    async def emit(self, event: str, data: Any, to: str | None = None):
        """
        Emit an event from an async context (e.g. FastAPI route).
        """
        await self.sio.emit(event, data, to=to)  # pyright: ignore [reportUnknownMemberType]

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
                self.sio.emit(event, data, to=to),
                self.loop,  # pyright: ignore [reportUnknownMemberType, reportUnknownArgumentType]
            )
        except Exception as e:
            logger.error(f"WebSocketManager: Failed to schedule emit_sync('{event}'): {e}")

    async def invalidate_and_push(self, cache_key: str, event: str, data: Any) -> None:
        """Invalidate cache and push event to clients."""
        from backend.core.cache import cache

        await cache.invalidate(cache_key)
        await self.emit(event, data)

    def invalidate_and_push_sync(self, cache_key: str, event: str, data: Any) -> None:
        """Sync version for thread contexts (Executor, Scheduler).

        IMPORTANT: Invalidates BOTH sync and async caches to ensure consistency.
        The async cache is used by FastAPI routes, so we must clear it too.
        """
        from backend.core.cache import cache, cache_sync

        # Clear sync cache (immediate)
        cache_sync.invalidate(cache_key)

        # Also clear async cache by scheduling on event loop
        if self.loop is not None and not self.loop.is_closed():
            try:
                asyncio.run_coroutine_threadsafe(
                    cache.invalidate(cache_key),
                    self.loop,
                )
            except Exception as e:
                logger.warning(f"Failed to invalidate async cache for '{cache_key}': {e}")

        # Emit the event
        self.emit_sync(event, data)


# Global instance
ws_manager = WebSocketManager()
