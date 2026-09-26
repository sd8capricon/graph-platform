"""Redis cache invalidation shared with the management API.

PostgreSQL remains authoritative. Worker transitions commit first; Redis
invalidation is best-effort, with short API TTLs bounding staleness if Redis is
unavailable.
"""

import hashlib
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from redis.asyncio import Redis
from redis.exceptions import RedisError

from common.config import settings

logger = logging.getLogger(__name__)

API_CACHE_NAMESPACE = "graph-platform:api:v1"


def _component(value: str) -> str:
    """Hash a key component so arbitrary ids cannot change key structure."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def index_job_cache_key(organization_id: str, knowledge_base_id: str, job_id: str) -> str:
    return (
        f"{API_CACHE_NAMESPACE}:org:{_component(organization_id)}"
        f":knowledge-base:{_component(knowledge_base_id)}"
        f":index-job:{_component(job_id)}"
    )


def knowledge_base_cache_keys(organization_id: str, knowledge_base_id: str) -> tuple[str, str]:
    org = _component(organization_id)
    kb = _component(knowledge_base_id)
    return (
        f"{API_CACHE_NAMESPACE}:org:{org}:knowledge-bases",
        f"{API_CACHE_NAMESPACE}:org:{org}:knowledge-base:{kb}",
    )


class CacheInvalidator:
    """Best-effort invalidation of API-owned cached read models."""

    def __init__(self, client: Redis):
        self._client = client

    async def invalidate_job(self, organization_id: str, knowledge_base_id: str, job_id: str) -> None:
        await self._delete(
            index_job_cache_key(organization_id, knowledge_base_id, job_id),
            job_id=job_id,
        )

    async def invalidate_knowledge_base(
        self, organization_id: str, knowledge_base_id: str, *, job_id: str | None = None
    ) -> None:
        keys = list(knowledge_base_cache_keys(organization_id, knowledge_base_id))
        if job_id is not None:
            keys.append(index_job_cache_key(organization_id, knowledge_base_id, job_id))
        await self._delete(*keys, job_id=job_id)

    async def _delete(self, *keys: str, job_id: str | None) -> None:
        failed = False
        for key in keys:
            try:
                await self._client.delete(key)
            except RedisError:
                failed = True

        if failed:
            logger.warning(
                "Redis cache invalidation failed for ingestion job %s; cache TTL will expire stale data",
                job_id or "unknown",
            )


@asynccontextmanager
async def open_cache_invalidator() -> AsyncIterator[CacheInvalidator | None]:
    """Open a task-scoped Redis client when a connection string is configured."""
    redis_settings = settings.redis
    if not redis_settings.is_configured:
        yield None
        return

    connection_string = redis_settings.connection_string.get_secret_value()
    try:
        client = Redis.from_url(
            connection_string,
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
            health_check_interval=30,
        )
    except (RedisError, ValueError):
        logger.warning(
            "Configured Redis connection string could not be parsed; cache invalidation is disabled"
        )
        yield None
        return
    try:
        yield CacheInvalidator(client)
    finally:
        try:
            await client.aclose()
        except RedisError:
            logger.debug("Failed to close Redis cache client", exc_info=True)


__all__ = [
    "API_CACHE_NAMESPACE",
    "CacheInvalidator",
    "index_job_cache_key",
    "knowledge_base_cache_keys",
    "open_cache_invalidator",
]
