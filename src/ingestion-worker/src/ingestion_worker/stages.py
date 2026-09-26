"""ADR-0005 stage stubs: the ontology -> per-file entity fan-out -> guarded
fan-in graph construction -> embedding DAG, with no real extraction/graph work
yet (that is ADR-0005 Phase 2).

Celery-free, like `dispatcher.dispatch_queued_jobs`: each function takes a
`session` and an injected `publish(task_name, args)` callable, and commits
before publishing - the same convention, and the same documented reconciler
gap (a crash between commit and publish leaves state durable but the next
stage never enqueued). Each stage skips a missing job, or one that isn't
`running` (already completed/failed/redelivered after terminal state).
"""

import logging

from ingestion_worker.job_store import (
    FILE_TERMINAL_STATUSES,
    JOB_RUNNING,
    KB_PUBLISHED,
    IndexJobStore,
)

logger = logging.getLogger(__name__)

EXTRACT_ONTOLOGY_TASK_NAME = "ingestion_worker.tasks.extract_ontology"
EXTRACT_ENTITIES_TASK_NAME = "ingestion_worker.tasks.extract_entities"
CONSTRUCT_GRAPH_TASK_NAME = "ingestion_worker.tasks.construct_graph"
EMBED_NODES_TASK_NAME = "ingestion_worker.tasks.embed_nodes"


async def extract_ontology(session, publish, job_id: str, *, cache=None) -> None:
    """Stub ontology stage: fan out one `extract_entities` per non-terminal file."""
    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info("extract_ontology: job %s missing or not running; skipping", job_id)
        return

    # TODO(ADR-0005 Phase 2): extract real ontology/schema from the KB's files.
    logger.info("extract_ontology stub running for job %s", job_id)

    files = await store.list_files(job_id)
    pending = [f for f in files if f.status not in FILE_TERMINAL_STATUSES]
    await session.commit()

    for file_row in pending:
        publish(EXTRACT_ENTITIES_TASK_NAME, [job_id, file_row.id])


async def extract_entities(
    session, publish, job_id: str, file_row_id: str, *, cache=None
) -> None:
    """Stub entity stage for one file: complete it, then attempt the fan-in claim.

    Only counts this file toward the fan-in when `complete_file` reports it
    actually performed the `pending`/`extracting` -> `extracted` transition, so
    a redelivery of the same (job_id, file_row_id) can't double-count. The
    fan-in claim is always attempted regardless, since a previous crash could
    have incremented the counter without publishing `construct_graph`.
    """
    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info(
            "extract_entities: job %s missing or not running; skipping", job_id
        )
        return

    # TODO(ADR-0005 Phase 2): real entity extraction for this file.
    logger.info(
        "extract_entities stub running for job %s file %s", job_id, file_row_id
    )

    transitioned = await store.complete_file(file_row_id)
    if transitioned:
        await store.record_file_done(job_id)
    claimed = await store.claim_graph_dispatch(job_id)
    await session.commit()

    if transitioned and cache is not None:
        await cache.invalidate_job(
            job.organization_id, job.knowledge_base_id, job.id
        )

    if claimed:
        publish(CONSTRUCT_GRAPH_TASK_NAME, [job_id])


async def construct_graph(session, publish, job_id: str, *, cache=None) -> None:
    """Stub graph-construction stage: publish a single stub embedding batch."""
    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info("construct_graph: job %s missing or not running; skipping", job_id)
        return

    # TODO(ADR-0005 Phase 2): real graph construction (MERGE nodes/relationships).
    logger.info("construct_graph stub running for job %s", job_id)
    await session.commit()

    publish(EMBED_NODES_TASK_NAME, [job_id, "0"])


async def embed_nodes(session, publish, job_id: str, batch_id: str, *, cache=None) -> None:
    """Stub embedding stage: complete the job and publish the knowledge base.

    Guarded by `mark_job_completed`'s own `running -> completed` transition, so
    a redelivered batch neither re-completes the job nor re-publishes the
    knowledge base's state.
    """
    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info("embed_nodes: job %s missing or not running; skipping", job_id)
        return

    # TODO(ADR-0005 Phase 2): real embedding computation for this batch.
    logger.info("embed_nodes stub running for job %s batch %s", job_id, batch_id)

    completed = await store.mark_job_completed(job_id)
    if completed:
        await store.set_knowledge_base_state(job.knowledge_base_id, KB_PUBLISHED)
    await session.commit()

    if completed and cache is not None:
        await cache.invalidate_knowledge_base(
            job.organization_id, job.knowledge_base_id, job_id=job.id
        )


__all__ = [
    "extract_ontology",
    "extract_entities",
    "construct_graph",
    "embed_nodes",
    "EXTRACT_ONTOLOGY_TASK_NAME",
    "EXTRACT_ENTITIES_TASK_NAME",
    "CONSTRUCT_GRAPH_TASK_NAME",
    "EMBED_NODES_TASK_NAME",
]
