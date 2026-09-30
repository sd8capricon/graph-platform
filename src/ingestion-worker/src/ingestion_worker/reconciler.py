"""Reconciler: redelivers the next-stage message for orphaned running jobs.

Every ADR-0005 stage commits its state before publishing the next Celery
message (see `dispatcher.py` and `stages.py`). A crash in that gap leaves a
job durably `running` with no in-flight task and nothing to redeliver it.
This runs as a Celery Beat periodic task, on a longer interval than the
dispatcher, and re-publishes an idempotent entry point for any job whose
`started_at` predates the staleness cutoff. For a publish job:

- not yet `graph_dispatched` -> republish `extract_ontology`, which re-fans-out
  only non-terminal files and is a no-op for files already `extracted`.
- already `graph_dispatched` -> republish `construct_graph`, whose upserts are
  idempotent and which ends by republishing `embed_nodes` (itself a no-op once
  the job is `completed`).

An unpublish job republishes `unpublish_knowledge_base`, which re-reads the
knowledge base's remaining embedding rows and deletes only what is left.

Known limitation: there is no per-job "last activity" timestamp, only
`started_at`, so a job still legitimately mid-retry-backoff can be redelivered
redundantly on every reconcile tick until it finishes. Harmless given the
idempotency above, but worth noting so it isn't mistaken for a bug. A future
refinement would add a `last_progress_at` column to skip jobs still actively
advancing.
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from ingestion_worker.celery_app import app
from ingestion_worker.config import load_worker_config

logger = logging.getLogger(__name__)

RECONCILE_TASK_NAME = "ingestion_worker.reconciler.reconcile_stale_jobs"
DEFAULT_BATCH = 10
DEFAULT_STALE_AFTER_SECONDS = int(os.environ.get("INGESTION_RECONCILE_STALE_SECONDS", "900"))


async def reconcile_stale_jobs(
    session, publish, *, stale_after_seconds: int, limit: int = DEFAULT_BATCH
) -> list[str]:
    """Redeliver the next-stage message for jobs stuck `running` past the cutoff.

    `publish(job_id, kind, graph_dispatched)` is injected so this is testable
    without a broker, matching `dispatcher.dispatch_queued_jobs`'s shape.
    """
    from ingestion_worker.job_store import IndexJobStore

    store = IndexJobStore(session)
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    stale = await store.find_stale_running_jobs(cutoff, limit)

    for job_id, kind, graph_dispatched in stale:
        publish(job_id, kind, graph_dispatched)
    return [job_id for job_id, _, _ in stale]


def _publish(job_id: str, kind: str, graph_dispatched: bool) -> None:
    from ingestion_worker.job_store import JOB_KIND_PUBLISH
    from ingestion_worker.stages import CONSTRUCT_GRAPH_TASK_NAME, entry_task_name

    if kind == JOB_KIND_PUBLISH and graph_dispatched:
        app.send_task(CONSTRUCT_GRAPH_TASK_NAME, args=[job_id])
    else:
        app.send_task(entry_task_name(kind), args=[job_id])


@app.task(name=RECONCILE_TASK_NAME)
def reconcile_task() -> int:
    """Beat entrypoint: open resources, reconcile a batch, return the count."""
    load_worker_config()

    async def _run() -> int:
        from ingestion_worker.db import open_job_resources

        async with open_job_resources() as (session, _repository):
            job_ids = await reconcile_stale_jobs(
                session, _publish, stale_after_seconds=DEFAULT_STALE_AFTER_SECONDS
            )
            logger.info("reconciled %d stale ingestion job(s)", len(job_ids))
            return len(job_ids)

    return asyncio.run(_run())


__all__ = [
    "reconcile_stale_jobs",
    "reconcile_task",
    "RECONCILE_TASK_NAME",
    "DEFAULT_STALE_AFTER_SECONDS",
]
