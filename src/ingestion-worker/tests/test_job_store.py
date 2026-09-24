"""Tests for the ingestion job-state store (ADR-0005)."""

from datetime import UTC, datetime

from sqlalchemy import insert
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.models.knowledge_base import KnowledgeBase
from common.schemas.knowledge_base import KnowledgeBaseRecordDTO

from ingestion_worker.job_store import (
    JOB_COMPLETED,
    JOB_RUNNING,
    IndexJobStore,
)
from ingestion_worker.models.base import create_job_tables
from ingestion_worker.models.index_job import IndexJob

knowledge_base = KnowledgeBase.__table__


async def _store_engine(**kwargs):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: create_job_tables(c, include_knowledge_base=True)
        )
    return engine


async def _insert_job(session, **overrides):
    values = {
        "id": "job-1",
        "organization_id": "org-1",
        "knowledge_base_id": "kb-1",
        "graph_name": "demo_graph",
        "status": "queued",
        "total_files": 0,
        "processed_files": 0,
        "failed_files": 0,
        "graph_dispatched": False,
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    await session.execute(insert(IndexJob).values(**values))
    await session.commit()


async def test_claim_and_run_transitions_are_guarded():
    engine = await _store_engine()
    async with AsyncSession(engine) as session:
        await _insert_job(session)
        store = IndexJobStore(session)

        assert await store.claim_queued_jobs() == ["job-1"]
        assert await store.mark_job_running("job-1") is True
        # A redelivered claim must not transition an already-running job.
        assert await store.mark_job_running("job-1") is False

        job = await store.get_job("job-1")
        assert job is not None
        assert job.status == JOB_RUNNING

    await engine.dispose()


async def test_create_file_increments_total_and_fan_in_claims_once():
    engine = await _store_engine()
    async with AsyncSession(engine) as session:
        await _insert_job(session)
        store = IndexJobStore(session)

        file_row_id = await store.create_file("job-1", "kb-1")
        job = await store.get_job("job-1")
        assert job.total_files == 1

        await store.mark_file_extracted(file_row_id)
        assert await store.increment_and_check_fan_in("job-1") is True
        # The one-shot gate must never fire twice.
        assert await store.increment_and_check_fan_in("job-1") is False
        await session.commit()

    await engine.dispose()


async def test_mark_job_completed_sets_processed_from_total():
    engine = await _store_engine()
    async with AsyncSession(engine) as session:
        await _insert_job(session, total_files=2)
        store = IndexJobStore(session)

        await store.mark_job_completed("job-1")
        job = await store.get_job("job-1")
        assert job.status == JOB_COMPLETED
        assert job.processed_files == 2
        assert job.completed_at is not None

    await engine.dispose()


async def test_read_and_set_knowledge_base_state():
    engine = await _store_engine()
    now = datetime.now(UTC)
    async with AsyncSession(engine) as session:
        await session.execute(
            knowledge_base.insert().values(
                Id="kb-1",
                OrganizationId="org-1",
                Name="F1",
                Data='{"nodes": []}',
                State="indexing",
                CreatedAtUtc=now,
                UpdatedAtUtc=now,
            )
        )
        await session.commit()

        store = IndexJobStore(session)
        kb = await store.read_knowledge_base("kb-1")
        assert kb is not None
        assert isinstance(kb, KnowledgeBaseRecordDTO)
        assert kb.name == "F1"
        assert kb.organization_id == "org-1"
        assert kb.data == '{"nodes": []}'

        await store.set_knowledge_base_state("kb-1", "published")
        kb = await store.read_knowledge_base("kb-1")
        assert kb.state == "published"

    await engine.dispose()


class _FakeResult:
    def scalars(self):
        return self

    def all(self):
        return []


class _CapturingSession:
    def __init__(self):
        self.stmt = None

    async def execute(self, stmt):
        self.stmt = stmt
        return _FakeResult()


async def test_claim_compiles_to_for_update_skip_locked_on_postgres():
    session = _CapturingSession()
    await IndexJobStore(session).claim_queued_jobs()

    compiled = str(session.stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE SKIP LOCKED" in compiled
    assert "index_job.status = " in compiled
