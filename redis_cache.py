"""
Redis-based async cache implementation with TTL support.
Falls back to in-memory cache if Redis is unavailable.
"""

import asyncio
import json
import logging
import pickle
from typing import Any, Callable, Optional

try:
    import redis.asyncio as redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

from arcache import AsyncRefreshTTL


class RedisCache:
    """Redis connection manager with fallback support."""

    _instance: Optional["RedisCache"] = None
    _client: Optional[Any] = None
    _enabled: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    async def init(cls, redis_url: str) -> bool:
        """Initialize Redis connection."""
        if not REDIS_AVAILABLE:
            logging.warning("redis package not installed, using in-memory cache")
            return False

        if not redis_url:
            logging.info("Redis URL not configured, using in-memory cache")
            return False

        try:
            cls._client = redis.from_url(redis_url, decode_responses=False)
            await cls._client.ping()
            cls._enabled = True
            logging.info(f"Redis cache connected: {redis_url}")
            return True
        except Exception as e:
            logging.warning(f"Redis connection failed: {e}, using in-memory cache")
            cls._client = None
            cls._enabled = False
            return False

    @classmethod
    def get_client(cls) -> Optional[Any]:
        return cls._client if cls._enabled else None

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._enabled

    @classmethod
    async def close(cls):
        if cls._client:
            await cls._client.close()
            cls._client = None
            cls._enabled = False


class AsyncRedisTTL:
    """
    Async cache decorator with Redis backend and TTL support.
    Falls back to in-memory AsyncRefreshTTL if Redis is unavailable.
    """

    def __init__(
        self,
        time_to_live: int = 60,
        maxsize: int = 1024,
        skip_args: int = 0,
        concurrent_lock: Optional[int] = None,
        key_prefix: str = "cache"
    ):
        self.time_to_live = time_to_live
        self.maxsize = maxsize
        self.skip_args = skip_args
        self.concurrent_lock = concurrent_lock
        self.key_prefix = key_prefix

        # Fallback to in-memory cache
        self._memory_cache = AsyncRefreshTTL(
            time_to_live=time_to_live,
            maxsize=maxsize,
            skip_args=skip_args,
            concurrent_lock=concurrent_lock
        )

        if concurrent_lock is not None and concurrent_lock > 0:
            self._sem = asyncio.Semaphore(concurrent_lock)
        else:
            self._sem = None

    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """Generate cache key from function name and arguments."""
        key_parts = [self.key_prefix, func_name]

        for arg in args:
            key_parts.append(str(arg))

        for k, v in sorted(kwargs.items()):
            if not k.startswith('_'):
                key_parts.append(f"{k}={v}")

        return ":".join(key_parts)

    def __call__(self, func: Callable):
        async def wrapper(*args, **kwargs):
            cache_refresh = kwargs.pop('_cache_refresh', False)
            client = RedisCache.get_client()

            # Fallback to memory cache if Redis not available
            if client is None:
                return await self._memory_cache(func)(*args, **kwargs, _cache_refresh=cache_refresh)

            cache_key = self._make_key(func.__name__, args[self.skip_args:], kwargs)

            async def _get_or_set():
                if not cache_refresh:
                    try:
                        cached = await client.get(cache_key)
                        if cached is not None:
                            return pickle.loads(cached)
                    except Exception as e:
                        logging.warning(f"Redis get error: {e}")

                # Cache miss or refresh requested
                result = await func(*args, **kwargs)

                try:
                    await client.setex(
                        cache_key,
                        self.time_to_live,
                        pickle.dumps(result)
                    )
                except Exception as e:
                    logging.warning(f"Redis set error: {e}")

                return result

            if self._sem:
                async with self._sem:
                    return await _get_or_set()
            else:
                return await _get_or_set()

        wrapper.__name__ = func.__name__
        return wrapper


class RedisDict:
    """
    Dict-like interface backed by Redis hash.
    Falls back to regular dict if Redis is unavailable.
    """

    def __init__(self, name: str, ttl: Optional[int] = None):
        self.name = name
        self.ttl = ttl
        self._fallback: dict = {}

    async def get(self, key: str, default: Any = None) -> Any:
        client = RedisCache.get_client()
        if client is None:
            return self._fallback.get(key, default)

        try:
            value = await client.hget(self.name, key)
            if value is None:
                return default
            return pickle.loads(value)
        except Exception as e:
            logging.warning(f"RedisDict get error: {e}")
            return self._fallback.get(key, default)

    async def set(self, key: str, value: Any):
        client = RedisCache.get_client()
        self._fallback[key] = value

        if client is None:
            return

        try:
            await client.hset(self.name, key, pickle.dumps(value))
            if self.ttl:
                await client.expire(self.name, self.ttl)
        except Exception as e:
            logging.warning(f"RedisDict set error: {e}")

    async def delete(self, key: str):
        client = RedisCache.get_client()
        self._fallback.pop(key, None)

        if client is None:
            return

        try:
            await client.hdel(self.name, key)
        except Exception as e:
            logging.warning(f"RedisDict delete error: {e}")

    async def clear(self):
        client = RedisCache.get_client()
        self._fallback.clear()

        if client is None:
            return

        try:
            await client.delete(self.name)
        except Exception as e:
            logging.warning(f"RedisDict clear error: {e}")

    def sync_get(self, key: str, default: Any = None) -> Any:
        """Synchronous get from fallback dict only."""
        return self._fallback.get(key, default)

    def sync_set(self, key: str, value: Any):
        """Synchronous set to fallback dict only."""
        self._fallback[key] = value

    def sync_pop(self, key: str, default: Any = None) -> Any:
        """Synchronous pop from fallback dict only."""
        return self._fallback.pop(key, default)
