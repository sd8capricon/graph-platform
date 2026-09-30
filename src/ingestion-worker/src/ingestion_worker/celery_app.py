"""Celery application and RabbitMQ topology for the ingestion pipeline.

One topic exchange `ingestion` with a routing key per stage into per-stage
queues, plus a retry and dead-letter variant per stage. Each of the four ADR-0005
stage tasks (`extract_ontology`, `extract_entities`, `construct_graph`,
`embed_nodes`) routes to its own `q.<stage>`; the stub stages walk the full
ontology -> per-file entity fan-out -> guarded fan-in graph construction ->
embedding DAG (real extraction/graph work is ADR-0005 Phase 2). The unpublish
task, a graph mutation, shares `q.graph`.

No result backend is configured (`task_ignore_result=True`): all durable state
lives in `index_job`/`index_file` (ADR-0005), so RabbitMQ + Celery + Postgres is
the whole stack.

A crash between a stage's commit and its next-stage publish (see `dispatcher.py`
and `stages.py`) leaves a job durably `running` with nothing to redeliver it;
the `reconciler` module's periodic Beat task redelivers those orphaned jobs.
"""

import os

from celery import Celery, signals
from kombu import Exchange, Queue

from ingestion_worker.config import configure_worker_logging, rabbitmq_url

INGESTION_EXCHANGE = Exchange("ingestion", type="topic")

# Stage -> (queue name, routing key), one per ADR-0005 DAG stage.
STAGES = ("ontology", "entity", "graph", "embedding")

# Default retry delay for the TTL+DLX retry queues (ms). The durable delayed
# retry path is a Phase 2 refinement; Phase 1 uses Celery's in-worker
# `retry_backoff`, and these queues exist so the topology is already in place.
DEFAULT_RETRY_TTL_MS = int(os.environ.get("INGESTION_RETRY_TTL_MS", "30000"))


def _stage_queues(stage: str) -> tuple[Queue, Queue, Queue]:
    main = Queue(
        f"q.{stage}",
        INGESTION_EXCHANGE,
        routing_key=f"ingestion.{stage}",
        durable=True,
    )
    retry = Queue(
        f"q.{stage}.retry",
        INGESTION_EXCHANGE,
        routing_key=f"ingestion.{stage}.retry",
        durable=True,
        queue_arguments={
            "x-dead-letter-exchange": "ingestion",
            "x-dead-letter-routing-key": f"ingestion.{stage}",
            "x-message-ttl": DEFAULT_RETRY_TTL_MS,
        },
    )
    dlq = Queue(
        f"q.{stage}.dlq",
        INGESTION_EXCHANGE,
        routing_key=f"ingestion.{stage}.dlq",
        durable=True,
    )
    return main, retry, dlq


def build_task_queues() -> tuple[Queue, ...]:
    """All per-stage queues: main, retry and dead-letter."""
    queues: list[Queue] = []
    for stage in STAGES:
        queues.extend(_stage_queues(stage))
    return tuple(queues)


app = Celery(
    "ingestion_worker",
    broker=rabbitmq_url(),
    include=[
        "ingestion_worker.tasks",
        "ingestion_worker.dispatcher",
        "ingestion_worker.reconciler",
    ],
)

app.conf.update(
    task_queues=build_task_queues(),
    task_default_exchange="ingestion",
    task_default_exchange_type="topic",
    task_default_queue="q.ontology",
    task_default_routing_key="ingestion.ontology",
    task_routes={
        "ingestion_worker.tasks.extract_ontology": {
            "queue": "q.ontology",
            "routing_key": "ingestion.ontology",
        },
        "ingestion_worker.tasks.extract_entities": {
            "queue": "q.entity",
            "routing_key": "ingestion.entity",
        },
        "ingestion_worker.tasks.construct_graph": {
            "queue": "q.graph",
            "routing_key": "ingestion.graph",
        },
        "ingestion_worker.tasks.embed_nodes": {
            "queue": "q.embedding",
            "routing_key": "ingestion.embedding",
        },
        # Unpublishing is a graph mutation; sharing q.graph keeps the worker's
        # `-Q` list unchanged.
        "ingestion_worker.tasks.unpublish_knowledge_base": {
            "queue": "q.graph",
            "routing_key": "ingestion.graph",
        },
        "ingestion_worker.dispatcher.dispatch_queued_jobs": {
            "queue": "q.ontology",
            "routing_key": "ingestion.ontology",
        },
        "ingestion_worker.reconciler.reconcile_stale_jobs": {
            "queue": "q.ontology",
            "routing_key": "ingestion.ontology",
        },
    },
    # At-least-once: ack only after success, redeliver if the worker dies.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # No result backend needed - the job tables are the source of truth.
    task_ignore_result=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    # RabbitMQ 4.x removed the "transient_nonexcl_queues" deprecated feature
    # that kombu's default pidbox reply queue (auto_delete, non-exclusive)
    # relies on; declaring it exclusive instead avoids Queue.declare errors.
    control_queue_exclusive=True,
    # Same deprecated feature also breaks the gossip/events receiver queue
    # (celery.events.Receiver), which defaults to the same non-exclusive,
    # auto_delete combination.
    event_queue_exclusive=True,
    beat_schedule={
        "dispatch-queued-jobs": {
            "task": "ingestion_worker.dispatcher.dispatch_queued_jobs",
            "schedule": float(os.environ.get("INGESTION_DISPATCH_INTERVAL_SECONDS", "5")),
        },
        "reconcile-stale-jobs": {
            "task": "ingestion_worker.reconciler.reconcile_stale_jobs",
            "schedule": float(os.environ.get("INGESTION_RECONCILE_INTERVAL_SECONDS", "300")),
        },
    },
)


@signals.setup_logging.connect
def setup_worker_logging(**_kwargs) -> None:
    """Configure logging from `ingestion_worker.logging` in the YAML config.

    Connecting this receiver makes Celery skip its own logging setup for both
    `worker` and `beat`, so the YAML - not `--loglevel` - is authoritative.
    Prefork pool children inherit the configuration.
    """
    configure_worker_logging()


__all__ = ["app", "INGESTION_EXCHANGE", "STAGES", "build_task_queues", "setup_worker_logging"]