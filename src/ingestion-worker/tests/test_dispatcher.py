"""Tests for the dispatcher's claim-then-publish behaviour."""

from datetime import UTC, datetime

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ingestion_worker.dispatcher import dispatch_queued_jobs
from ingestion_worker.job_store import IndexJobStore
from ingestion_worker.models.base import create_job_tables
from ingestion_worker.models.index_job import IndexJob


async def _engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: create_job_tables(c, include_knowledge_base=True)
        )
    return engine


async def _insert_job(session, job_id, status="queued"):
    await session.execute(
        insert(IndexJob).values(
            id=job_id,
            organization_id="org-1",
            knowledge_base_id=f"kb-{job_id}",
            graph_name="demo_graph",
            status=status,
            total_files=0,
            processed_files=0,
            failed_files=0,
            graph_dispatched=False,
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()


async def test_dispatch_claims_queued_jobs_marks_running_and_publishes():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _insert_job(session, "job-1")
        await _insert_job(session, "job-2")
        await _insert_job(session, "job-done", status="completed")

        published: list[str] = []
        dispatched = await dispatch_queued_jobs(session, published.append)

        assert sorted(dispatched) == ["job-1", "job-2"]
        assert sorted(published) == ["job-1", "job-2"]

    # The claim is committed before publish, so a fresh session sees running.
    async with AsyncSession(engine) as session:
        store = IndexJobStore(session)
        assert (await store.get_job("job-1")).status == "running"
        assert (await store.get_job("job-2")).status == "running"
        assert (await store.get_job("job-done")).status == "completed"

    await engine.dispose()


async def test_dispatch_returns_empty_when_nothing_is_queued():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        published: list[str] = []
        assert await dispatch_queued_jobs(session, published.append) == []
        assert published == []

    await engine.dispose()


async def test_dispatch_honours_the_batch_limit():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        for index in range(3):
            await _insert_job(session, f"job-{index}")

        published: list[str] = []
        dispatched = await dispatch_queued_jobs(session, published.append, limit=2)

        assert len(dispatched) == 2
        assert len(published) == 2

    await engine.dispose()
