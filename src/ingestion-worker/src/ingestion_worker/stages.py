"""ADR-0005 stages: stub extraction fan-out/in plus real graph/embedding writes.

Ontology extraction (``extract_ontology``) and per-file entity extraction
(``extract_entities``) remain stubs: the uploaded JSON already contains the
complete schema, nodes/entities and relationships, so those stages only advance
the ``index_file``/``index_job`` counters and preserve the fan-out/fan-in shape
for a future real extractor. They perform no storage reads and no parsing.

``construct_graph`` and ``embed_nodes`` consume the pre-extracted components
directly from each file's JSON in object storage (see
``ingestion_worker.ingestion.payload``): the temporary ``schema`` block builds
registry rows, ``nodes``/``relationships`` build the graph and node embeddings.
A single malformed file fails the whole job (partial-failure policy is still
ADR-0005 Q4); transient provider/storage errors are classified by
``jobs.run_stage`` into retries.

Celery-free, like `dispatcher.dispatch_queued_jobs`: each function takes a
`session` and an injected `publish(task_name, args)` callable, and commits
before publishing - the same convention, and the same documented reconciler
gap (a crash between commit and publish leaves state durable but the next
stage never enqueued). Each stage skips a missing job, or one that isn't
`running` (already completed/failed/redelivered after terminal state).
"""

import logging

from ingestion_worker.ingestion.payload import (
    UploadedKbFile,
    parse_uploaded_file,
    to_knowledge_base,
    to_node_embedding_records,
    to_schema_registry_records,
)
from ingestion_worker.job_store import (
    FILE_TERMINAL_STATUSES,
    JOB_RUNNING,
    KB_PUBLISHED,
    IndexJobRow,
    IndexJobStore,
)

logger = logging.getLogger(__name__)

EXTRACT_ONTOLOGY_TASK_NAME = "ingestion_worker.tasks.extract_ontology"
EXTRACT_ENTITIES_TASK_NAME = "ingestion_worker.tasks.extract_entities"
CONSTRUCT_GRAPH_TASK_NAME = "ingestion_worker.tasks.construct_graph"
EMBED_NODES_TASK_NAME = "ingestion_worker.tasks.embed_nodes"


async def extract_ontology(
    session, publish, job_id: str, *, cache=None, repository=None, storage=None
) -> None:
    """Stub ontology stage: fan out one `extract_entities` per non-terminal file.

    Intentionally reads no file content: schema arrives pre-extracted in the
    upload and is consumed by `construct_graph`.
    """
    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info("extract_ontology: job %s missing or not running; skipping", job_id)
        return

    logger.info("extract_ontology stub running for job %s", job_id)

    files = await store.list_files(job_id)
    pending = [f for f in files if f.status not in FILE_TERMINAL_STATUSES]
    await session.commit()

    for file_row in pending:
        publish(EXTRACT_ENTITIES_TASK_NAME, [job_id, file_row.id])


async def extract_entities(
    session,
    publish,
    job_id: str,
    file_row_id: str,
    *,
    cache=None,
    repository=None,
    storage=None,
) -> None:
    """Stub entity stage for one file: complete it, then attempt the fan-in claim.

    Only counts this file toward the fan-in when `complete_file` reports it
    actually performed the `pending`/`extracting` -> `extracted` transition, so
    a redelivery of the same (job_id, file_row_id) can't double-count. The
    fan-in claim is always attempted regardless, since a previous crash could
    have incremented the counter without publishing `construct_graph`.

    Intentionally parses no entities: they arrive pre-extracted in the upload
    and are consumed by `construct_graph`/`embed_nodes`.
    """
    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info(
            "extract_entities: job %s missing or not running; skipping", job_id
        )
        return

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


async def _load_envelopes(store: IndexJobStore, storage, job: IndexJobRow) -> list[UploadedKbFile]:
    """Read and parse every file of a job from object storage.

    Raises:
        ValueError: On a missing `File` row, unreadable bytes, or malformed
            JSON. Permanent input failures; `run_stage` classifies them as
            non-retryable.
    """
    files = await store.list_files(job.id)
    envelopes: list[UploadedKbFile] = []
    for file_row in sorted(files, key=lambda row: row.id):
        key = await store.get_file_storage_key(file_row.file_id, job.organization_id)
        if key is None:
            raise ValueError(
                f"file {file_row.file_id!r} for job {job.id!r} has no stored object"
            )
        raw = await storage.read_bytes(key)
        envelopes.append(parse_uploaded_file(raw))
    return envelopes


async def construct_graph(
    session, publish, job_id: str, *, cache=None, repository=None, storage=None
) -> None:
    """Merge pre-extracted nodes/relationships and upsert the temp schema block."""
    from common.services.knowledge_base_service import KnowledgeBaseService

    from ingestion_worker.config import embedding_model_for_job
    from ingestion_worker.ingestion.graph import merge_knowledge_base
    from ingestion_worker.ingestion.writer import upsert_schema_registry

    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info("construct_graph: job %s missing or not running; skipping", job_id)
        return
    if repository is None:
        raise ValueError("construct_graph requires a graph repository")
    if storage is None:
        raise ValueError("construct_graph requires object storage")

    logger.info("construct_graph running for job %s", job_id)
    try:
        model = embedding_model_for_job(job.embedding_model_id)
        envelopes = await _load_envelopes(store, storage, job)

        kb_record = await store.read_knowledge_base(job.knowledge_base_id)
        kb_name = kb_record.name if kb_record is not None else job.knowledge_base_id

        await KnowledgeBaseService(repository).create_graph(job.graph_name)
        for envelope in envelopes:
            if envelope.id and envelope.id != job.knowledge_base_id:
                logger.warning(
                    "construct_graph job %s: file kb id %r overridden by job kb id %r",
                    job_id,
                    envelope.id,
                    job.knowledge_base_id,
                )
            knowledge_base = to_knowledge_base(envelope, job.knowledge_base_id, kb_name)
            await merge_knowledge_base(repository, knowledge_base, job.graph_name)

        schema_records = []
        for envelope in envelopes:
            schema_records.extend(
                to_schema_registry_records(
                    envelope, job.graph_name, job.organization_id, job.knowledge_base_id
                )
            )
        if schema_records:
            await upsert_schema_registry(session, schema_records, model=model)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - rollback is best-effort before re-raise
            logger.debug("construct_graph rollback failed for job %s", job_id, exc_info=True)
        raise

    publish(EMBED_NODES_TASK_NAME, [job_id, "0"])


async def embed_nodes(
    session, publish, job_id: str, batch_id: str, *, cache=None, repository=None, storage=None
) -> None:
    """Upsert node embeddings from pre-extracted nodes, then complete the job.

    Guarded by `mark_job_completed`'s own `running -> completed` transition, so
    a redelivered batch neither re-completes the job nor re-publishes the
    knowledge base's state.
    """
    from ingestion_worker.config import embedding_model_for_job
    from ingestion_worker.ingestion.writer import upsert_node_embeddings

    store = IndexJobStore(session)
    job = await store.get_job(job_id)
    if job is None or job.status != JOB_RUNNING:
        logger.info("embed_nodes: job %s missing or not running; skipping", job_id)
        return
    if storage is None:
        raise ValueError("embed_nodes requires object storage")

    logger.info("embed_nodes running for job %s batch %s", job_id, batch_id)
    try:
        model = embedding_model_for_job(job.embedding_model_id)
        envelopes = await _load_envelopes(store, storage, job)
        records = []
        for envelope in envelopes:
            records.extend(
                to_node_embedding_records(
                    envelope, job.graph_name, job.organization_id, job.knowledge_base_id
                )
            )
        if records:
            await upsert_node_embeddings(session, records, model=model)

        completed = await store.mark_job_completed(job_id)
        if completed:
            await store.set_knowledge_base_state(job.knowledge_base_id, KB_PUBLISHED)
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 - rollback is best-effort before re-raise
            logger.debug("embed_nodes rollback failed for job %s", job_id, exc_info=True)
        raise

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
