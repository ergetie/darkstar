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


# Global instance
ws_manager = WebSocketManager()
