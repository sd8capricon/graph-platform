"""Tests for the async job orchestration (worker's `jobs.ingest_job`)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.models.base import Base
from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.knowledge_base import KnowledgeBase as KnowledgeBaseRecord
from common.models.node_embedding import NodeEmbedding
from common.schemas.knowledge_base import KnowledgeBase

from ingestion_worker.errors import NonRetryableIngestionError
from ingestion_worker.job_store import IndexJobStore
from ingestion_worker.jobs import ingest_job
from ingestion_worker.models.base import create_job_tables
from ingestion_worker.models.index_file import IndexFile
from ingestion_worker.models.index_job import IndexJob

knowledge_base = KnowledgeBaseRecord.__table__


def _demo_knowledge_base(kb_id: str = "kb-1") -> KnowledgeBase:
    return KnowledgeBase.model_validate(
        {
            "id": kb_id,
            "name": "demo",
            "nodes": [
                {"id": f"{kb_id}-d", "label": "Driver", "properties": {"name": "Max"}},
            ],
            "relationships": [],
        }
    )


class _RecordingRepository:
    def __init__(self, graph_exists: bool = True):
        self._graph_exists = graph_exists
        self.queries: list[str] = []
        self.commits = 0

    async def graph_exists(self, graph_name):
        return self._graph_exists

    async def create_graph(self, graph_name):
        self._graph_exists = True
        query = f"create_graph:{graph_name}"
        self.queries.append(query)
        return query

    async def ensure_vertex_label(self, graph_name, label):
        self.queries.append(f"vlabel:{label}")

    async def ensure_edge_label(self, graph_name, label):
        self.queries.append(f"elabel:{label}")

    async def merge_node(self, graph_name, label, properties):
        query = f"MERGE (n:{label} {properties})"
        self.queries.append(query)
        return query

    async def merge_relationship(
        self, graph_name, source_node_id, target_node_id, label, properties
    ):
        query = f"MERGE ({source_node_id})-[:{label}]->({target_node_id})"
        self.queries.append(query)
        return query

    async def commit(self):
        self.commits += 1


async def _engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(
            lambda c: create_job_tables(c, include_knowledge_base=True)
        )
    return engine


async def _seed_job(session, *, knowledge_base_id="kb-1", job_id="job-1"):
    now = datetime.now(UTC)
    await session.execute(
        knowledge_base.insert().values(
            Id=knowledge_base_id,
            OrganizationId="org-1",
            Name="demo",
            Data=_demo_knowledge_base(knowledge_base_id).model_dump_json(),
            State="indexing",
            CreatedAtUtc=now,
            UpdatedAtUtc=now,
        )
    )
    await session.execute(
        insert(IndexJob).values(
            id=job_id,
            organization_id="org-1",
            knowledge_base_id=knowledge_base_id,
            graph_name="demo_graph",
            status="queued",
            total_files=0,
            processed_files=0,
            failed_files=0,
            graph_dispatched=False,
            created_at=now,
        )
    )
    await session.commit()


async def test_ingest_job_completes_and_publishes_the_knowledge_base():
    engine = await _engine()
    repository = _RecordingRepository()
    async with AsyncSession(engine) as session:
        await _seed_job(session)

        await ingest_job("job-1", session, repository)

        store = IndexJobStore(session)
        job = await store.get_job("job-1")
        assert job is not None
        assert job.status == "completed"
        assert job.processed_files == 1

        kb = await store.read_knowledge_base("kb-1")
        assert kb is not None
        assert kb.state == "published"

        file_rows = (await session.execute(select(IndexFile))).scalars().all()
        assert len(file_rows) == 1
        assert file_rows[0].status == "extracted"

        assert len((await session.execute(select(GraphSchemaRegistry))).scalars().all()) == 1
        assert len((await session.execute(select(NodeEmbedding))).scalars().all()) == 1

    await engine.dispose()


async def test_ingest_job_reuses_file_row_and_skips_when_completed():
    engine = await _engine()
    repository = _RecordingRepository()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        await ingest_job("job-1", session, repository)
        commits_after_first = repository.commits

        # A redelivered task must be a no-op, not a second ingestion.
        await ingest_job("job-1", session, repository)

        assert repository.commits == commits_after_first
        file_rows = (await session.execute(select(IndexFile))).scalars().all()
        assert len(file_rows) == 1

    await engine.dispose()


async def test_ingest_job_creates_the_graph_when_missing():
    engine = await _engine()
    repository = _RecordingRepository(graph_exists=False)
    async with AsyncSession(engine) as session:
        await _seed_job(session)

        await ingest_job("job-1", session, repository)

        assert "create_graph:demo_graph" in repository.queries

    await engine.dispose()


async def test_ingest_job_raises_non_retryable_when_knowledge_base_missing():
    engine = await _engine()
    repository = _RecordingRepository()
    async with AsyncSession(engine) as session:
        now = datetime.now(UTC)
        await session.execute(
            insert(IndexJob).values(
                id="job-1",
                organization_id="org-1",
                knowledge_base_id="missing",
                graph_name="demo_graph",
                status="queued",
                total_files=0,
                processed_files=0,
                failed_files=0,
                graph_dispatched=False,
                created_at=now,
            )
        )
        await session.commit()

        with pytest.raises(NonRetryableIngestionError):
            await ingest_job("job-1", session, repository)

    await engine.dispose()


async def test_ingest_job_is_a_no_op_for_a_missing_job():
    engine = await _engine()
    repository = _RecordingRepository()
    async with AsyncSession(engine) as session:
        await ingest_job("does-not-exist", session, repository)
        assert repository.queries == []

    await engine.dispose()
