import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from graphrag_apacheage.models.base import Base
from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry, SchemaType
from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase
from graphrag_apacheage.schemas.model import AuthMode, Model, ModelType


def _embedding_model(**overrides) -> Model:
    fields = {
        "id": "text-embedding-3-small",
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


def test_graph_registry_table_exists_and_tracks_graph_name():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "graph_registry" in inspector.get_table_names()

    columns = {column["name"] for column in inspector.get_columns("graph_registry")}
    expected = {
        "id",
        "organization_id",
        "graph_name",
        "knowledge_base_ids",
        "type",
        "name",
        "description",
        "aliases",
        "properties",
        "source_label",
        "target_label",
    }
    assert expected.issubset(columns)


async def test_upsert_records_skips_embedding_when_model_not_provided():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    record = GraphSchemaRegistry(
        organization_id="org-1",
        graph_name="demo",
        knowledge_base_ids=["kb-1"],
        type=SchemaType.NODE,
        name="Driver",
        description="A racer",
        aliases=[],
        properties=[],
    )

    async with AsyncSession(engine) as session:
        persisted = await GraphSchemaRegistry.upsert_records(session, [record])
        embedding_row = persisted[0].embedding_row
        await session.commit()

    assert embedding_row is None


async def test_upsert_records_computes_embedding_via_litellm_when_configured(monkeypatch):
    import graphrag_apacheage.services.embedding_service as embedding_service

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

    record = GraphSchemaRegistry(
        organization_id="org-1",
        graph_name="demo",
        knowledge_base_ids=["kb-1"],
        type=SchemaType.NODE,
        name="Driver",
        description="A racer",
        aliases=["Racer"],
        properties=[],
    )

    async with AsyncSession(engine) as session:
        persisted = await GraphSchemaRegistry.upsert_records(
            session, [record], model=_embedding_model()
        )
        embedding = persisted[0].embedding_row.embedding
        embedding_model_id = persisted[0].embedding_row.embedding_model_id
        await session.commit()

    assert embedding == [0.1, 0.2, 0.3]
    assert embedding_model_id == "text-embedding-3-small"
    assert captured["model"] == "openai/text-embedding-3-small"
    assert captured["input"] == ["Driver A racer Racer"]


async def test_vector_search_embeds_query_and_builds_cosine_distance_statement(monkeypatch):
    # vector_search relies on pgvector's `<=>` cosine distance operator, which
    # only exists on PostgreSQL, so we capture the statement it builds via a
    # fake session instead of executing it against SQLite.
    import graphrag_apacheage.services.embedding_service as embedding_service

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

    results = await GraphSchemaRegistry.vector_search(
        FakeSession(),
        query="fast driver",
        graph_name="demo",
        organization_id="org-1",
        model=_embedding_model(),
        type=SchemaType.NODE,
        top_k=3,
    )

    assert results == []
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "<=>" in compiled
    assert "JOIN schema_embedding" in compiled
    assert "graph_registry.graph_name" in compiled
    assert "graph_registry.organization_id" in compiled
    assert "schema_embedding.organization_id" in compiled
    assert "LIMIT" in compiled
    # Derived from the `model` argument, not passed in (ADR-0003): together the
    # predicate and the cast keep the search inside one model's vector space and
    # make the partial expression index matchable.
    assert "schema_embedding.embedding_model_id" in compiled
    assert "CAST(schema_embedding.embedding AS VECTOR(3))" in compiled


async def test_vector_search_filters_by_knowledge_base_ids(monkeypatch):
    # Same rationale as the test above: the `?|` jsonb overlap operator only
    # exists on PostgreSQL, so we capture the statement via a fake session.
    import graphrag_apacheage.services.embedding_service as embedding_service

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

    results = await GraphSchemaRegistry.vector_search(
        FakeSession(),
        query="fast driver",
        graph_name="demo",
        organization_id="org-1",
        model=_embedding_model(),
        knowledge_base_ids=["kb-1", "kb-2"],
        top_k=3,
    )

    assert results == []
    compiled = str(captured["stmt"].compile(dialect=postgresql.dialect()))
    assert "?|" in compiled
    assert "graph_registry.knowledge_base_ids" in compiled


async def test_vector_search_raises_when_model_not_provided():
    class FakeSession:
        async def execute(self, stmt):
            raise AssertionError("should not query the database without an embedding")

    with pytest.raises(ValueError, match="model is required"):
        await GraphSchemaRegistry.vector_search(
            FakeSession(),
            query="fast driver",
            graph_name="demo",
            organization_id="org-1",
            model=None,
        )


def test_graph_registry_type_accepts_only_node_or_relationship():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_registry "
                "(organization_id, graph_name, knowledge_base_ids, type, name, description, aliases, properties) "
                "VALUES ('org-1', 'demo', '[\"kb-1\"]', 'node', 'Demo Node', 'Example', '[]', '[]')"
            )
        )

    with engine.begin() as conn:
        with pytest.raises(IntegrityError, match="ck_graph_registry_type"):
            conn.execute(
                text(
                    "INSERT INTO graph_registry "
                    "(organization_id, graph_name, knowledge_base_ids, type, name, description, aliases, properties) "
                    "VALUES ('org-1', 'demo', '[\"kb-1\"]', 'edge', 'Bad Node', 'Example', '[]', '[]')"
                )
            )


def test_missing_ids_are_uuid_generated_and_existing_ids_are_preserved():
    node = KnowledgeBase.model_validate(
        {
            "name": "demo",
            "nodes": [{"label": "Driver", "properties": {"name": "Alice"}}],
            "relationships": [{"label": "RACED_FOR", "properties": {"season": 2025}}],
        }
    ).nodes[0]
    assert node.id is not None
    assert len(node.id) > 0

    relationship = KnowledgeBase.model_validate(
        {
            "name": "demo",
            "nodes": [{"id": "node-1", "label": "Driver"}],
            "relationships": [
                {"source_id": "node-1", "target_id": "node-2", "label": "RACED_FOR"}
            ],
        }
    ).relationships[0]
    assert relationship.source_id == "node-1"
    assert relationship.target_id == "node-2"


async def test_knowledge_base_parses_json_and_upserts_registry_rows():
    payload_path = Path(__file__).resolve().parents[1] / "dummy_data" / "f1_kb.json"
    knowledge_base = KnowledgeBase.model_validate_json(payload_path.read_text())

    # Pass graph_name to the method instead of storing it on model
    node_records = knowledge_base.get_graph_schema_registry_records("F1 kb", "org-1")
    assert any(
        record.type == SchemaType.NODE and record.name == "Driver"
        for record in node_records
    )
    assert any(
        record.type == SchemaType.RELATIONSHIP and record.name == "RACED_FOR"
        for record in node_records
    )

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        await GraphSchemaRegistry.upsert_records(session, node_records)
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(GraphSchemaRegistry).where(
                        GraphSchemaRegistry.graph_name == "F1 kb"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert any(row.type == SchemaType.NODE and row.name == "Driver" for row in rows)
    assert any(
        row.type == SchemaType.RELATIONSHIP and row.name == "RACED_FOR" for row in rows
    )

    driver_row = next(
        row for row in rows if row.type == SchemaType.NODE and row.name == "Driver"
    )
    assert driver_row.knowledge_base_ids == [knowledge_base.id]


def test_knowledge_base_graph_name_is_provided_to_service_not_stored():
    knowledge_base = KnowledgeBase.model_validate(
        {
            "name": "custom_kb",
            "nodes": [{"label": "Driver", "properties": {"name": "Alice"}}],
        }
    )

    # graph_name is not stored on model, only passed to methods
    assert knowledge_base.name == "custom_kb"

    records = knowledge_base.get_graph_schema_registry_records(
        "shared_age_graph", "org-1"
    )
    assert records[0].graph_name == "shared_age_graph"
    assert records[0].organization_id == "org-1"
    assert records[0].knowledge_base_ids == [knowledge_base.id]


async def test_knowledge_base_service_raises_error_if_graph_name_not_provided():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

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

    class DummyRepository:
        pass

    service = KnowledgeBaseService(DummyRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        # graph_name is a mandatory parameter; an empty value should still raise ValueError
        await service.upsert_knowledge_base(None, knowledge_base, "", "org-1")


async def test_knowledge_base_service_raises_error_if_graph_does_not_exist():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

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

    class MockRepository:
        async def graph_exists(self, graph_name):
            return False  # Graph does not exist

    service = KnowledgeBaseService(MockRepository())

    with pytest.raises(ValueError, match="does not exist in the database"):
        await service.upsert_knowledge_base(
            None, knowledge_base, graph_name="nonexistent_graph", organization_id="org-1"
        )


async def test_knowledge_base_can_write_nodes_and_relationships_to_age_graph():
    knowledge_base = KnowledgeBase.model_validate(
        {
            "name": "demo_kb",
            "nodes": [
                {
                    "id": "node-1",
                    "label": "Driver",
                    "properties": {"name": "Max Verstappen"},
                },
                {
                    "id": "node-2",
                    "label": "Team",
                    "properties": {"name": "Red Bull"},
                },
            ],
            "relationships": [
                {
                    "source_id": "node-1",
                    "target_id": "node-2",
                    "label": "DRIVES_FOR",
                    "properties": {"season": 2025},
                }
            ],
        }
    )

    class RecordingCursor:
        def __init__(self):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, params=None):
            self.calls.append((query, params))

    class RecordingConnection:
        def __init__(self):
            self.cursor_obj = RecordingCursor()

        def cursor(self):
            return self.cursor_obj

    connection = RecordingConnection()
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    class RecordingRepository:
        def __init__(self, connection):
            self.connection = connection

        async def graph_exists(self, graph_name):
            return True  # Mock graph exists

        async def create_graph(self, graph_name):
            query = f"SELECT * FROM ag_catalog.create_graph('{graph_name}');"
            connection.cursor_obj.calls.append((query, None))
            return query

        async def ensure_vertex_label(self, graph_name, label):
            connection.cursor_obj.calls.append(
                (f"SELECT ag_catalog.create_vlabel('{graph_name}', '{label}');", None)
            )

        async def ensure_edge_label(self, graph_name, label):
            connection.cursor_obj.calls.append(
                (f"SELECT ag_catalog.create_elabel('{graph_name}', '{label}');", None)
            )

        async def create_node(self, graph_name, label, properties):
            query = (
                f"SELECT * FROM cypher('{graph_name}', $$ CREATE (n:{label} {properties}) "
                "RETURN n $$) AS (v agtype);"
            )
            connection.cursor_obj.calls.append((query, None))
            return query

        async def create_relationship(
            self, graph_name, source_node_id, target_node_id, label, properties
        ):
            query = (
                f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}}), '
                f'(b {{"id":"{target_node_id}"}}) CREATE (a)-[:{label} {properties}]->(b) '
                "RETURN a, b $$) AS (v agtype);"
            )
            connection.cursor_obj.calls.append((query, None))
            return query

        async def commit(self):
            return None

    service = KnowledgeBaseService(RecordingRepository(connection))

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        await service.upsert_knowledge_base(
            session, knowledge_base, graph_name="demo_graph", organization_id="org-1"
        )
        await session.commit()

        # The one call writes the graph and both side-tables.
        schema_names = set(
            (
                await session.execute(
                    select(GraphSchemaRegistry.name).where(
                        GraphSchemaRegistry.graph_name == "demo_graph"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert schema_names == {"Driver", "Team", "DRIVES_FOR"}

        embedded_node_ids = set(
            (
                await session.execute(
                    select(NodeEmbedding.node_id).where(
                        NodeEmbedding.graph_name == "demo_graph"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert embedded_node_ids == {"node-1", "node-2"}

    executed_queries = connection.cursor_obj.calls
    # Graph already exists, so no create_graph call should be made
    assert not any("create_graph" in query.lower() for query, _ in executed_queries)
    assert any(
        "CREATE (n:Driver" in query or "CREATE (n:Team" in query
        for query, _ in executed_queries
    )
    assert any(
        "MATCH (a" in query and "DRIVES_FOR" in query for query, _ in executed_queries
    )


async def test_age_graph_repository_graph_exists_checks_if_graph_exists():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    class MockCursor:
        def __init__(self, has_graph=False):
            self.has_graph = has_graph
            self.last_query = None

        async def execute(self, query):
            self.last_query = query

        async def fetchone(self):
            return (1,) if self.has_graph else None

    class MockConnection:
        def __init__(self, has_graph=False):
            self.cursor_obj = MockCursor(has_graph)

        def cursor(self):
            return self.cursor_obj

    # Test graph exists
    connection = MockConnection(has_graph=True)
    repository = AgeGraphRepository(connection)
    assert await repository.graph_exists("existing_graph") is True
    assert "ag_catalog.ag_graph" in connection.cursor_obj.last_query
    assert "existing_graph" in connection.cursor_obj.last_query

    # Test graph does not exist
    connection = MockConnection(has_graph=False)
    repository = AgeGraphRepository(connection)
    assert await repository.graph_exists("nonexistent_graph") is False


async def test_age_graph_repository_delete_graph_drops_graph():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    class MockCursor:
        def __init__(self):
            self.last_query = None

        async def execute(self, query):
            self.last_query = query

    class MockConnection:
        def __init__(self):
            self.cursor_obj = MockCursor()

        def cursor(self):
            return self.cursor_obj

    connection = MockConnection()
    repository = AgeGraphRepository(connection)
    query = await repository.delete_graph("demo_graph")

    assert "drop_graph" in query.lower()
    assert "demo_graph" in query
    assert "drop_graph" in connection.cursor_obj.last_query.lower()


class _QueuedFetchOneCursor:
    """Cursor recording every query, serving a queued fetchone result per call.

    `_ensure_label` issues an existence-check SELECT (consuming one fetchone)
    and then, only when the label is missing, a second SELECT that creates it
    (no fetchone call) - so only the existence check's result needs queuing.
    """

    def __init__(self, fetchone_results=()):
        self._fetchone_results = list(fetchone_results)
        self.queries = []

    async def execute(self, query):
        self.queries.append(query)

    async def fetchone(self):
        return self._fetchone_results.pop(0)


class _QueuedFetchOneConnection:
    def __init__(self, fetchone_results=()):
        self.cursor_obj = _QueuedFetchOneCursor(fetchone_results)

    def cursor(self):
        return self.cursor_obj


async def test_age_graph_repository_ensure_vertex_label_creates_when_missing():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[None])
    repository = AgeGraphRepository(connection)

    await repository.ensure_vertex_label("demo_graph", "Driver")

    exists_query, create_query = connection.cursor_obj.queries
    assert "ag_catalog.ag_label" in exists_query
    assert "demo_graph" in exists_query and "Driver" in exists_query
    assert create_query == "SELECT ag_catalog.create_vlabel('demo_graph', 'Driver');"


async def test_age_graph_repository_ensure_vertex_label_skips_when_already_exists():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[(1,)])
    repository = AgeGraphRepository(connection)

    await repository.ensure_vertex_label("demo_graph", "Driver")

    assert len(connection.cursor_obj.queries) == 1


async def test_age_graph_repository_ensure_edge_label_creates_when_missing():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[None])
    repository = AgeGraphRepository(connection)

    await repository.ensure_edge_label("demo_graph", "DRIVES_FOR")

    _, create_query = connection.cursor_obj.queries
    assert create_query == "SELECT ag_catalog.create_elabel('demo_graph', 'DRIVES_FOR');"


async def test_age_graph_repository_ensure_edge_label_skips_when_already_exists():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[(1,)])
    repository = AgeGraphRepository(connection)

    await repository.ensure_edge_label("demo_graph", "DRIVES_FOR")

    assert len(connection.cursor_obj.queries) == 1


def _agtype_vertex(id_: int, node_id: str, label: str, **properties) -> str:
    payload = {"id": id_, "label": label, "properties": {"id": node_id, **properties}}
    return json.dumps(payload) + "::vertex"


def _agtype_edge(id_: int, start_id: int, end_id: int, label: str, **properties) -> str:
    payload = {
        "id": id_,
        "start_id": start_id,
        "end_id": end_id,
        "label": label,
        "properties": properties,
    }
    return json.dumps(payload) + "::edge"


class _RowsCursor:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.last_query = None

    async def execute(self, query):
        self.last_query = query

    async def fetchall(self):
        return self.rows


class _RowsConnection:
    def __init__(self, rows=()):
        self.cursor_obj = _RowsCursor(rows)

    def cursor(self):
        return self.cursor_obj


class _QueuedRowsCursor:
    """Cursor that serves a different row batch per execute, recording every query.

    `_RowsCursor` replays one fixed row set for every execute, which cannot
    represent `get_node_schema`'s two queries (outgoing, then incoming).
    """

    def __init__(self, row_batches=()):
        self.row_batches = [list(batch) for batch in row_batches]
        self.queries = []
        self._pending = []

    async def execute(self, query):
        self.queries.append(query)
        self._pending = self.row_batches.pop(0) if self.row_batches else []

    async def fetchall(self):
        return self._pending


class _QueuedRowsConnection:
    def __init__(self, row_batches=()):
        self.cursor_obj = _QueuedRowsCursor(row_batches)

    def cursor(self):
        return self.cursor_obj


async def test_age_graph_repository_get_node_neighbours_matches_node_by_id_property():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.get_node_neighbours("demo_graph", "driver-1")

    query = connection.cursor_obj.last_query
    assert "demo_graph" in query
    assert "MATCH (a {id: 'driver-1'})-[r]-(b)" in query
    assert "RETURN a, r, b" in query


async def test_age_graph_repository_get_node_neighbours_filters_by_labels_when_provided():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.get_node_neighbours(
        "demo_graph", "driver-1", relationship_labels=["DRIVES_FOR", "MEMBER_OF"]
    )

    assert "WHERE type(r) IN ['DRIVES_FOR', 'MEMBER_OF']" in connection.cursor_obj.last_query


async def test_age_graph_repository_get_node_neighbours_omits_label_filter_when_not_provided():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    for relationship_labels in (None, []):
        connection = _RowsConnection()
        repository = AgeGraphRepository(connection)
        await repository.get_node_neighbours(
            "demo_graph", "driver-1", relationship_labels=relationship_labels
        )
        assert "type(r)" not in connection.cursor_obj.last_query


async def test_age_graph_repository_get_node_neighbours_parses_agtype_rows():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    rows = [
        (
            _agtype_vertex(1, "driver-1", "Driver", name="Lewis"),
            _agtype_edge(10, 1, 2, "DRIVES_FOR"),
            _agtype_vertex(2, "team-1", "Team", name="Mercedes"),
        )
    ]
    connection = _RowsConnection(rows)
    repository = AgeGraphRepository(connection)

    triplets = await repository.get_node_neighbours("demo_graph", "driver-1")

    assert len(triplets) == 1
    source, relationship, target = triplets[0]
    assert source == {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}}
    assert relationship == {
        "id": 10,
        "start_id": 1,
        "end_id": 2,
        "label": "DRIVES_FOR",
        "properties": {},
    }
    assert target == {"id": 2, "label": "Team", "properties": {"id": "team-1", "name": "Mercedes"}}


async def test_age_graph_repository_get_node_neighbours_orients_source_target_via_edge_start_end_ids():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    # The queried node ("driver-1", vertex id 1) lands in the *second* returned
    # vertex position, and the edge's start_id points at vertex id 2 (the team) —
    # so the team is the true source, not whichever vertex happened to bind to `a`.
    rows = [
        (
            _agtype_vertex(1, "driver-1", "Driver"),
            _agtype_edge(10, 2, 1, "DRIVES_FOR"),
            _agtype_vertex(2, "team-1", "Team"),
        )
    ]
    connection = _RowsConnection(rows)
    repository = AgeGraphRepository(connection)

    [(source, _, target)] = await repository.get_node_neighbours("demo_graph", "driver-1")

    assert source["properties"]["id"] == "team-1"
    assert target["properties"]["id"] == "driver-1"


async def test_age_graph_repository_get_node_neighbours_deduplicates_repeated_edge_rows():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    row = (
        _agtype_vertex(1, "driver-1", "Driver"),
        _agtype_edge(10, 1, 2, "DRIVES_FOR"),
        _agtype_vertex(2, "team-1", "Team"),
    )
    connection = _RowsConnection([row, row])
    repository = AgeGraphRepository(connection)

    triplets = await repository.get_node_neighbours("demo_graph", "driver-1")

    assert len(triplets) == 1


async def test_age_graph_repository_get_node_neighbours_returns_empty_list_when_no_relationships():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection([])
    repository = AgeGraphRepository(connection)

    assert await repository.get_node_neighbours("demo_graph", "driver-1") == []


async def test_upsert_records_merges_knowledge_base_ids_for_same_label_across_knowledge_bases():
    # The same label (e.g. "Driver") may be defined by more than one knowledge base
    # feeding the same graph; the registry keeps a single shared row and accumulates
    # every contributing knowledge base's id instead of splitting into separate rows.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    def _driver(knowledge_base_id: str) -> GraphSchemaRegistry:
        return GraphSchemaRegistry(
            organization_id="org-1",
            graph_name="shared_graph",
            knowledge_base_ids=[knowledge_base_id],
            type=SchemaType.NODE,
            name="Driver",
            description="A racer",
            aliases=[],
            properties=[],
        )

    async with AsyncSession(engine) as session:
        await GraphSchemaRegistry.upsert_records(session, [_driver("kb-b")])
        await session.commit()

        await GraphSchemaRegistry.upsert_records(session, [_driver("kb-a")])
        await session.commit()

        rows = (
            (
                await session.execute(
                    select(GraphSchemaRegistry).where(GraphSchemaRegistry.name == "Driver")
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].knowledge_base_ids == ["kb-a", "kb-b"]


def test_get_graph_schema_registry_records_requires_knowledge_base_id():
    knowledge_base = KnowledgeBase.model_validate(
        {"id": None, "name": "demo", "nodes": [{"label": "Driver"}]}
    )

    with pytest.raises(ValueError, match="id is required"):
        knowledge_base.get_graph_schema_registry_records("demo", "org-1")


def test_get_graph_schema_registry_records_requires_organization_id():
    knowledge_base = KnowledgeBase.model_validate(
        {"name": "demo", "nodes": [{"label": "Driver"}]}
    )

    with pytest.raises(ValueError, match="organization_id is required"):
        knowledge_base.get_graph_schema_registry_records("demo", "")


async def test_age_graph_repository_get_node_schema_queries_both_directions_by_id_property():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.get_node_schema("demo_graph", "driver-1")

    outgoing, incoming = connection.cursor_obj.queries
    assert "MATCH (a {id: 'driver-1'})-[r]->(b)" in outgoing
    assert "MATCH (a {id: 'driver-1'})<-[r]-(b)" in incoming
    for query in (outgoing, incoming):
        assert "demo_graph" in query
        assert "RETURN type(r), label(b), count(*)" in query


async def test_age_graph_repository_get_node_schema_parses_scalars_and_tags_direction():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection(
        [
            [('"RACED_FOR"', '"Team"', "3")],
            [('"SPONSORS"', '"Sponsor"', "1")],
        ]
    )
    repository = AgeGraphRepository(connection)

    assert await repository.get_node_schema("demo_graph", "driver-1") == [
        ("RACED_FOR", "outgoing", "Team", 3),
        ("SPONSORS", "incoming", "Sponsor", 1),
    ]


async def test_age_graph_repository_get_node_schema_orders_entries_deterministically():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    # The database gives no row-order guarantee, so entries are sorted within
    # each direction — but outgoing still precedes incoming.
    connection = _QueuedRowsConnection(
        [
            [
                ('"WON"', '"Race"', "12"),
                ('"RACED_FOR"', '"Team"', "3"),
                ('"RACED_FOR"', '"Academy"', "1"),
            ],
            [('"SPONSORS"', '"Sponsor"', "1")],
        ]
    )
    repository = AgeGraphRepository(connection)

    assert await repository.get_node_schema("demo_graph", "driver-1") == [
        ("RACED_FOR", "outgoing", "Academy", 1),
        ("RACED_FOR", "outgoing", "Team", 3),
        ("WON", "outgoing", "Race", 12),
        ("SPONSORS", "incoming", "Sponsor", 1),
    ]


async def test_age_graph_repository_get_node_schema_returns_empty_list_when_no_relationships():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection([[], []])
    repository = AgeGraphRepository(connection)

    assert await repository.get_node_schema("demo_graph", "driver-1") == []


async def test_age_graph_repository_get_label_schema_queries_both_directions_by_label():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.get_label_schema("demo_graph", "Driver")

    outgoing, incoming = connection.cursor_obj.queries
    assert "MATCH (a:Driver)-[r]->(b)" in outgoing
    assert "MATCH (a:Driver)<-[r]-(b)" in incoming
    for query in (outgoing, incoming):
        assert "demo_graph" in query
        assert "RETURN type(r), label(b), count(*)" in query


async def test_age_graph_repository_get_label_schema_parses_scalars_and_tags_direction():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection(
        [
            [('"RACED_FOR"', '"Team"', "20"), ('"RACED_FOR"', '"Academy"', "4")],
            [('"SPONSORS"', '"Sponsor"', "7")],
        ]
    )
    repository = AgeGraphRepository(connection)

    # Counts are graph-wide totals across every Driver, not one driver's degree.
    assert await repository.get_label_schema("demo_graph", "Driver") == [
        ("RACED_FOR", "outgoing", "Academy", 4),
        ("RACED_FOR", "outgoing", "Team", 20),
        ("SPONSORS", "incoming", "Sponsor", 7),
    ]


@pytest.mark.parametrize(
    "label", ["", "   ", "Driver) DETACH DELETE (a", "Driver-1", "1Driver"]
)
async def test_age_graph_repository_get_label_schema_rejects_unsafe_labels(label):
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection()
    repository = AgeGraphRepository(connection)

    with pytest.raises(ValueError, match="valid graph label"):
        await repository.get_label_schema("demo_graph", label)
    assert connection.cursor_obj.queries == []


class _RecordingAgeRepository:
    """Stands in for AgeGraphRepository, recording the Cypher it is asked to run."""

    def __init__(self, graph_exists: bool = True):
        self._graph_exists = graph_exists
        self.queries: list[str] = []
        self.commits = 0

    async def graph_exists(self, graph_name):
        return self._graph_exists

    async def create_graph(self, graph_name):
        query = f"SELECT * FROM ag_catalog.create_graph('{graph_name}');"
        self.queries.append(query)
        return query

    async def ensure_vertex_label(self, graph_name, label):
        self.queries.append(f"SELECT ag_catalog.create_vlabel('{graph_name}', '{label}');")

    async def ensure_edge_label(self, graph_name, label):
        self.queries.append(f"SELECT ag_catalog.create_elabel('{graph_name}', '{label}');")

    async def create_node(self, graph_name, label, properties):
        query = f"CREATE (n:{label} {properties})"
        self.queries.append(query)
        return query

    async def create_relationship(
        self, graph_name, source_node_id, target_node_id, label, properties
    ):
        query = f"CREATE ({source_node_id})-[:{label}]->({target_node_id})"
        self.queries.append(query)
        return query

    async def delete_node(self, graph_name, node_id):
        query = f'MATCH (n {{id:"{node_id}"}}) DETACH DELETE n'
        self.queries.append(query)
        return query

    async def delete_graph(self, graph_name):
        query = f"SELECT * FROM ag_catalog.drop_graph('{graph_name}', true);"
        self.queries.append(query)
        return query

    async def commit(self):
        self.commits += 1


async def _sqlite_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return AsyncSession(engine)


def _demo_knowledge_base(knowledge_base_id: str) -> KnowledgeBase:
    return KnowledgeBase.model_validate(
        {
            "id": knowledge_base_id,
            "name": f"kb_{knowledge_base_id}",
            "nodes": [
                {
                    "id": f"{knowledge_base_id}-node-1",
                    "label": "Driver",
                    "properties": {"name": "Max Verstappen"},
                },
                {
                    "id": f"{knowledge_base_id}-node-2",
                    "label": "Team",
                    "properties": {"name": "Red Bull"},
                },
            ],
            "relationships": [
                {
                    "source_id": f"{knowledge_base_id}-node-1",
                    "target_id": f"{knowledge_base_id}-node-2",
                    "label": "DRIVES_FOR",
                    "properties": {},
                }
            ],
        }
    )


async def test_upsert_knowledge_base_ensures_labels_once_before_creating_nodes():
    # Regression test: Apache Age's implicit auto-create-on-first-CREATE races
    # when several CREATEs for the same brand-new label run in one uncommitted
    # transaction, raising DuplicateTable. Every label must be ensured exactly
    # once, before any CREATE that references it - even when multiple nodes
    # share the label.
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)
    knowledge_base = KnowledgeBase.model_validate(
        {
            "id": "kb-multi",
            "name": "kb_multi",
            "nodes": [
                {"id": "kb-multi-d1", "label": "Driver", "properties": {"name": "A"}},
                {"id": "kb-multi-d2", "label": "Driver", "properties": {"name": "B"}},
            ],
            "relationships": [
                {
                    "source_id": "kb-multi-d1",
                    "target_id": "kb-multi-d2",
                    "label": "TEAMMATE_OF",
                    "properties": {},
                }
            ],
        }
    )

    async with await _sqlite_session() as session:
        await service.upsert_knowledge_base(
            session, knowledge_base, "demo_graph", "org-1"
        )

    ensure_vertex_calls = [q for q in repository.queries if "create_vlabel" in q]
    ensure_edge_calls = [q for q in repository.queries if "create_elabel" in q]
    create_node_indices = [
        i
        for i, q in enumerate(repository.queries)
        if q.startswith("CREATE (n:Driver")
    ]
    create_relationship_indices = [
        i
        for i, q in enumerate(repository.queries)
        if q.startswith("CREATE (") and "TEAMMATE_OF" in q
    ]

    # Ensured exactly once, even though two Driver nodes are created.
    assert ensure_vertex_calls == [
        "SELECT ag_catalog.create_vlabel('demo_graph', 'Driver');"
    ]
    assert ensure_edge_calls == [
        "SELECT ag_catalog.create_elabel('demo_graph', 'TEAMMATE_OF');"
    ]

    # And before any CREATE that references the label.
    vertex_ensure_index = repository.queries.index(ensure_vertex_calls[0])
    edge_ensure_index = repository.queries.index(ensure_edge_calls[0])
    assert all(vertex_ensure_index < i for i in create_node_indices)
    assert all(edge_ensure_index < i for i in create_relationship_indices)


async def test_delete_knowledge_base_removes_nodes_embeddings_and_registry_rows():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService
    from graphrag_apacheage.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)
    knowledge_base = _demo_knowledge_base("kb-1")

    async with await _sqlite_session() as session:
        await service.upsert_knowledge_base(
            session, knowledge_base, "demo_graph", "org-1"
        )
        await session.commit()

        repository.queries.clear()
        queries = await service.delete_knowledge_base(
            session, "kb-1", "demo_graph", "org-1"
        )
        await session.commit()

        # Every node this knowledge base wrote is detach-deleted from the graph;
        # its relationships go with the nodes.
        assert len(queries) == 2
        assert all("DETACH DELETE" in query for query in queries)
        assert {"kb-1-node-1", "kb-1-node-2"} == {
            query.split('"')[1] for query in queries
        }

        remaining_embeddings = (
            (await session.execute(select(NodeEmbedding))).scalars().all()
        )
        assert remaining_embeddings == []

        remaining_schema = (
            (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        )
        assert remaining_schema == []


async def test_delete_knowledge_base_keeps_registry_rows_shared_with_another_base():
    # The same label may be defined by several knowledge bases feeding one graph;
    # deleting one must only drop its id, not the shared row.
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService
    from graphrag_apacheage.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)

    async with await _sqlite_session() as session:
        await service.upsert_knowledge_base(
            session, _demo_knowledge_base("kb-1"), "demo_graph", "org-1"
        )
        await service.upsert_knowledge_base(
            session, _demo_knowledge_base("kb-2"), "demo_graph", "org-1"
        )
        await session.commit()

        rows = (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        assert all(
            sorted(row.knowledge_base_ids) == ["kb-1", "kb-2"] for row in rows
        )

        await service.delete_knowledge_base(session, "kb-1", "demo_graph", "org-1")
        await session.commit()

        rows = (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        assert {row.name for row in rows} == {"Driver", "Team", "DRIVES_FOR"}
        assert all(row.knowledge_base_ids == ["kb-2"] for row in rows)

        # Only the deleted knowledge base's node embeddings are removed.
        remaining = (await session.execute(select(NodeEmbedding))).scalars().all()
        assert {record.knowledge_base_id for record in remaining} == {"kb-2"}


async def test_delete_knowledge_base_validates_graph_name_and_knowledge_base_id():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.delete_knowledge_base(None, "kb-1", "", "org-1")

    with pytest.raises(ValueError, match="knowledge_base_id is required"):
        await service.delete_knowledge_base(None, "", "demo_graph", "org-1")


async def test_delete_knowledge_base_raises_error_if_graph_does_not_exist():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository(graph_exists=False))

    with pytest.raises(ValueError, match="does not exist in the database"):
        await service.delete_knowledge_base(None, "kb-1", "demo_graph", "org-1")


async def test_delete_graph_drops_the_graph_and_all_its_side_table_rows():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService
    from graphrag_apacheage.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)

    async with await _sqlite_session() as session:
        # Two knowledge bases in the graph being dropped, one in a graph that stays.
        await service.upsert_knowledge_base(
            session, _demo_knowledge_base("kb-1"), "doomed_graph", "org-1"
        )
        await service.upsert_knowledge_base(
            session, _demo_knowledge_base("kb-2"), "doomed_graph", "org-1"
        )
        await service.upsert_knowledge_base(
            session, _demo_knowledge_base("kb-3"), "other_graph", "org-1"
        )
        await session.commit()

        repository.queries.clear()
        query = await service.delete_graph(session, "doomed_graph", "org-1")
        await session.commit()

        assert "drop_graph('doomed_graph', true)" in query
        # The graph drop cascades, so no per-node DETACH DELETE is issued.
        assert not any("DETACH DELETE" in issued for issued in repository.queries)

        # Registry rows are deleted outright, not adjusted: no knowledge base has a
        # remaining claim on a graph that no longer exists.
        remaining_schema = (
            (await session.execute(select(GraphSchemaRegistry))).scalars().all()
        )
        assert {row.graph_name for row in remaining_schema} == {"other_graph"}
        assert all(row.knowledge_base_ids == ["kb-3"] for row in remaining_schema)

        remaining_embeddings = (
            (await session.execute(select(NodeEmbedding))).scalars().all()
        )
        assert {record.graph_name for record in remaining_embeddings} == {"other_graph"}


async def test_delete_graph_cleans_side_tables_even_when_the_graph_is_already_gone():
    # Dropping a graph is exactly what orphans the side-tables, so a missing graph
    # must still clean them up rather than raise.
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService
    from graphrag_apacheage.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)

    async with await _sqlite_session() as session:
        await service.upsert_knowledge_base(
            session, _demo_knowledge_base("kb-1"), "demo_graph", "org-1"
        )
        await session.commit()

        repository._graph_exists = False
        repository.queries.clear()
        query = await service.delete_graph(session, "demo_graph", "org-1")
        await session.commit()

        assert query is None
        assert repository.queries == []
        assert (await session.execute(select(NodeEmbedding))).scalars().all() == []
        assert (
            await session.execute(select(GraphSchemaRegistry))
        ).scalars().all() == []


async def test_delete_graph_validates_graph_name():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.delete_graph(None, "", "org-1")


async def test_create_graph_creates_the_graph_and_is_a_no_op_when_it_exists():
    # The symmetric partner of delete_graph(): both return None when there is
    # nothing to do, so the graph lifecycle is driven entirely through the service.
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    repository = _RecordingAgeRepository(graph_exists=False)
    service = KnowledgeBaseService(repository)

    query = await service.create_graph("demo_graph")
    assert "create_graph('demo_graph')" in query
    assert repository.commits == 1

    repository._graph_exists = True
    repository.queries.clear()
    assert await service.create_graph("demo_graph") is None
    assert repository.queries == []


async def test_create_graph_validates_graph_name():
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.create_graph("")


async def test_age_graph_repository_search_relationships_matches_directed_pattern_by_label():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.search_relationships("demo_graph", "DRIVES_FOR")

    query = connection.cursor_obj.last_query
    assert "demo_graph" in query
    assert "MATCH (a)-[r:DRIVES_FOR]->(b)" in query
    assert "RETURN a, r, b" in query


async def test_age_graph_repository_search_relationships_filters_by_endpoint_labels_and_ids():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.search_relationships(
        "demo_graph",
        "DRIVES_FOR",
        source_label="Driver",
        target_label="Team",
        source_id="driver-1",
        target_id="team-1",
    )

    query = connection.cursor_obj.last_query
    assert "MATCH (a:Driver {id: 'driver-1'})-[r:DRIVES_FOR]->(b:Team {id: 'team-1'})" in query


async def test_age_graph_repository_search_relationships_filters_by_relationship_properties():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.search_relationships(
        "demo_graph", "DRIVES_FOR", properties={"season": 2025}
    )

    assert "[r:DRIVES_FOR {season: 2025}]" in connection.cursor_obj.last_query


async def test_age_graph_repository_search_relationships_parses_agtype_rows():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    rows = [
        (
            _agtype_vertex(1, "driver-1", "Driver", name="Lewis"),
            _agtype_edge(10, 1, 2, "DRIVES_FOR", season=2025),
            _agtype_vertex(2, "team-1", "Team", name="Mercedes"),
        )
    ]
    connection = _RowsConnection(rows)
    repository = AgeGraphRepository(connection)

    triplets = await repository.search_relationships("demo_graph", "DRIVES_FOR")

    assert triplets == [
        (
            {"id": 1, "label": "Driver", "properties": {"id": "driver-1", "name": "Lewis"}},
            {
                "id": 10,
                "start_id": 1,
                "end_id": 2,
                "label": "DRIVES_FOR",
                "properties": {"season": 2025},
            },
            {"id": 2, "label": "Team", "properties": {"id": "team-1", "name": "Mercedes"}},
        )
    ]


async def test_age_graph_repository_search_relationships_returns_empty_list_when_no_matches():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection([])
    repository = AgeGraphRepository(connection)

    assert await repository.search_relationships("demo_graph", "DRIVES_FOR") == []


async def test_get_properties_by_name_returns_properties_scoped_by_graph_and_type():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as session:
        session.add_all(
            [
                GraphSchemaRegistry(
                    organization_id="org-1",
                    graph_name="demo_graph",
                    knowledge_base_ids=["kb-1"],
                    type=SchemaType.NODE,
                    name="Driver",
                    description="A racer",
                    aliases=[],
                    properties=["name", "number"],
                ),
                GraphSchemaRegistry(
                    organization_id="org-1",
                    graph_name="demo_graph",
                    knowledge_base_ids=["kb-1"],
                    type=SchemaType.RELATIONSHIP,
                    name="RACED_FOR",
                    description="Drove for a team",
                    aliases=[],
                    properties=["season"],
                ),
                # Same name, different graph: must not leak into the lookup below.
                GraphSchemaRegistry(
                    organization_id="org-1",
                    graph_name="other_graph",
                    knowledge_base_ids=["kb-2"],
                    type=SchemaType.NODE,
                    name="Driver",
                    description="A racer",
                    aliases=[],
                    properties=["unrelated"],
                ),
                # Same name and graph, different organization: must not leak either.
                GraphSchemaRegistry(
                    organization_id="org-2",
                    graph_name="demo_graph",
                    knowledge_base_ids=["kb-3"],
                    type=SchemaType.NODE,
                    name="Driver",
                    description="A racer",
                    aliases=[],
                    properties=["unrelated"],
                ),
            ]
        )
        await session.commit()

        node_properties = await GraphSchemaRegistry.get_properties_by_name(
            session, "demo_graph", "org-1", ["Driver", "Team"], type=SchemaType.NODE
        )
        relationship_properties = await GraphSchemaRegistry.get_properties_by_name(
            session, "demo_graph", "org-1", ["RACED_FOR"], type=SchemaType.RELATIONSHIP
        )
        empty = await GraphSchemaRegistry.get_properties_by_name(
            session, "demo_graph", "org-1", []
        )

    assert node_properties == {"Driver": ["name", "number"]}
    assert relationship_properties == {"RACED_FOR": ["season"]}
    assert empty == {}
