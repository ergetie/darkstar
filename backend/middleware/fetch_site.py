"""
Fetch-Site guard (pure ASGI).

Rejects browser-initiated cross-site writes and WebSocket handshakes based on the
``Sec-Fetch-Site`` request header, which browsers set and page scripts cannot forge.

Rule:
    - ``http`` scope, method POST/PUT/PATCH/DELETE: 403 when the header is
      ``cross-site`` or ``same-site``.
    - ``websocket`` scope: the handshake is refused for the same header values.
    - Everything else (safe methods, ``same-origin``, ``none``, absent header such as
      curl, scripts, Home Assistant or older clients, ``lifespan``) passes through.

Usage:
    from backend.middleware.fetch_site import FetchSiteGuard
    app = FetchSiteGuard(app)
"""

import json
import logging
from typing import Any

from starlette.types import Receive, Scope, Send

logger = logging.getLogger("darkstar.fetch_site")

_BLOCKED_SITES = frozenset({"cross-site", "same-site"})
_WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_FETCH_SITE_HEADER = b"sec-fetch-site"
_DENIED_BODY = json.dumps({"detail": "Cross-site request blocked"}).encode("utf-8")
_WS_POLICY_VIOLATION = 1008


def _fetch_site(scope: Scope) -> str:
    """Return the lower-cased Sec-Fetch-Site value, or '' when absent."""
    for name, value in scope.get("headers", []):
        if name.lower() == _FETCH_SITE_HEADER:
            return value.decode("latin-1").strip().lower()
    return ""


class FetchSiteGuard:
    """Outermost ASGI wrapper that blocks cross-site writes and WebSocket handshakes."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @property
    def other_asgi_app(self) -> Any:
        """Delegate to the wrapped Socket.IO app's FastAPI app (tests and CI read this)."""
        return getattr(self.app, "other_asgi_app", self.app)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        scope_type = scope["type"]

        if scope_type == "http" and scope["method"].upper() in _WRITE_METHODS:
            if _fetch_site(scope) in _BLOCKED_SITES:
                await self._deny_http(scope, send)
                return
        elif scope_type == "websocket" and _fetch_site(scope) in _BLOCKED_SITES:
            await self._deny_websocket(scope, receive, send)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _deny_http(scope: Scope, send: Send) -> None:
        logger.warning(
            "Blocked cross-site %s %s (Sec-Fetch-Site: %s)",
            scope["method"],
            scope.get("path", ""),
            _fetch_site(scope),
        )
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_DENIED_BODY)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _DENIED_BODY})

    @staticmethod
    async def _deny_websocket(scope: Scope, receive: Receive, send: Send) -> None:
        logger.warning(
            "Blocked cross-site WebSocket handshake %s (Sec-Fetch-Site: %s)",
            scope.get("path", ""),
            _fetch_site(scope),
        )
        # The connect event must be consumed before the handshake can be answered.
        message = await receive()
        if message["type"] != "websocket.connect":
            return
        if "websocket.http.response" in scope.get("extensions", {}):
            await send(
                {
                    "type": "websocket.http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(_DENIED_BODY)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "websocket.http.response.body", "body": _DENIED_BODY})
        else:
            await send({"type": "websocket.close", "code": _WS_POLICY_VIOLATION})
