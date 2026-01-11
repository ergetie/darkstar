"""
Request Timing Middleware for FastAPI

Adds response timing headers and logs slow requests for debugging.

Usage:
    from backend.middleware.timing import TimingMiddleware
    app.add_middleware(TimingMiddleware)
"""

import logging
import time
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("darkstar.timing")

# Threshold in milliseconds for logging slow requests
SLOW_REQUEST_THRESHOLD_MS = 500


class TimingMiddleware(BaseHTTPMiddleware):
    """Middleware that adds timing headers and logs slow requests."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()

        response: Response = await call_next(request)

        process_time_ms = (time.perf_counter() - start_time) * 1000

        # Add timing header (useful for debugging via browser DevTools)
        response.headers["X-Response-Time"] = f"{process_time_ms:.2f}ms"

        # Log slow requests
        if process_time_ms >= SLOW_REQUEST_THRESHOLD_MS:
            logger.warning(
                f"Slow request: {request.method} {request.url.path} took {process_time_ms:.0f}ms"
            )

        return response
