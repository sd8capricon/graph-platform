"""Celery application and RabbitMQ topology for the ingestion pipeline.

One topic exchange `ingestion` with a routing key per stage into per-stage
queues, plus a retry and dead-letter variant per stage. Phase 1 routes its single
combined task to `q.ontology`; the other stage queues are declared now so the
Phase 2 fan-out does not require a broker-topology change.

No result backend is configured (`task_ignore_result=True`): all durable state
lives in `index_job`/`index_file` (ADR-0005), so RabbitMQ + Celery + Postgres is
the whole stack.
"""

import os

from celery import Celery
from kombu import Exchange, Queue

from ingestion_worker.config import rabbitmq_url

INGESTION_EXCHANGE = Exchange("ingestion", type="topic")

# Stage -> (queue name, routing key). Phase 1 uses ontology; the rest are
# declared for the Phase 2 fan-out/fan-in.
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
    ],
)

app.conf.update(
    task_queues=build_task_queues(),
    task_default_exchange="ingestion",
    task_default_exchange_type="topic",
    task_default_queue="q.ontology",
    task_default_routing_key="ingestion.ontology",
    task_routes={
        "ingestion_worker.tasks.ingest_knowledge_base": {
            "queue": "q.ontology",
            "routing_key": "ingestion.ontology",
        },
        "ingestion_worker.dispatcher.dispatch_queued_jobs": {
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
    beat_schedule={
        "dispatch-queued-jobs": {
            "task": "ingestion_worker.dispatcher.dispatch_queued_jobs",
            "schedule": float(os.environ.get("INGESTION_DISPATCH_INTERVAL_SECONDS", "5")),
        }
    },
)


__all__ = ["app", "INGESTION_EXCHANGE", "STAGES", "build_task_queues"]