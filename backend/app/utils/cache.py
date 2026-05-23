"""
cache.py
--------
Simple TTL cache for expensive API responses.

Uses cachetools.TTLCache — entries expire after TTL seconds.
Cached via a decorator applied to router functions.

Usage:
    from app.utils.cache import cached

    @router.get("")
    @cached(ttl=300)
    async def my_endpoint():
        ...
"""

import functools
import hashlib
import json
from typing import Any, Callable

from cachetools import TTLCache
from loguru import logger

# One shared cache — 256 entries max, default 5 minute TTL
_cache: TTLCache = TTLCache(maxsize=256, ttl=300)


def make_cache_key(func_name: str, kwargs: dict) -> str:
    """Build a stable string cache key from function name + query params."""
    serialized = json.dumps(kwargs, sort_keys=True, default=str)
    digest = hashlib.md5(serialized.encode()).hexdigest()[:8]
    return f"{func_name}:{digest}"


def cached(ttl: int = 300) -> Callable:
    """
    Decorator that caches async endpoint responses by their query parameters.

    Args:
        ttl: Time-to-live in seconds. Defaults to 300 (5 minutes).
    """
    def decorator(func: Callable) -> Callable:
        # Create a per-function cache with the specified TTL
        func_cache: TTLCache = TTLCache(maxsize=64, ttl=ttl)

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            key = make_cache_key(func.__name__, kwargs)
            if key in func_cache:
                logger.debug(f"Cache hit: {key}")
                return func_cache[key]

            result = await func(*args, **kwargs)
            func_cache[key] = result
            logger.debug(f"Cache set: {key}")
            return result

        # Expose cache for manual invalidation
        wrapper.cache = func_cache  # type: ignore
        return wrapper

    return decorator


def clear_all_caches() -> None:
    """Clear the shared cache — called after data reload."""
    _cache.clear()
    logger.info("Response cache cleared")
