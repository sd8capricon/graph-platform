"""Task-scoped object storage for the ingestion worker."""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from common.storage.base import StorageService


@asynccontextmanager
async def open_storage_service() -> AsyncIterator[StorageService]:
    """Yield the configured storage service, closing it on exit.

    Mirrors ``open_job_resources``/``open_cache_invalidator``: stages take a
    ``StorageService`` instead of importing provider modules themselves.
    """
    from common.config import settings
    from common.storage.factory import create_storage_service

    service = create_storage_service(settings.storage)
    try:
        yield service
    finally:
        await service.aclose()


__all__ = ["open_storage_service"]
