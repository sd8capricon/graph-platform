"""Async orchestration of one ingestion job.

`ingest_job` is Celery-free so it can be unit-tested directly against a SQLite
session and a fake repository. `run_job` opens the real resources. The Celery
task wrapper in `tasks.py` only translates errors into retry/DLQ policy.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from common.repositories.age_graph_repository import AgeGraphRepository

from ingestion_worker.errors import NonRetryableIngestionError, classify_exception
from ingestion_worker.job_store import IndexJobStore

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "partially_failed"})


async def ingest_job(
    job_id: str,
    session: AsyncSession,
    repository: AgeGraphRepository,
    *,
    store: IndexJobStore | None = None,
) -> None:
    """Run one indexing job, or raise a classified error.

    Idempotent: a job already in a terminal state is skipped.

    The graph-payload ingestion this used to perform read the knowledge base's
    inline `Data` JSON, which the management API no longer stores. Until
    file-based ingestion (ADR-0005 Phase 2) exists, a claimed job fails with a
    non-retryable error naming that reason.
    """
    store = store or IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None:
        logger.warning("index_job %s not found; nothing to do", job_id)
        return
    if job.status in _TERMINAL_STATUSES:
        logger.info("index_job %s already %s; skipping", job_id, job.status)
        return

    try:
        kb_row = await store.read_knowledge_base(job.knowledge_base_id)
        if kb_row is None:
            raise NonRetryableIngestionError(
                f"knowledge_base {job.knowledge_base_id} not found for job {job_id}"
            )

        # The knowledge base's inline graph JSON was removed from the API: a
        # knowledge base's content is now the files uploaded to it, and
        # ingesting those is ADR-0005 Phase 2, which is not implemented. Fail
        # explicitly rather than retrying work that cannot succeed.
        raise NonRetryableIngestionError(
            f"knowledge_base {job.knowledge_base_id} has no inline graph payload: "
            "file-based ingestion is not implemented yet"
        )
    except Exception as exc:
        await session.rollback()
        raise classify_exception(exc) from exc


async def fail_job(job_id: str, error: str) -> None:
    """Record a terminal failure on a job, opening its own short-lived session.

    Called from the Celery task's `on_failure` hook once retries are exhausted.
    """
    from ingestion_worker.db import open_job_resources

    async with open_job_resources() as (session, _repository):
        await IndexJobStore(session).mark_job_failed(job_id, error)
        await session.commit()


async def run_job(job_id: str) -> None:
    """Open the worker's DB resources and run one job (the Celery entrypoint)."""
    from ingestion_worker.db import open_job_resources

    async with open_job_resources() as (session, repository):
        await ingest_job(job_id, session, repository)


__all__ = ["ingest_job", "run_job", "fail_job"]