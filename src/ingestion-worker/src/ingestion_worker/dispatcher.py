"""The dispatcher: claims queued jobs and publishes the first-stage task.

Runs as a Celery Beat periodic task. Claiming uses `FOR UPDATE SKIP LOCKED`
(see `ingestion_worker.job_store.IndexJobStore.claim_queued_jobs`) and a guarded
`queued -> running` transition, so two dispatchers racing, or a dispatcher that
crashes and restarts, never start a second pipeline for the same job. The API
never calls a worker; this row-claim plus RabbitMQ is the async boundary.
"""

import asyncio
import logging

from celery import shared_task

from ingestion_worker.celery_app import app
from ingestion_worker.config import load_worker_config

logger = logging.getLogger(__name__)

DISPATCH_TASK_NAME = "ingestion_worker.dispatcher.dispatch_queued_jobs"
DEFAULT_BATCH = 10


async def dispatch_queued_jobs(session, publish, *, limit: int = DEFAULT_BATCH) -> list[str]:
    """Claim queued jobs, mark them running, commit, then publish each.

    Commit-before-publish: once the guarded transition is durable the job cannot
    be claimed again, so a crash between commit and publish leaves the job
    `running` (visible for the future reconciler) rather than lost.

    `publish` is a callable taking a job id - injected so this is testable
    without a broker.
    """
    from ingestion_worker.job_store import IndexJobStore

    store = IndexJobStore(session)
    job_ids = await store.claim_queued_jobs(limit)
    for job_id in job_ids:
        await store.mark_job_running(job_id)
    await session.commit()

    for job_id in job_ids:
        publish(job_id)
    return job_ids


def _publish(job_id: str) -> None:
    from ingestion_worker.tasks import INGEST_TASK_NAME

    app.send_task(INGEST_TASK_NAME, args=[job_id])


@app.task(name=DISPATCH_TASK_NAME)
def dispatch_task() -> int:
    """Beat entrypoint: open resources, dispatch a batch, return the count."""
    load_worker_config()

    async def _run() -> int:
        from ingestion_worker.db import open_job_resources

        async with open_job_resources() as (session, _repository):
            job_ids = await dispatch_queued_jobs(session, _publish)
            logger.info("dispatched %d queued ingestion job(s)", len(job_ids))
            return len(job_ids)

    return asyncio.run(_run())


__all__ = ["dispatch_queued_jobs", "dispatch_task", "DISPATCH_TASK_NAME"]