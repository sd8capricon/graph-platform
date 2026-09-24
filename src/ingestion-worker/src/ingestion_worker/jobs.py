"""Async orchestration of one ingestion job.

`ingest_job` is Celery-free so it can be unit-tested directly against a SQLite
session and a fake repository. `run_job` opens the real resources. The Celery
task wrapper in `tasks.py` only translates errors into retry/DLQ policy.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from common.models.node_embedding import NodeEmbedding
from common.models.schema_embedding import SchemaEmbedding
from common.repositories.age_graph_repository import AgeGraphRepository
from common.schemas.knowledge_base import KnowledgeBase
from common.services.knowledge_base_service import KnowledgeBaseService

from ingestion_worker.config import embedding_model_for_job
from ingestion_worker.errors import NonRetryableIngestionError, classify_exception
from ingestion_worker.job_store import IndexJobStore
from ingestion_worker.pipeline import ingest_knowledge_base

logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"completed", "cancelled", "partially_failed"})
_PUBLISHED = "published"


async def ingest_job(
    job_id: str,
    session: AsyncSession,
    repository: AgeGraphRepository,
    *,
    store: IndexJobStore | None = None,
) -> None:
    """Run one indexing job to completion, or raise a classified error.

    Idempotent: a job already in a terminal state is skipped, and every write on
    the path (graph `MERGE`, side-table upserts, file-row reuse) is safe to
    repeat after an at-least-once redelivery.
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

        knowledge_base = KnowledgeBase.model_validate_json(kb_row.data)
        # The API overlays the outer resource id onto the payload root, so these
        # agree; pinning it keeps the job/file identity consistent either way.
        knowledge_base.id = job.knowledge_base_id

        await KnowledgeBaseService(repository).create_graph(job.graph_name)

        model = embedding_model_for_job(job.embedding_model_id)
        if model is not None:
            await NodeEmbedding.ensure_embedding_index(session, model)
            await SchemaEmbedding.ensure_embedding_index(session, model)

        await ingest_knowledge_base(
            session,
            repository,
            knowledge_base,
            job.graph_name,
            job.organization_id,
            model,
        )

        # Phase 1 treats the whole knowledge base as one file. Reuse the file row
        # on redelivery rather than inserting a second one and inflating totals.
        file_row_id = await store.find_file(job_id, job.knowledge_base_id)
        if file_row_id is None:
            file_row_id = await store.create_file(job_id, job.knowledge_base_id)
        await store.mark_file_extracted(file_row_id)

        await session.commit()
        await store.mark_job_completed(job_id)
        await store.set_knowledge_base_state(job.knowledge_base_id, _PUBLISHED)
        await session.commit()
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