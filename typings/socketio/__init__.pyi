from collections.abc import Callable
from typing import Any

class Client:
    def __init__(self, *args: Any, **kwargs: Any): ...
    def connect(
        self,
        url: str,
        headers: dict[str, str] = ...,
        auth: dict[str, Any] | None = ...,
        wait: bool = ...,
        wait_timeout: float = ...,
    ): ...
    def wait(self): ...
    def emit(
        self,
        event: str,
        data: Any = ...,
        namespace: str | None = ...,
        callback: Callable | None = ...,
    ): ...
    def disconnect(self): ...
    def on(
        self, event: str, handler: Callable | None = None, namespace: str | None = None
    ) -> None: ...

class Server: ...

class AsyncServer:
    def __init__(self, async_mode: str = ..., cors_allowed_origins: Any = ..., **kwargs: Any): ...
    def attach(self, app: Any, socketio_path: str = ...): ...
    def on(self, event: str, namespace: str | None = None) -> Callable: ...
    async def emit(
        self,
        event: str,
        data: Any,
        to: str | None = None,
        room: str | None = None,
        namespace: str | None = None,
    ): ...

class ASGIApp:
    def __init__(
        self, socketio_server: Any, other_asgi_app: Any = ..., socketio_path: str = ...
    ): ...
