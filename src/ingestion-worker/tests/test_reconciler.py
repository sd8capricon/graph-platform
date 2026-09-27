"""Tests for the reconciler's stale-job redelivery behaviour."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from ingestion_worker.job_store import IndexJobStore
from ingestion_worker.models.base import create_job_tables
from ingestion_worker.models.index_job import IndexJob
from ingestion_worker.reconciler import reconcile_stale_jobs


async def _engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: create_job_tables(c, include_knowledge_base=True)
        )
    return engine


async def _insert_job(session, job_id, *, started_at, status="running", graph_dispatched=False):
    await session.execute(
        insert(IndexJob).values(
            id=job_id,
            organization_id="org-1",
            knowledge_base_id=f"kb-{job_id}",
            graph_name="demo_graph",
            status=status,
            total_files=1,
            processed_files=0,
            failed_files=0,
            graph_dispatched=graph_dispatched,
            created_at=started_at,
            started_at=started_at,
        )
    )
    await session.commit()


async def test_reconcile_republishes_ontology_for_stale_not_dispatched_job():
    engine = await _engine()
    now = datetime.now(UTC)
    async with AsyncSession(engine) as session:
        await _insert_job(session, "stale-1", started_at=now - timedelta(seconds=1000))

        published: list[tuple[str, bool]] = []
        job_ids = await reconcile_stale_jobs(
            session, lambda job_id, dispatched: published.append((job_id, dispatched)),
            stale_after_seconds=900,
        )

        assert job_ids == ["stale-1"]
        assert published == [("stale-1", False)]

    await engine.dispose()


async def test_reconcile_republishes_construct_graph_for_stale_dispatched_job():
    engine = await _engine()
    now = datetime.now(UTC)
    async with AsyncSession(engine) as session:
        await _insert_job(
            session, "stale-2", started_at=now - timedelta(seconds=1000), graph_dispatched=True
        )

        published: list[tuple[str, bool]] = []
        job_ids = await reconcile_stale_jobs(
            session, lambda job_id, dispatched: published.append((job_id, dispatched)),
            stale_after_seconds=900,
        )

        assert job_ids == ["stale-2"]
        assert published == [("stale-2", True)]

    await engine.dispose()


async def test_reconcile_ignores_fresh_and_non_running_jobs():
    engine = await _engine()
    now = datetime.now(UTC)
    async with AsyncSession(engine) as session:
        await _insert_job(session, "fresh", started_at=now - timedelta(seconds=10))
        await _insert_job(
            session, "stale-completed", started_at=now - timedelta(seconds=1000), status="completed"
        )

        published: list[tuple[str, bool]] = []
        job_ids = await reconcile_stale_jobs(
            session, lambda job_id, dispatched: published.append((job_id, dispatched)),
            stale_after_seconds=900,
        )

        assert job_ids == []
        assert published == []

    await engine.dispose()


async def test_reconcile_honours_the_batch_limit():
    engine = await _engine()
    now = datetime.now(UTC)
    async with AsyncSession(engine) as session:
        for index in range(3):
            await _insert_job(session, f"stale-{index}", started_at=now - timedelta(seconds=1000))

        published: list[tuple[str, bool]] = []
        job_ids = await reconcile_stale_jobs(
            session, lambda job_id, dispatched: published.append((job_id, dispatched)),
            stale_after_seconds=900,
            limit=2,
        )

        assert len(job_ids) == 2
        assert len(published) == 2

    await engine.dispose()
