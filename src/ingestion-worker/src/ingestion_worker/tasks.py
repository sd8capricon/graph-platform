"""Celery task wrappers for the ingestion pipeline.

Thin, synchronous Celery tasks around the async `jobs` module. Celery is
synchronous, so each task bridges with `asyncio.run`. Retry policy lives here:
retryable failures use Celery's exponential backoff with jitter; when retries
are exhausted (or a non-retryable error occurs) the task's `on_failure` hook
records the terminal failure on the job.
"""

import asyncio
import logging

from celery import Task

from ingestion_worker.celery_app import app
from ingestion_worker.config import load_worker_config
from ingestion_worker.errors import RetryableIngestionError
from ingestion_worker.jobs import fail_job, run_job

logger = logging.getLogger(__name__)

INGEST_TASK_NAME = "ingestion_worker.tasks.ingest_knowledge_base"
MAX_RETRIES = 5


class IngestionTask(Task):
    """Task base that records a terminal failure on the job row."""

    acks_late = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        job_id = args[0] if args else None
        if not job_id:
            return
        try:
            asyncio.run(fail_job(str(job_id), str(exc)))
        except Exception:  # noqa: BLE001 - never mask the original failure
            logger.exception("could not record failure for job %s", job_id)


@app.task(
    bind=True,
    base=IngestionTask,
    name=INGEST_TASK_NAME,
    autoretry_for=(RetryableIngestionError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def ingest_knowledge_base(self, job_id: str) -> None:
    """Run one indexing job, retrying transient failures with backoff."""
    load_worker_config()
    asyncio.run(run_job(job_id))


__all__ = ["ingest_knowledge_base", "IngestionTask", "INGEST_TASK_NAME"]