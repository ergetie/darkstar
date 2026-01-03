import asyncio

from backend.core.cache import TTLCache, TTLCacheSync


def test_ttl_cache_async_wrapper():
    asyncio.run(_async_cache_tests())

async def _async_cache_tests():
    cache = TTLCache()

    # Test set and get
    await cache.set("key1", "value1", 1.0)
    assert await cache.get("key1") == "value1"

    # Test expiration
    await asyncio.sleep(1.1)
    assert await cache.get("key1") is None

    # Test invalidation
    await cache.set("key2", "value2", 1.0)
    await cache.invalidate("key2")
    assert await cache.get("key2") is None

    # Test prefix invalidation
    await cache.set("prefix:1", "v1", 1.0)
    await cache.set("prefix:2", "v2", 1.0)
    await cache.set("other:1", "v3", 1.0)

    await cache.invalidate_prefix("prefix:")
    assert await cache.get("prefix:1") is None
    assert await cache.get("prefix:2") is None
    assert await cache.get("other:1") == "v3"

def test_ttl_cache_sync():
    cache = TTLCacheSync()
    import time

    # Test set and get
    cache.set("key1", "value1", 0.1)
    assert cache.get("key1") == "value1"

    # Test expiration
    time.sleep(0.2)
    assert cache.get("key1") is None

    # Test invalidation
    cache.set("key2", "value2", 1.0)
    cache.invalidate("key2")
    assert cache.get("key2") is None
