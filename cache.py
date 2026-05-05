import time
import asyncio

_lock: asyncio.Lock | None = None


# In-memory store
cache_store = {}

# Config
MAX_CACHE_SIZE = 1000
CACHE_TTL = 300  # 5 minutes

def _get_lock():
    """Ensure we have a lock for cache operations.
    """
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock

def get(key: str):
    """
    Retrieve value from cache.
    Returns None if not found or expired.
    """
    entry = cache_store.get(key)

    if not entry:
        return None

    # Check expiration
    if entry["expires_at"] < time.time():
        cache_store.pop(key, None)
        return None

    # Update LRU access time
    entry["last_accessed"] = time.time()

    return entry["value"]


async def set(key: str, value: dict):
    async with _get_lock():
        if len(cache_store) >= MAX_CACHE_SIZE:
            await evict_lru()
        cache_store[key] = {
            "value": value,
            "expires_at": time.time() + CACHE_TTL,
            "last_accessed": time.time(),
        }


async def evict_lru():
    """
    Remove least recently used item.
    """
    oldest_key = None
    oldest_access = float("inf")

    for key, entry in cache_store.items():
        if entry["last_accessed"] < oldest_access:
            oldest_access = entry["last_accessed"]
            oldest_key = key

    if oldest_key:
        cache_store.pop(oldest_key, None)


async def invalidate_all():
    async with _get_lock():
        cache_store.clear()