"""The dispatcher: claims queued jobs and publishes the first-stage task.

Runs as a Celery Beat periodic task. The first-stage task depends on the job's
`kind`: `extract_ontology` for a publish, `unpublish_knowledge_base` for an
unpublish (see `stages.entry_task_name`). Claiming uses `FOR UPDATE SKIP LOCKED`
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


async def dispatch_queued_jobs(
    session, publish, *, limit: int = DEFAULT_BATCH, cache=None
) -> list[str]:
    """Claim queued jobs, mark them running, commit, then publish each.

    Commit-before-publish: once the guarded transition is durable the job cannot
    be claimed again, so a crash between commit and publish leaves the job
    `running` (visible for the future reconciler) rather than lost.

    `publish` is a callable taking a job id and its kind - injected so this is
    testable without a broker.
    """
    from ingestion_worker.job_store import IndexJobStore

    store = IndexJobStore(session)
    job_ids = await store.claim_queued_jobs(limit)
    jobs = []
    for job_id in job_ids:
        job = await store.get_job(job_id)
        if job is not None:
            jobs.append(job)
        await store.mark_job_running(job_id)
    await session.commit()

    if cache is not None:
        for job in jobs:
            await cache.invalidate_job(
                job.organization_id, job.knowledge_base_id, job.id
            )

    for job in jobs:
        publish(job.id, job.kind)
    return job_ids


def _publish(job_id: str, kind: str) -> None:
    from ingestion_worker.stages import entry_task_name

    app.send_task(entry_task_name(kind), args=[job_id])


@app.task(name=DISPATCH_TASK_NAME)
def dispatch_task() -> int:
    """Beat entrypoint: open resources, dispatch a batch, return the count."""
    load_worker_config()

    async def _run() -> int:
        from ingestion_worker.cache import open_cache_invalidator
        from ingestion_worker.db import open_job_resources

        async with open_cache_invalidator() as cache:
            async with open_job_resources() as (session, _repository):
                job_ids = await dispatch_queued_jobs(session, _publish, cache=cache)
                logger.info("dispatched %d queued ingestion job(s)", len(job_ids))
                return len(job_ids)

    return asyncio.run(_run())


__all__ = ["dispatch_queued_jobs", "dispatch_task", "DISPATCH_TASK_NAME"]
