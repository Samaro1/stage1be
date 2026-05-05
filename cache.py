import time
import asyncio

_lock = asyncio.Lock()
# In-memory store
cache_store = {}

# Config
MAX_CACHE_SIZE = 1000
CACHE_TTL = 300  # 5 minutes


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
        del cache_store[key]
        return None

    # Update LRU access time
    entry["last_accessed"] = time.time()

    return entry["value"]


async def set(key: str, value: dict):
    async with _lock:
        if len(cache_store) >= MAX_CACHE_SIZE:
            evict_lru()
        cache_store[key] = {
            "value": value,
            "expires_at": time.time() + CACHE_TTL,
            "last_accessed": time.time(),
        }


def evict_lru():
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
        del cache_store[oldest_key]


async def invalidate_all():
    async with _lock:
        cache_store.clear()