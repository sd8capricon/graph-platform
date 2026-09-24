"""Tests for the Celery app configuration and RabbitMQ topology."""

from ingestion_worker.celery_app import STAGES, app, build_task_queues
from ingestion_worker.dispatcher import DISPATCH_TASK_NAME
from ingestion_worker.tasks import INGEST_TASK_NAME


def test_acknowledgement_and_no_result_backend():
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True
    assert app.conf.worker_prefetch_multiplier == 1
    assert app.conf.task_ignore_result is True
    assert app.conf.result_backend in (None, "")


def test_per_stage_queues_including_retry_and_dlq():
    names = {queue.name for queue in build_task_queues()}
    for stage in STAGES:
        assert f"q.{stage}" in names
        assert f"q.{stage}.retry" in names
        assert f"q.{stage}.dlq" in names


def test_ingest_task_routes_to_the_ontology_queue():
    route = app.conf.task_routes[INGEST_TASK_NAME]
    assert route["queue"] == "q.ontology"
    assert route["routing_key"] == "ingestion.ontology"


def test_beat_schedules_the_dispatcher():
    assert "dispatch-queued-jobs" in app.conf.beat_schedule
    schedule = app.conf.beat_schedule["dispatch-queued-jobs"]
    assert schedule["task"] == DISPATCH_TASK_NAME
    assert schedule["schedule"] > 0
