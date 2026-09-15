from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateTable

from common.models.base import Base
from common.models.node_embedding import NodeEmbedding
from common.schemas.knowledge_base import KnowledgeBase
from common.schemas.model import AuthMode, Model, ModelType
from common.services.knowledge_base_service import KnowledgeBaseService


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


def test_node_embedding_column_is_dimensionless():
    """Per ADR-0003 the column is `vector`, not `vector(n)`, so organizations on
    embedding models of different widths can share the table. Asserted on the
    compiled PostgreSQL DDL because SQLite never uses the pgvector type at all
    (it falls back to JSON via with_variant), so the width is invisible there."""
    ddl = str(CreateTable(NodeEmbedding.__table__).compile(dialect=postgresql.dialect()))

    assert "embedding VECTOR," in ddl or ddl.rstrip().endswith("embedding VECTOR")
    assert "VECTOR(" not in ddl


def test_node_embedding_table_exists_and_tracks_graph_and_node():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "node_embedding" in inspector.get_table_names()

    columns = {column["name"] for column in inspector.get_columns("node_embedding")}
    expected = {
        "id",
        "organization_id",
        "graph_name",
        "knowledge_base_id",
        "node_id",
        "label",
        "properties",
        "embedding_model_id",
        "embedding",
    }
    assert expected.issubset(columns)


def test_node_embedding_round_trips_on_sqlite():
    # The embedding column uses a JSON fallback on SQLite (via with_variant),
    # since pgvector's Vector type only compiles on PostgreSQL.
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    record = NodeEmbedding(
        organization_id="org-1",
        graph_name="demo",
        knowledge_base_id="kb-1",
        node_id="node-1",
        label="Driver",
        properties={"name": "Max Verstappen"},
        embedding=[0.1, 0.2, 0.3],
    )

    with Session(engine) as session:
        session.add(record)
        session.commit()

        stored = session.execute(
            select(NodeEmbedding).where(NodeEmbedding.node_id == "node-1")
        ).scalar_one()

    assert stored.embedding == [0.1, 0.2, 0.3]


async def test_upsert_node_embeddings_skips_embedding_when_model_not_provided():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    record = NodeEmbedding(
        organization_id="org-1",
        graph_name="demo",
        knowledge_base_id="kb-1",
        node_id="node-1",
        label="Driver",
        properties={},
    )

    async with AsyncSession(engine) as session:
        persisted = await NodeEmbedding.upsert_records(session, [record])
        embedding = persisted[0].embedding
        embedding_model_id = persisted[0].embedding_model_id
        await session.commit()

    assert embedding is None
    assert embedding_model_id is None


async def test_upsert_node_embeddings_computes_embedding_via_litellm_when_configured(
    monkeypatch,
):
    import common.services.embedding_service as embedding_service

    captured = {}

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}]

    async def fake_aembedding(**kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    record = NodeEmbedding(
        organization_id="org-1",
        graph_name="demo",
        knowledge_base_id="kb-1",
        node_id="node-1",
        label="Driver",
        properties={"name": "Max Verstappen"},
    )

    async with AsyncSession(engine) as session:
        persisted = await NodeEmbedding.upsert_records(
            session, [record], model=_embedding_model()
        )
        embedding = persisted[0].embedding
        embedding_model_id = persisted[0].embedding_model_id
        await session.commit()

    assert embedding == [0.1, 0.2, 0.3]
    assert embedding_model_id == "550e8400-e29b-41d4-a716-446655440000"
    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["input"] == ["Driver name: Max Verstappen"]


async def test_upsert_node_embeddings_updates_existing_record_for_same_node():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        await NodeEmbedding.upsert_records(
            session,
            [
                NodeEmbedding(
                    organization_id="org-1",
                    graph_name="demo",
                    knowledge_base_id="kb-1",
                    node_id="node-1",
                    label="Driver",
                    properties={"name": "Max"},
                )
            ],
        )
        await session.commit()

        await NodeEmbedding.upsert_records(
            session,
            [
                NodeEmbedding(
                    organization_id="org-1",
                    graph_name="demo",
                    knowledge_base_id="kb-1",
                    node_id="node-1",
                    label="Driver",
                    properties={"name": "Max Verstappen"},
                )
            ],
        )
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(NodeEmbedding).where(NodeEmbedding.node_id == "node-1")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].properties == {"name": "Max Verstappen"}
    assert rows[0].knowledge_base_id == "kb-1"


async def test_vector_search_embeds_query_and_builds_cosine_distance_statement(monkeypatch):
    # vector_search relies on pgvector's `<=>` cosine distance operator, which
    # only exists on PostgreSQL, so we capture the statement it builds via a
    # fake session instead of executing it against SQLite.
    import common.services.embedding_service as embedding_service

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}]

    async def fake_aembedding(**kwargs):
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    captured = {}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return FakeResult()

    results = await NodeEmbedding.vector_search(
        FakeSession(),
        query="fast driver",
        graph_name="demo",
        organization_id="org-1",
        model=_embedding_model(),
        labels=["Driver"],
        limit=3,
    )

    assert results == []
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "<=>" in compiled
    assert "node_embedding.graph_name" in compiled
    assert "node_embedding.organization_id" in compiled
    assert "LIMIT" in compiled


async def test_vector_search_filters_by_multiple_labels_when_provided(monkeypatch):
    import common.services.embedding_service as embedding_service

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}]

    async def fake_aembedding(**kwargs):
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    captured = {}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return FakeResult()

    results = await NodeEmbedding.vector_search(
        FakeSession(),
        query="fast driver",
        graph_name="demo",
        organization_id="org-1",
        model=_embedding_model(),
        labels=["Driver", "Team"],
        limit=3,
    )

    assert results == []
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "node_embedding.label IN" in compiled


async def test_vector_search_scopes_to_the_query_model_without_being_asked(monkeypatch):
    """The `embedding_model_id` predicate and the `::vector(n)` cast are derived
    from the `model` argument, not passed separately (ADR-0003). Together they
    keep a search inside one model's vector space *and* make the partial
    expression index (see `database/indexes.py`) matchable."""
    import common.services.embedding_service as embedding_service

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}]

    async def fake_aembedding(**kwargs):
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    captured = {}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return FakeResult()

    # Note: no embedding_model_id= and no dimension argument.
    results = await NodeEmbedding.vector_search(
        FakeSession(),
        query="fast driver",
        graph_name="demo",
        organization_id="org-1",
        model=_embedding_model(),
        limit=3,
    )

    assert results == []
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "node_embedding.embedding_model_id" in compiled
    assert "CAST(node_embedding.embedding AS VECTOR(3))" in compiled


async def test_vector_search_raises_when_model_is_not_an_embedding_model():
    """A chat-only Model has no embedding_dimension, so there is no width to cast
    to - catch that at the boundary rather than emitting a no-op cast."""
    model = _embedding_model()
    object.__setattr__(model, "embedding_dimension", None)

    class FakeSession:
        async def execute(self, stmt):
            raise AssertionError("should not query the database")

    with pytest.raises(ValueError, match="has no embedding_dimension"):
        await NodeEmbedding.vector_search(
            FakeSession(),
            query="fast driver",
            graph_name="demo",
            organization_id="org-1",
            model=model,
        )


async def test_vector_search_raises_when_model_not_provided():
    class FakeSession:
        async def execute(self, stmt):
            raise AssertionError("should not query the database without an embedding")

    with pytest.raises(ValueError, match="model is required"):
        await NodeEmbedding.vector_search(
            FakeSession(),
            query="fast driver",
            graph_name="demo",
            organization_id="org-1",
            model=None,
        )


def test_knowledge_base_extracts_one_node_embedding_record_per_node():
    payload_path = Path(__file__).resolve().parents[1] / "dummy_data" / "f1_kb.json"
    knowledge_base = KnowledgeBase.model_validate_json(payload_path.read_text())

    assert knowledge_base.id == "b7c9e1a4-3f28-4d65-9e07-1a2b3c4d5e6f"

    records = knowledge_base.get_node_embedding_records("F1 kb", "org-1")

    assert len(records) == len(knowledge_base.nodes)
    assert all(record.graph_name == "F1 kb" for record in records)
    assert all(record.organization_id == "org-1" for record in records)
    assert all(record.knowledge_base_id == knowledge_base.id for record in records)
    node_ids = {node.id for node in knowledge_base.nodes}
    assert {record.node_id for record in records} == node_ids


async def test_knowledge_base_service_upserts_node_embeddings():
    knowledge_base = KnowledgeBase.model_validate(
        {
            "name": "demo_kb",
            "nodes": [
                {
                    "id": "node-1",
                    "label": "Driver",
                    "properties": {"name": "Max Verstappen"},
                },
            ],
        }
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    service = KnowledgeBaseService(repository=None)

    async with AsyncSession(engine) as session:
        persisted = await service.upsert_node_embeddings(
            session, knowledge_base, "demo_kb", "org-1"
        )
        assert len(persisted) == 1
        assert persisted[0].node_id == "node-1"
        assert persisted[0].organization_id == "org-1"
        assert persisted[0].knowledge_base_id == knowledge_base.id
        await session.commit()


async def test_knowledge_base_service_raises_error_if_graph_name_not_provided_for_embeddings():
    knowledge_base = KnowledgeBase.model_validate(
        {"name": "demo_kb", "nodes": [{"label": "Driver"}]}
    )
    service = KnowledgeBaseService(repository=None)

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.upsert_node_embeddings(None, knowledge_base, "", "org-1")


async def test_upsert_node_embeddings_keeps_separate_rows_per_knowledge_base():
    # The same node_id may legitimately be contributed by more than one knowledge
    # base feeding the same graph; knowledge_base_id is part of the row identity
    # so each knowledge base's node embedding is stored separately.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def _node(knowledge_base_id: str) -> NodeEmbedding:
        return NodeEmbedding(
            organization_id="org-1",
            graph_name="demo",
            knowledge_base_id=knowledge_base_id,
            node_id="node-1",
            label="Driver",
            properties={"name": "Max Verstappen"},
        )

    async with AsyncSession(engine) as session:
        await NodeEmbedding.upsert_records(session, [_node("kb-a")])
        await session.commit()

        await NodeEmbedding.upsert_records(session, [_node("kb-b")])
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(NodeEmbedding).where(NodeEmbedding.node_id == "node-1")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    assert {row.knowledge_base_id for row in rows} == {"kb-a", "kb-b"}


async def test_upsert_node_embeddings_keeps_separate_rows_per_organization():
    # organization_id is part of the row identity too: two organizations
    # contributing the same node_id/graph_name/knowledge_base_id combination
    # (e.g. both feeding a shared demo graph) must not collide into one row.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def _node(organization_id: str) -> NodeEmbedding:
        return NodeEmbedding(
            organization_id=organization_id,
            graph_name="demo",
            knowledge_base_id="kb-1",
            node_id="node-1",
            label="Driver",
            properties={"name": "Max Verstappen"},
        )

    async with AsyncSession(engine) as session:
        await NodeEmbedding.upsert_records(session, [_node("org-1")])
        await session.commit()

        await NodeEmbedding.upsert_records(session, [_node("org-2")])
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(NodeEmbedding).where(NodeEmbedding.node_id == "node-1")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 2
    assert {row.organization_id for row in rows} == {"org-1", "org-2"}


async def test_vector_search_filters_by_knowledge_base_id_when_provided(monkeypatch):
    import common.services.embedding_service as embedding_service

    class FakeResponse:
        data = [{"embedding": [0.1, 0.2, 0.3]}]

    async def fake_aembedding(**kwargs):
        return FakeResponse()

    monkeypatch.setattr(embedding_service.litellm, "aembedding", fake_aembedding)

    captured = {}

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class FakeSession:
        async def execute(self, stmt):
            captured["stmt"] = stmt
            return FakeResult()

    results = await NodeEmbedding.vector_search(
        FakeSession(),
        query="fast driver",
        graph_name="demo",
        organization_id="org-1",
        model=_embedding_model(),
        knowledge_base_id="kb-a",
        limit=3,
    )

    assert results == []
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "node_embedding.knowledge_base_id" in compiled


def test_get_node_embedding_records_requires_knowledge_base_id():
    knowledge_base = KnowledgeBase.model_validate(
        {"id": None, "name": "demo_kb", "nodes": [{"label": "Driver"}]}
    )

    with pytest.raises(ValueError, match="id is required"):
        knowledge_base.get_node_embedding_records("demo", "org-1")


def test_get_node_embedding_records_requires_organization_id():
    knowledge_base = KnowledgeBase.model_validate(
        {"name": "demo_kb", "nodes": [{"label": "Driver"}]}
    )

    with pytest.raises(ValueError, match="organization_id is required"):
        knowledge_base.get_node_embedding_records("demo", "")


async def test_knowledge_base_service_raises_error_if_knowledge_base_id_missing():
    knowledge_base = KnowledgeBase.model_validate(
        {"id": None, "name": "demo_kb", "nodes": [{"label": "Driver"}]}
    )
    service = KnowledgeBaseService(repository=None)

    with pytest.raises(ValueError, match="id is required"):
        await service.upsert_node_embeddings(None, knowledge_base, "demo", "org-1")
