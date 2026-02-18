"""Redis cache layer for query results."""

import hashlib
import json
from typing import Optional

import redis.asyncio as redis


def make_cache_key(query: str, model: str, top_k: int) -> str:
    """Create a deterministic cache key from query parameters."""
    payload = f"{query}:{model}:{top_k}"
    return f"plc_kb:{hashlib.sha256(payload.encode()).hexdigest()}"


async def get_cached(r: redis.Redis, key: str) -> Optional[dict]:
    """Retrieve a cached result by key."""
    val = await r.get(key)
    return json.loads(val) if val else None


async def set_cached(r: redis.Redis, key: str, result: dict, ttl: int = 86400) -> None:
    """Store a result in cache with TTL."""
    await r.setex(key, ttl, json.dumps(result))
