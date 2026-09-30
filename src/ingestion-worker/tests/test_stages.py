"""Tests for the ADR-0005 stage pipeline (`stages.py`).

Each stage function is Celery-free, so these drive it directly against a
SQLite session and a recording `publish` callable - the same convention as
`test_dispatcher.py`'s `dispatch_queued_jobs` tests. Ontology/entity stages
remain stubs; construct/embed consume pre-extracted JSON from fake storage.
"""

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.config import settings
from common.models.base import Base
from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.node_embedding import NodeEmbedding
from common.schemas.model import AuthMode, Model, ModelType
from common.services import embedding_service
from ingestion_worker.errors import NonRetryableIngestionError
from ingestion_worker.job_store import IndexJobStore
from ingestion_worker.jobs import fail_job
from ingestion_worker.models.base import create_job_tables
from ingestion_worker.models.index_job import IndexJob
from ingestion_worker.stages import (
    CONSTRUCT_GRAPH_TASK_NAME,
    EMBED_NODES_TASK_NAME,
    EXTRACT_ENTITIES_TASK_NAME,
    EXTRACT_ONTOLOGY_TASK_NAME,
    UNPUBLISH_KNOWLEDGE_BASE_TASK_NAME,
    construct_graph,
    embed_nodes,
    entry_task_name,
    extract_entities,
    extract_ontology,
    unpublish_knowledge_base,
)


EMBEDDING_MODEL_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def _embedding_model(monkeypatch):
    model = Model.model_validate(
        {
            "id": EMBEDDING_MODEL_ID,
            "display_name": "Embedding",
            "name": "text-embedding-3-small",
            "provider": "openai",
            "connection_string": "https://api.openai.com/v1",
            "auth_mode": AuthMode.API_KEY,
            "api_key": "test-key",
            "type": [ModelType.EMBEDDING],
            "embedding_dimension": 3,
        }
    )
    monkeypatch.setattr(settings, "models", [model])

    async def fake_aembedding(*, input, **kwargs):
        return SimpleNamespace(
            data=[{"embedding": [0.1, 0.2, 0.3]} for _ in input]
        )

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)


async def _engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: create_job_tables(c, include_knowledge_base=True)
        )
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed_job(
    session,
    *,
    job_id="job-1",
    status="running",
    knowledge_base_id="kb-1",
    embedding_model_id=EMBEDDING_MODEL_ID,
    kind="publish",
    knowledge_base_state="indexing",
):
    """Seed a job, plus its knowledge base unless `knowledge_base_state` is None."""
    now = datetime.now(UTC)
    await session.execute(
        insert(IndexJob).values(
            id=job_id,
            organization_id="org-1",
            knowledge_base_id=knowledge_base_id,
            graph_name="demo_graph",
            kind=kind,
            status=status,
            total_files=0,
            processed_files=0,
            failed_files=0,
            graph_dispatched=False,
            embedding_model_id=embedding_model_id,
            created_at=now,
        )
    )
    from common.models.knowledge_base import KnowledgeBase

    if knowledge_base_state is not None:
        await session.execute(
            KnowledgeBase.__table__.insert().values(
                Id=knowledge_base_id,
                OrganizationId="org-1",
                Name="demo",
                State=knowledge_base_state,
                CreatedAtUtc=now,
                UpdatedAtUtc=now,
            )
        )
    await session.commit()


async def _seed_file(session, *, file_id, storage_key):
    from common.models.file import File

    now = datetime.now(UTC)
    await session.execute(
        File.__table__.insert().values(
            Id=file_id,
            OrganizationId="org-1",
            FileName=f"{file_id}.json",
            ContentType="application/json",
            Size=10,
            StorageKey=storage_key,
            Status="uploaded",
            CreatedAtUtc=now,
            UpdatedAtUtc=now,
        )
    )


def _demo_file_bytes(*, file_kb_id="file-kb-1"):
    return json.dumps(
        {
            "id": file_kb_id,
            "name": "demo",
            "schema": {
                "labels": [
                    {"name": "Driver", "properties": {"name": {"type": "string"}}},
                    {"name": "Team", "properties": {"name": {"type": "string"}}},
                ],
                "relationships": [
                    {"name": "RACED_FOR", "properties": {"season": {"type": "integer"}}}
                ],
                "triplets": [
                    {"source": "Driver", "relationship": "RACED_FOR", "target": "Team"}
                ],
            },
            "nodes": [
                {"id": "d1", "label": "Driver", "properties": {"name": "Max"}},
                {"id": "t1", "label": "Team", "properties": {"name": "Red Bull"}},
            ],
            "relationships": [
                {
                    "source_id": "d1",
                    "target_id": "t1",
                    "label": "RACED_FOR",
                    "properties": {"season": 2024},
                }
            ],
        }
    ).encode("utf-8")


class _RecordingPublisher:
    def __init__(self):
        self.calls: list[tuple[str, list]] = []

    def __call__(self, task_name: str, args: list) -> None:
        self.calls.append((task_name, list(args)))


class _RecordingCache:
    def __init__(self):
        self.calls = []

    async def invalidate_job(self, organization_id, knowledge_base_id, job_id):
        self.calls.append(("job", organization_id, knowledge_base_id, job_id))

    async def invalidate_knowledge_base(
        self, organization_id, knowledge_base_id, *, job_id=None
    ):
        self.calls.append(("knowledge_base", organization_id, knowledge_base_id, job_id))


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self.objects = objects

    async def read_bytes(self, key: str) -> bytes:
        return self.objects[key]

    async def aclose(self) -> None:
        return None


class _FakeRepository:
    def __init__(self):
        self.queries: list[str] = []
        self.graphs: set[str] = {"demo_graph"}

    async def graph_exists(self, graph_name):
        return graph_name in self.graphs

    async def create_graph(self, graph_name):
        self.graphs.add(graph_name)
        query = f"create:{graph_name}"
        self.queries.append(query)
        return query

    async def ensure_vertex_label(self, graph_name, label):
        self.queries.append(f"vlabel:{label}")

    async def ensure_edge_label(self, graph_name, label):
        self.queries.append(f"elabel:{label}")

    async def merge_node(self, graph_name, label, properties, *, knowledge_base_id=None):
        query = f"MERGE (n:{label} {properties})"
        self.queries.append(query)
        return query

    async def merge_relationship(
        self,
        graph_name,
        source_node_id,
        target_node_id,
        label,
        properties,
        *,
        knowledge_base_id=None,
    ):
        query = f"MERGE ({source_node_id})-[:{label}]->({target_node_id})"
        self.queries.append(query)
        return query

    async def release_knowledge_base(self, graph_name, knowledge_base_id):
        query = f"release {knowledge_base_id}"
        self.queries.append(query)
        return [query]

    async def delete_unclaimed_nodes(self, graph_name, node_ids):
        if not node_ids:
            return None
        query = f"unclaimed {','.join(sorted(node_ids))}"
        self.queries.append(query)
        return query

    async def commit(self):
        return None


async def test_full_dag_completes_the_job_and_publishes_the_knowledge_base():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        await _seed_file(session, file_id="file-1", storage_key="k/file-1")
        await _seed_file(session, file_id="file-2", storage_key="k/file-2")
        store = IndexJobStore(session)
        file_1 = await store.create_file("job-1", "file-1")
        file_2 = await store.create_file("job-1", "file-2")
        await session.commit()

        storage = _FakeStorage(
            {"k/file-1": _demo_file_bytes(), "k/file-2": _demo_file_bytes()}
        )
        repository = _FakeRepository()

        publish = _RecordingPublisher()
        cache = _RecordingCache()
        await extract_ontology(session, publish, "job-1")

        entity_calls = [c for c in publish.calls if c[0] == EXTRACT_ENTITIES_TASK_NAME]
        assert sorted(c[1][1] for c in entity_calls) == sorted([file_1, file_2])

        # Walk the fan-out for both files (stubs: no storage reads).
        publish.calls.clear()
        await extract_entities(session, publish, "job-1", file_1, cache=cache)
        assert publish.calls == []  # only one of two files done; no fan-in yet

        await extract_entities(session, publish, "job-1", file_2, cache=cache)
        assert publish.calls == [(CONSTRUCT_GRAPH_TASK_NAME, ["job-1"])]

        publish.calls.clear()
        await construct_graph(session, publish, "job-1", repository=repository, storage=storage)
        assert publish.calls == [(EMBED_NODES_TASK_NAME, ["job-1", "0"])]
        assert any(q.startswith("MERGE (n:Driver") for q in repository.queries)
        schema_rows = (
            await session.execute(select(GraphSchemaRegistry))
        ).scalars().all()
        assert {row.name for row in schema_rows} == {"Driver", "Team", "RACED_FOR"}

        publish.calls.clear()
        await embed_nodes(session, publish, "job-1", "0", cache=cache, storage=storage)
        assert publish.calls == []
        assert cache.calls == [
            ("job", "org-1", "kb-1", "job-1"),
            ("job", "org-1", "kb-1", "job-1"),
            ("knowledge_base", "org-1", "kb-1", "job-1"),
        ]

        node_rows = (await session.execute(select(NodeEmbedding))).scalars().all()
        assert {row.node_id for row in node_rows} == {"d1", "t1"}
        assert all(row.knowledge_base_id == "kb-1" for row in node_rows)

        job = await store.get_job("job-1")
        assert job.status == "completed"
        kb = await store.read_knowledge_base("kb-1")
        assert kb.state == "published"

    await engine.dispose()


async def test_construct_graph_rereads_storage_for_redelivered_embed():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        await _seed_file(session, file_id="file-1", storage_key="k/file-1")
        store = IndexJobStore(session)
        file_1 = await store.create_file("job-1", "file-1")
        await session.commit()
        await extract_entities(session, lambda *a: None, "job-1", file_1)

        storage = _FakeStorage({"k/file-1": _demo_file_bytes()})
        repository = _FakeRepository()
        publish = _RecordingPublisher()
        await construct_graph(session, publish, "job-1", repository=repository, storage=storage)
        assert publish.calls == [(EMBED_NODES_TASK_NAME, ["job-1", "0"])]

        publish.calls.clear()
        await embed_nodes(session, publish, "job-1", "0", storage=storage)
        await embed_nodes(session, publish, "job-1", "0", storage=storage)
        assert publish.calls == []

        job = await store.get_job("job-1")
        assert job.status == "completed"

    await engine.dispose()


async def test_construct_graph_missing_file_object_is_non_retryable():
    from ingestion_worker.errors import NonRetryableIngestionError, classify_exception

    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session)
        store = IndexJobStore(session)
        file_1 = await store.create_file("job-1", "file-1")
        await session.commit()
        await extract_entities(session, lambda *a: None, "job-1", file_1)

        class _MissingStorage:
            async def read_bytes(self, key):
                from common.storage.base import StorageObjectNotFoundError

                raise StorageObjectNotFoundError(key)

        publish = _RecordingPublisher()
        try:
            await construct_graph(
                session,
                publish,
                "job-1",
                repository=_FakeRepository(),
                storage=_MissingStorage(),
            )
        except Exception as exc:
            classified = classify_exception(exc)
            assert isinstance(classified, NonRetryableIngestionError)
        else:
            raise AssertionError("expected construct_graph to fail on missing object")
        assert publish.calls == []

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


@pytest.mark.parametrize("kind", ["publish", "unpublish"])
async def test_fail_job_sets_the_job_and_knowledge_base_to_failed(monkeypatch, kind):
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session, kind=kind)
        await session.commit()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _fake_open_job_resources():
        async with AsyncSession(engine) as session:
            yield session, None

    cache = _RecordingCache()

    @asynccontextmanager
    async def _fake_open_cache_invalidator():
        yield cache

    monkeypatch.setattr(
        "ingestion_worker.db.open_job_resources", _fake_open_job_resources
    )
    monkeypatch.setattr(
        "ingestion_worker.cache.open_cache_invalidator", _fake_open_cache_invalidator
    )

    await fail_job("job-1", "boom")

    async with AsyncSession(engine) as session:
        store = IndexJobStore(session)
        job = await store.get_job("job-1")
        assert job.status == "failed"
        assert job.error == "boom"
        kb = await store.read_knowledge_base("kb-1")
        assert kb.state == "failed"
    assert cache.calls == [("knowledge_base", "org-1", "kb-1", "job-1")]

    await engine.dispose()


async def test_stages_raise_when_organization_has_no_embedding_model():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        await _seed_job(session, embedding_model_id=None)
        await _seed_file(session, file_id="file-1", storage_key="k/file-1")
        await IndexJobStore(session).create_file("job-1", "file-1")
        await session.commit()

        publish = _RecordingPublisher()
        storage = _FakeStorage({"k/file-1": _demo_file_bytes()})
        with pytest.raises(NonRetryableIngestionError, match="no embedding model"):
            await extract_ontology(session, publish, "job-1")
        with pytest.raises(NonRetryableIngestionError, match="no embedding model"):
            await construct_graph(
                session, publish, "job-1", repository=_FakeRepository(), storage=storage
            )
        with pytest.raises(NonRetryableIngestionError, match="no embedding model"):
            await embed_nodes(session, publish, "job-1", "0", storage=storage)
        assert publish.calls == []

    await engine.dispose()


async def _publish_demo_knowledge_base(session, repository):
    """Run a one-file publish job (`job-1`, `kb-1`) through to `published`."""
    await _seed_job(session)
    await _seed_file(session, file_id="file-1", storage_key="k/file-1")
    store = IndexJobStore(session)
    file_1 = await store.create_file("job-1", "file-1")
    await session.commit()

    storage = _FakeStorage({"k/file-1": _demo_file_bytes()})
    ignore = lambda *args: None  # noqa: E731
    await extract_entities(session, ignore, "job-1", file_1)
    await construct_graph(session, ignore, "job-1", repository=repository, storage=storage)
    await embed_nodes(session, ignore, "job-1", "0", storage=storage)
    assert (await store.read_knowledge_base("kb-1")).state == "published"


async def _seed_unpublish_job(session, job_id="job-2"):
    await _seed_job(session, job_id=job_id, kind="unpublish", knowledge_base_state=None)
    await IndexJobStore(session).set_knowledge_base_state("kb-1", "unpublishing")
    await session.commit()


async def test_unpublish_removes_graph_data_and_returns_the_knowledge_base_to_draft():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        repository = _FakeRepository()
        await _publish_demo_knowledge_base(session, repository)
        await _seed_unpublish_job(session)

        repository.queries.clear()
        publish = _RecordingPublisher()
        cache = _RecordingCache()
        await unpublish_knowledge_base(
            session, publish, "job-2", cache=cache, repository=repository
        )

        # The knowledge base's graph claim is released, plus any unstamped nodes.
        assert repository.queries == ["release kb-1", "unclaimed d1,t1"]
        assert (await session.execute(select(NodeEmbedding))).scalars().all() == []
        assert (await session.execute(select(GraphSchemaRegistry))).scalars().all() == []

        store = IndexJobStore(session)
        assert (await store.get_job("job-2")).status == "completed"
        assert (await store.read_knowledge_base("kb-1")).state == "draft"
        assert publish.calls == []
        assert cache.calls == [("knowledge_base", "org-1", "kb-1", "job-2")]

        # A redelivery after completion is a no-op.
        repository.queries.clear()
        cache.calls.clear()
        await unpublish_knowledge_base(
            session, publish, "job-2", cache=cache, repository=repository
        )
        assert repository.queries == []
        assert cache.calls == []

    await engine.dispose()


async def test_unpublish_replay_after_a_partial_failure_finishes_the_job():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        repository = _FakeRepository()
        await _publish_demo_knowledge_base(session, repository)
        await _seed_unpublish_job(session)

        class _FailingSession:
            """Delegates to `session` but fails the stage's commit once."""

            def __getattr__(self, name):
                return getattr(session, name)

            async def commit(self):
                raise RuntimeError("database went away")

        with pytest.raises(RuntimeError):
            await unpublish_knowledge_base(
                _FailingSession(), _RecordingPublisher(), "job-2", repository=repository
            )

        store = IndexJobStore(session)
        assert (await store.get_job("job-2")).status == "running"
        assert len((await session.execute(select(NodeEmbedding))).scalars().all()) == 2

        await unpublish_knowledge_base(
            session, _RecordingPublisher(), "job-2", repository=repository
        )
        assert (await session.execute(select(NodeEmbedding))).scalars().all() == []
        assert (await store.get_job("job-2")).status == "completed"
        assert (await store.read_knowledge_base("kb-1")).state == "draft"

    await engine.dispose()


async def test_unpublish_cleans_side_tables_when_the_graph_does_not_exist():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        repository = _FakeRepository()
        await _publish_demo_knowledge_base(session, repository)
        await _seed_unpublish_job(session)

        repository.graphs.clear()
        repository.queries.clear()
        await unpublish_knowledge_base(
            session, _RecordingPublisher(), "job-2", repository=repository
        )

        assert repository.queries == []
        assert (await session.execute(select(NodeEmbedding))).scalars().all() == []
        assert (await IndexJobStore(session).read_knowledge_base("kb-1")).state == "draft"

    await engine.dispose()


async def test_stages_skip_a_job_of_the_other_kind():
    engine = await _engine()
    async with AsyncSession(engine) as session:
        # An unpublish job has no embedding model; an ingestion stage must skip
        # it rather than fail on the missing model.
        await _seed_job(session, kind="unpublish", embedding_model_id=None)
        await _seed_job(session, job_id="job-publish", knowledge_base_state=None)
        file_1 = await IndexJobStore(session).create_file("job-1", "file-1")
        await session.commit()

        publish = _RecordingPublisher()
        repository = _FakeRepository()
        await extract_ontology(session, publish, "job-1")
        await extract_entities(session, publish, "job-1", file_1)
        await construct_graph(session, publish, "job-1", repository=repository)
        await embed_nodes(session, publish, "job-1", "0")
        await unpublish_knowledge_base(session, publish, "job-publish", repository=repository)

        assert publish.calls == []
        assert repository.queries == []
        store = IndexJobStore(session)
        assert (await store.get_job("job-1")).status == "running"
        assert (await store.get_job("job-publish")).status == "running"

    await engine.dispose()


def test_entry_task_name_maps_each_job_kind():
    assert entry_task_name("publish") == EXTRACT_ONTOLOGY_TASK_NAME
    assert entry_task_name("unpublish") == UNPUBLISH_KNOWLEDGE_BASE_TASK_NAME
    with pytest.raises(ValueError, match="unknown index job kind"):
        entry_task_name("reindex")
