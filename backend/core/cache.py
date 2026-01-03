import asyncio
import time
from typing import Any, TypeVar

T = TypeVar("T")

class TTLCache:
    """Simple TTL cache with async support."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            if key in self._cache:
                value, expires_at = self._cache[key]
                if time.time() < expires_at:
                    return value
                del self._cache[key]
        return None

    async def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        async with self._lock:
            self._cache[key] = (value, time.time() + ttl_seconds)

    async def invalidate(self, key: str) -> None:
        async with self._lock:
            self._cache.pop(key, None)

    async def invalidate_prefix(self, prefix: str) -> None:
        async with self._lock:
            to_delete = [k for k in self._cache if k.startswith(prefix)]
            for k in to_delete:
                del self._cache[k]

# Sync version for non-async contexts
class TTLCacheSync:
    """Thread-safe TTL cache for sync contexts."""

    def __init__(self) -> None:
        import threading
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key in self._cache:
                value, expires_at = self._cache[key]
                if time.time() < expires_at:
                    return value
                del self._cache[key]
        return None

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        with self._lock:
            self._cache[key] = (value, time.time() + ttl_seconds)

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

# Global instances
cache = TTLCache()
cache_sync = TTLCacheSync()
