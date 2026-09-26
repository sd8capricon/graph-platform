"""Tests for the cache-key contract shared with the management API."""

import hashlib

from redis.exceptions import ConnectionError as RedisConnectionError

from common.config import settings
from common.schemas.redis import RedisSettings
from ingestion_worker.cache import (
    API_CACHE_NAMESPACE,
    CacheInvalidator,
    index_job_cache_key,
    knowledge_base_cache_keys,
    open_cache_invalidator,
)


class _RecordingRedis:
    def __init__(self, *, error=None):
        self.deleted: list[str] = []
        self.error = error

    async def delete(self, *keys):
        if self.error:
            raise self.error
        self.deleted.extend(keys)


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def test_index_job_key_matches_the_cross_language_versioned_contract():
    assert index_job_cache_key("org-1", "kb-1", "job-1") == (
        f"{API_CACHE_NAMESPACE}:org:{_hash('org-1')}:knowledge-base:{_hash('kb-1')}"
        f":index-job:{_hash('job-1')}"
    )


async def test_knowledge_base_invalidation_removes_collection_and_detail_keys():
    redis = _RecordingRedis()
    cache = CacheInvalidator(redis)
    await cache.invalidate_knowledge_base("org-1", "kb-1", job_id="job-1")
    assert redis.deleted == [
        *knowledge_base_cache_keys("org-1", "kb-1"),
        index_job_cache_key("org-1", "kb-1", "job-1"),
    ]


async def test_cache_invalidation_failure_is_best_effort(caplog):
    cache = CacheInvalidator(_RecordingRedis(error=RedisConnectionError("offline")))

    await cache.invalidate_job("org-1", "kb-1", "job-1")

    assert "Redis cache invalidation failed" in caplog.text


async def test_invalid_configured_uri_disables_invalidation_without_exposing_it(monkeypatch, caplog):
    secret = "not-a-redis-uri-secret"
    monkeypatch.setattr(settings, "redis", RedisSettings(connection_string=secret))

    async with open_cache_invalidator() as cache:
        assert cache is None

    assert "cache invalidation is disabled" in caplog.text
    assert secret not in caplog.text
