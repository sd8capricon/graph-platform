"""Tests for the ADR-0005 stub stage pipeline (`stages.py`).

Each stage function is Celery-free, so these drive it directly against a
SQLite session and a recording `publish` callable - the same convention as
`test_dispatcher.py`'s `dispatch_queued_jobs` tests.
"""

from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ingestion_worker.job_store import IndexJobStore
from ingestion_worker.jobs import fail_job
from ingestion_worker.models.base import create_job_tables
from ingestion_worker.models.index_job import IndexJob
from ingestion_worker.stages import (
    CONSTRUCT_GRAPH_TASK_NAME,
    EMBED_NODES_TASK_NAME,
    EXTRACT_ENTITIES_TASK_NAME,
    construct_graph,
    embed_nodes,
    extract_entities,
    extract_ontology,
)


async def _engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: create_job_tables(c, include_knowledge_base=True)
        )
    return engine


async def _seed_job(session, *, job_id="job-1", status="running", knowledge_base_id="kb-1"):
    now = datetime.now(UTC)
    await session.execute(
        insert(IndexJob).values(
            id=job_id,
            organization_id="org-1",
            knowledge_base_id=knowledge_base_id,
            graph_name="demo_graph",
            status=status,
            total_files=0,
            processed_files=0,
            failed_files=0,
            graph_dispatched=False,
            created_at=now,
        )
    )
    from common.models.knowledge_base import KnowledgeBase

    await session.execute(
        KnowledgeBase.__table__.insert().values(
            Id=knowledge_base_id,
            OrganizationId="org-1",
            Name="demo",
            State="indexing",
            CreatedAtUtc=now,
            UpdatedAtUtc=now,
        )
    )
    await session.commit()


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, list]] = []

    def __call__(self, task_name: str, args: list) -> None:
        self.calls.append((task_name, list(args)))


async def test_full_dag_completes_the_job_and_publishes_the_knowledge_base():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        store = IndexJobStore(session)
        file_1 = await store.create_file("job-1", "file-1")
        file_2 = await store.create_file("job-1", "file-2")
        await session.commit()

        publish = _RecordingPublisher()
        await extract_ontology(session, publish, "job-1")

        entity_calls = [c for c in publish.calls if c[0] == EXTRACT_ENTITIES_TASK_NAME]
        assert sorted(c[1][1] for c in entity_calls) == sorted([file_1, file_2])

        # Walk the fan-out for both files.
        publish.calls.clear()
        await extract_entities(session, publish, "job-1", file_1)
        assert publish.calls == []  # only one of two files done; no fan-in yet

        await extract_entities(session, publish, "job-1", file_2)
        assert publish.calls == [(CONSTRUCT_GRAPH_TASK_NAME, ["job-1"])]

        publish.calls.clear()
        await construct_graph(session, publish, "job-1")
        assert publish.calls == [(EMBED_NODES_TASK_NAME, ["job-1", "0"])]

        publish.calls.clear()
        await embed_nodes(session, publish, "job-1", "0")
        assert publish.calls == []

        job = await store.get_job("job-1")
        assert job.status == "completed"
        kb = await store.read_knowledge_base("kb-1")
        assert kb.state == "published"

    await engine.dispose()


async def test_redelivered_extract_entities_does_not_double_count_or_republish():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        store = IndexJobStore(session)
        file_1 = await store.create_file("job-1", "file-1")
        await session.commit()

        publish = _RecordingPublisher()
        await extract_entities(session, publish, "job-1", file_1)
        assert publish.calls == [(CONSTRUCT_GRAPH_TASK_NAME, ["job-1"])]

        job = await store.get_job("job-1")
        assert job.processed_files == 1

        # Redelivery of the same file: the file is already terminal, so it must
        # not increment the counter again, but the fan-in claim is still safe
        # to attempt (and this time correctly reports already-claimed).
        publish.calls.clear()
        await extract_entities(session, publish, "job-1", file_1)
        assert publish.calls == []

        job = await store.get_job("job-1")
        assert job.processed_files == 1

    await engine.dispose()


async def test_stage_skips_a_job_that_is_not_running():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session, status="completed")
        store = IndexJobStore(session)
        file_1 = await store.create_file("job-1", "file-1")
        await session.commit()

        publish = _RecordingPublisher()
        await extract_ontology(session, publish, "job-1")
        assert publish.calls == []

        await extract_entities(session, publish, "job-1", file_1)
        assert publish.calls == []

        await construct_graph(session, publish, "job-1")
        assert publish.calls == []

        await embed_nodes(session, publish, "job-1", "0")
        assert publish.calls == []

    await engine.dispose()


async def test_stage_skips_a_missing_job():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        publish = _RecordingPublisher()
        await extract_ontology(session, publish, "does-not-exist")
        assert publish.calls == []

    await engine.dispose()


async def test_fail_job_sets_the_job_and_knowledge_base_to_failed(monkeypatch):
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        await session.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_open_job_resources():
        async with AsyncSession(engine) as session:
            yield session, None

    monkeypatch.setattr(
        "ingestion_worker.db.open_job_resources", _fake_open_job_resources
    )

    await fail_job("job-1", "boom")

    async with AsyncSession(engine) as session:
        store = IndexJobStore(session)
        job = await store.get_job("job-1")
        assert job.status == "failed"
        assert job.error == "boom"
        kb = await store.read_knowledge_base("kb-1")
        assert kb.state == "failed"

    await engine.dispose()
