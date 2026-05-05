import time

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


def set(key: str, value: dict):
    """
    Store value in cache with TTL and LRU eviction.
    """
    # Evict if cache is full
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


def invalidate_all():
    """
    Clear entire cache.
    Used after writes to prevent stale data.
    """
    cache_store.clear()