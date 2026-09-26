"""Celery task wrappers for the ADR-0005 ingestion stage pipeline.

Four thin, synchronous Celery tasks around the async, Celery-free stage
functions in `stages.py`. Celery is synchronous, so each task bridges with
`asyncio.run`. Retry policy lives here: retryable failures use Celery's
exponential backoff with jitter; when retries are exhausted (or a
non-retryable error occurs) the task's `on_failure` hook records the terminal
failure on the job.
"""

import asyncio
import logging

from celery import Task

from ingestion_worker import stages
from ingestion_worker.celery_app import app
from ingestion_worker.config import load_worker_config
from ingestion_worker.errors import RetryableIngestionError
from ingestion_worker.jobs import fail_job, run_stage

logger = logging.getLogger(__name__)

EXTRACT_ONTOLOGY_TASK_NAME = "ingestion_worker.tasks.extract_ontology"
EXTRACT_ENTITIES_TASK_NAME = "ingestion_worker.tasks.extract_entities"
CONSTRUCT_GRAPH_TASK_NAME = "ingestion_worker.tasks.construct_graph"
EMBED_NODES_TASK_NAME = "ingestion_worker.tasks.embed_nodes"

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


def _publish(task_name: str, args: list) -> None:
    app.send_task(task_name, args=args)


@app.task(
    bind=True,
    base=IngestionTask,
    name=EXTRACT_ONTOLOGY_TASK_NAME,
    autoretry_for=(RetryableIngestionError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def extract_ontology(self, job_id: str) -> None:
    """Ontology stage: fan out one `extract_entities` per file."""
    load_worker_config()
    asyncio.run(run_stage(stages.extract_ontology, _publish, job_id))


@app.task(
    bind=True,
    base=IngestionTask,
    name=EXTRACT_ENTITIES_TASK_NAME,
    autoretry_for=(RetryableIngestionError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def extract_entities(self, job_id: str, file_row_id: str) -> None:
    """Entity stage for one file, guarded fan-in into `construct_graph`."""
    load_worker_config()
    asyncio.run(run_stage(stages.extract_entities, _publish, job_id, file_row_id))


@app.task(
    bind=True,
    base=IngestionTask,
    name=CONSTRUCT_GRAPH_TASK_NAME,
    autoretry_for=(RetryableIngestionError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def construct_graph(self, job_id: str) -> None:
    """Graph-construction stage; publishes a single stub embedding batch."""
    load_worker_config()
    asyncio.run(run_stage(stages.construct_graph, _publish, job_id))


@app.task(
    bind=True,
    base=IngestionTask,
    name=EMBED_NODES_TASK_NAME,
    autoretry_for=(RetryableIngestionError,),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=MAX_RETRIES,
)
def embed_nodes(self, job_id: str, batch_id: str) -> None:
    """Embedding stage; completes the job and publishes the knowledge base."""
    load_worker_config()
    asyncio.run(run_stage(stages.embed_nodes, _publish, job_id, batch_id))


__all__ = [
    "extract_ontology",
    "extract_entities",
    "construct_graph",
    "embed_nodes",
    "IngestionTask",
    "EXTRACT_ONTOLOGY_TASK_NAME",
    "EXTRACT_ENTITIES_TASK_NAME",
    "CONSTRUCT_GRAPH_TASK_NAME",
    "EMBED_NODES_TASK_NAME",
]
