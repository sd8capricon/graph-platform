"""Tests for the worker's ingestion write path (extraction, writer, graph, pipeline)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.models.base import Base
from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.node_embedding import NodeEmbedding
from common.models.schema_embedding import SchemaEmbedding
from common.schemas.graph_schema_registry import GraphSchemaRegistryDTO, SchemaType
from common.schemas.knowledge_base import KnowledgeBase
from common.schemas.model import AuthMode, Model, ModelType
from common.schemas.node_embedding import NodeEmbeddingDTO

from ingestion_worker.ingestion.extraction import (
    graph_schema_registry_records,
    node_embedding_records,
)
from ingestion_worker.ingestion.graph import merge_knowledge_base
from ingestion_worker.ingestion.writer import (
    upsert_node_embeddings,
    upsert_schema_registry,
)
from ingestion_worker.pipeline import ingest_knowledge_base


def _embedding_model(**overrides) -> Model:
    fields = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "display_name": "Text Embedding 3 Small",
        "name": "text-embedding-3-small",
        "provider": "openai",
        "connection_string": "https://api.openai.com/v1",
        "auth_mode": AuthMode.API_KEY,
        "api_key": "test-key",
        "type": [ModelType.EMBEDDING],
        "embedding_dimension": 3,
    }
    fields.update(overrides)
    return Model.model_validate(fields)


async def _session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, AsyncSession(engine)


def _demo_knowledge_base(kb_id: str = "kb-1") -> KnowledgeBase:
    return KnowledgeBase.model_validate(
        {
            "id": kb_id,
            "name": "demo",
            "nodes": [
                {"id": f"{kb_id}-d", "label": "Driver", "properties": {"name": "Max"}},
                {"id": f"{kb_id}-t", "label": "Team", "properties": {"name": "Red Bull"}},
            ],
            "relationships": [
                {
                    "source_id": f"{kb_id}-d",
                    "target_id": f"{kb_id}-t",
                    "label": "DRIVES_FOR",
                    "properties": {"season": 2024},
                }
            ],
        }
    )


class _RecordingRepository:
    """Fake AgeGraphRepository recording the MERGE calls it receives."""

    def __init__(self, graph_exists: bool = True):
        self._graph_exists = graph_exists
        self.queries: list[str] = []
        self.commits = 0

    async def graph_exists(self, graph_name):
        return self._graph_exists

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


class FakeResponse:
    def __init__(self, texts):
        self.data = [{"embedding": [0.1, 0.2, 0.3]} for _ in texts]


def _fake_aembedding(monkeypatch):
    import common.services.embedding_service as embedding_service

    async def fake(**kwargs):
        return FakeResponse(kwargs["input"])

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake)


def test_graph_schema_registry_records_groups_by_label():
    records = graph_schema_registry_records(_demo_knowledge_base(), "graph-1", "org-1")

    assert all(isinstance(record, GraphSchemaRegistryDTO) for record in records)
    by_name = {record.name: record for record in records}
    assert set(by_name) == {"Driver", "Team", "DRIVES_FOR"}
    assert by_name["Driver"].type == SchemaType.NODE
    assert by_name["Driver"].knowledge_base_ids == ["kb-1"]
    assert by_name["Driver"].properties == ["name"]
    assert by_name["DRIVES_FOR"].type == SchemaType.RELATIONSHIP
    assert by_name["DRIVES_FOR"].source_label == "Driver"
    assert by_name["DRIVES_FOR"].target_label == "Team"
    assert by_name["DRIVES_FOR"].properties == ["season"]


def test_graph_schema_registry_records_require_knowledge_base_id():
    import pytest

    kb = _demo_knowledge_base()
    kb.id = None
    with pytest.raises(ValueError, match="id is required"):
        graph_schema_registry_records(kb, "graph-1", "org-1")


def test_node_embedding_records_one_per_node():
    records = node_embedding_records(_demo_knowledge_base(), "graph-1", "org-1")

    assert all(isinstance(record, NodeEmbeddingDTO) for record in records)
    assert {record.node_id for record in records} == {"kb-1-d", "kb-1-t"}
    assert all(record.knowledge_base_id == "kb-1" for record in records)
    assert all(record.graph_name == "graph-1" for record in records)


async def test_upsert_schema_registry_inserts_then_merges_knowledge_base_ids():
    engine, session = await _session()
    async with session:
        first = graph_schema_registry_records(_demo_knowledge_base("kb-1"), "g", "org-1")
        second = graph_schema_registry_records(_demo_knowledge_base("kb-2"), "g", "org-1")
        persisted = await upsert_schema_registry(session, first)
        assert all(isinstance(record, GraphSchemaRegistryDTO) for record in persisted)
        await upsert_schema_registry(session, second)
        await session.commit()

        rows = (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        assert len(rows) == 3
        assert all(sorted(r.knowledge_base_ids) == ["kb-1", "kb-2"] for r in rows)

    await engine.dispose()


async def test_upsert_schema_registry_stamps_provenance_and_stores_embedding(monkeypatch):
    _fake_aembedding(monkeypatch)
    engine, session = await _session()
    model = _embedding_model()
    async with session:
        records = graph_schema_registry_records(_demo_knowledge_base(), "g", "org-1")
        await upsert_schema_registry(session, records, model=model)
        await session.commit()

        children = (await session.execute(select(SchemaEmbedding))).scalars().all()
        assert len(children) == 3
        assert all(child.embedding_model_id == model.id for child in children)
        assert all(child.embedding == [0.1, 0.2, 0.3] for child in children)

    await engine.dispose()


async def test_upsert_node_embeddings_updates_existing_and_stamps_model(monkeypatch):
    _fake_aembedding(monkeypatch)
    engine, session = await _session()
    model = _embedding_model()
    async with session:
        records = node_embedding_records(_demo_knowledge_base(), "g", "org-1")
        persisted = await upsert_node_embeddings(session, records, model=model)
        assert all(isinstance(record, NodeEmbeddingDTO) for record in persisted)
        await session.commit()

        # Re-upserting the same nodes updates, not duplicates.
        records = node_embedding_records(_demo_knowledge_base(), "g", "org-1")
        await upsert_node_embeddings(session, records, model=model)
        await session.commit()

        rows = (await session.execute(select(NodeEmbedding))).scalars().all()
        assert len(rows) == 2
        assert all(row.embedding_model_id == model.id for row in rows)

    await engine.dispose()


async def test_merge_knowledge_base_merges_children_and_commits():
    repository = _RecordingRepository()

    queries = await merge_knowledge_base(repository, _demo_knowledge_base(), "demo_graph")

    assert repository.commits == 1
    assert len(queries) == 3
    assert any(query.startswith("MERGE (n:Driver") for query in queries)
    assert any("DRIVES_FOR" in query for query in queries)


async def test_ingest_knowledge_base_writes_graph_and_both_side_tables():
    engine, session = await _session()
    repository = _RecordingRepository()
    async with session:
        queries = await ingest_knowledge_base(
            session,
            repository,
            _demo_knowledge_base(),
            "demo_graph",
            "org-1",
        )
        await session.commit()

        assert len(queries) == 3
        schema_rows = (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        assert {row.name for row in schema_rows} == {"Driver", "Team", "DRIVES_FOR"}
        node_rows = (await session.execute(select(NodeEmbedding))).scalars().all()
        assert {row.node_id for row in node_rows} == {"kb-1-d", "kb-1-t"}

    await engine.dispose()
