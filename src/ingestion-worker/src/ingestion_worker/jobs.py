"""Async orchestration glue for the ADR-0005 stage pipeline.

`run_stage` opens the worker's real DB resources (mirroring the old `run_job`)
and calls one Celery-free stage function from `stages.py`, so the Celery task
wrappers in `tasks.py` stay thin translators of errors into retry/DLQ policy.
`fail_job` records a terminal failure once a task's retries are exhausted.
"""

from ingestion_worker.job_store import KB_FAILED, IndexJobStore


async def fail_job(job_id: str, error: str) -> None:
    """Record a terminal failure on a job and its knowledge base.

    Called from the Celery task's `on_failure` hook once retries are exhausted.
    Opens its own short-lived session/resources.
    """
    from ingestion_worker.db import open_job_resources

    async with open_job_resources() as (session, _repository):
        store = IndexJobStore(session)
        job = await store.get_job(job_id)
        await store.mark_job_failed(job_id, error)
        if job is not None:
            await store.set_knowledge_base_state(job.knowledge_base_id, KB_FAILED)
        await session.commit()


async def run_stage(fn, publish, *args) -> None:
    """Open the worker's DB resources and run one stage function.

    `fn` is one of `stages.py`'s Celery-free stage coroutines, called as
    `fn(session, publish, *args)`. This is the Celery entrypoint each task in
    `tasks.py` awaits via `asyncio.run`.
    """
    from ingestion_worker.db import open_job_resources

    async with open_job_resources() as (session, _repository):
        await fn(session, publish, *args)


__all__ = ["fail_job", "run_stage"]
