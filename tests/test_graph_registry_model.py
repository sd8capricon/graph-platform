import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from common.models.base import Base
from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.node_embedding import NodeEmbedding
from common.schemas.knowledge_base import KnowledgeBase
from common.schemas.graph_schema_registry import SchemaType
from common.schemas.model import AuthMode, Model, ModelType


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


async def test_age_graph_repository_graph_exists_checks_if_graph_exists():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[None])
    repository = AgeGraphRepository(connection)

    await repository.ensure_vertex_label("demo_graph", "Driver")

    exists_query, create_query = connection.cursor_obj.queries
    assert "ag_catalog.ag_label" in exists_query
    assert "demo_graph" in exists_query and "Driver" in exists_query
    assert create_query == "SELECT ag_catalog.create_vlabel('demo_graph', 'Driver');"


async def test_age_graph_repository_ensure_vertex_label_skips_when_already_exists():
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[(1,)])
    repository = AgeGraphRepository(connection)

    await repository.ensure_vertex_label("demo_graph", "Driver")

    assert len(connection.cursor_obj.queries) == 1


async def test_age_graph_repository_ensure_edge_label_creates_when_missing():
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedFetchOneConnection(fetchone_results=[None])
    repository = AgeGraphRepository(connection)

    await repository.ensure_edge_label("demo_graph", "DRIVES_FOR")

    _, create_query = connection.cursor_obj.queries
    assert create_query == "SELECT ag_catalog.create_elabel('demo_graph', 'DRIVES_FOR');"


async def test_age_graph_repository_ensure_edge_label_skips_when_already_exists():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.get_node_neighbours("demo_graph", "driver-1")

    query = connection.cursor_obj.last_query
    assert "demo_graph" in query
    assert "MATCH (a {id: 'driver-1'})-[r]-(b)" in query
    assert "RETURN a, r, b" in query


async def test_age_graph_repository_get_node_neighbours_filters_by_labels_when_provided():
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.get_node_neighbours(
        "demo_graph", "driver-1", relationship_labels=["DRIVES_FOR", "MEMBER_OF"]
    )

    assert "WHERE type(r) IN ['DRIVES_FOR', 'MEMBER_OF']" in connection.cursor_obj.last_query


async def test_age_graph_repository_get_node_neighbours_omits_label_filter_when_not_provided():
    from common.repositories.age_graph_repository import AgeGraphRepository

    for relationship_labels in (None, []):
        connection = _RowsConnection()
        repository = AgeGraphRepository(connection)
        await repository.get_node_neighbours(
            "demo_graph", "driver-1", relationship_labels=relationship_labels
        )
        assert "type(r)" not in connection.cursor_obj.last_query


async def test_age_graph_repository_get_node_neighbours_parses_agtype_rows():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection([])
    repository = AgeGraphRepository(connection)

    assert await repository.get_node_neighbours("demo_graph", "driver-1") == []


async def test_age_graph_repository_get_node_schema_queries_both_directions_by_id_property():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _QueuedRowsConnection([[], []])
    repository = AgeGraphRepository(connection)

    assert await repository.get_node_schema("demo_graph", "driver-1") == []


async def test_age_graph_repository_get_label_schema_queries_both_directions_by_label():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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


async def _seed_side_tables(session, knowledge_base, graph_name, organization_id):
    """Seed the registry/embedding rows the worker write would have persisted.

    Mirrors the worker's two side-table upserts (schema registry merges by label;
    node embedding rows are one per node) without the graph write, so the
    lifecycle/delete tests can run without importing the ingestion worker.
    """
    kb_id = knowledge_base.id

    async def _schema_row(name, schema_type, properties, source_label=None, target_label=None):
        row = (
            await session.execute(
                select(GraphSchemaRegistry).where(
                    GraphSchemaRegistry.organization_id == organization_id,
                    GraphSchemaRegistry.graph_name == graph_name,
                    GraphSchemaRegistry.name == name,
                    GraphSchemaRegistry.type == schema_type,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = GraphSchemaRegistry(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_ids=[kb_id],
                type=schema_type,
                name=name,
                description="",
                aliases=[],
                properties=sorted(properties),
                source_label=source_label,
                target_label=target_label,
            )
            row.embedding_row = None
            session.add(row)
        else:
            row.knowledge_base_ids = sorted(set(row.knowledge_base_ids) | {kb_id})

    node_properties: dict[str, set] = {}
    for node in knowledge_base.nodes:
        node_properties.setdefault(node.label, set()).update(node.properties.keys())
    for label, props in node_properties.items():
        await _schema_row(label, SchemaType.NODE, props)

    for relationship in knowledge_base.relationships:
        source_label = next(
            (n.label for n in knowledge_base.nodes if n.id == relationship.source_id),
            None,
        )
        target_label = next(
            (n.label for n in knowledge_base.nodes if n.id == relationship.target_id),
            None,
        )
        await _schema_row(
            relationship.label,
            SchemaType.RELATIONSHIP,
            relationship.properties.keys(),
            source_label,
            target_label,
        )

    for node in knowledge_base.nodes:
        session.add(
            NodeEmbedding(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_id=kb_id,
                node_id=node.id,
                label=node.label,
                properties=dict(node.properties),
            )
        )
    await session.flush()


async def test_delete_knowledge_base_removes_nodes_embeddings_and_registry_rows():
    from common.services.knowledge_base_service import KnowledgeBaseService
    from common.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)
    knowledge_base = _demo_knowledge_base("kb-1")

    async with await _sqlite_session() as session:
        await _seed_side_tables(session, knowledge_base, "demo_graph", "org-1")
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
    from common.services.knowledge_base_service import KnowledgeBaseService
    from common.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)

    async with await _sqlite_session() as session:
        await _seed_side_tables(session, _demo_knowledge_base("kb-1"), "demo_graph", "org-1")
        await _seed_side_tables(session, _demo_knowledge_base("kb-2"), "demo_graph", "org-1")
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
    from common.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.delete_knowledge_base(None, "kb-1", "", "org-1")

    with pytest.raises(ValueError, match="knowledge_base_id is required"):
        await service.delete_knowledge_base(None, "", "demo_graph", "org-1")


async def test_delete_knowledge_base_raises_error_if_graph_does_not_exist():
    from common.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository(graph_exists=False))

    with pytest.raises(ValueError, match="does not exist in the database"):
        await service.delete_knowledge_base(None, "kb-1", "demo_graph", "org-1")


async def test_delete_graph_drops_the_graph_and_all_its_side_table_rows():
    from common.services.knowledge_base_service import KnowledgeBaseService
    from common.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)

    async with await _sqlite_session() as session:
        # Two knowledge bases in the graph being dropped, one in a graph that stays.
        await _seed_side_tables(session, _demo_knowledge_base("kb-1"), "doomed_graph", "org-1")
        await _seed_side_tables(session, _demo_knowledge_base("kb-2"), "doomed_graph", "org-1")
        await _seed_side_tables(session, _demo_knowledge_base("kb-3"), "other_graph", "org-1")
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
    from common.services.knowledge_base_service import KnowledgeBaseService
    from common.models.node_embedding import NodeEmbedding

    repository = _RecordingAgeRepository()
    service = KnowledgeBaseService(repository)

    async with await _sqlite_session() as session:
        await _seed_side_tables(session, _demo_knowledge_base("kb-1"), "demo_graph", "org-1")
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
    from common.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.delete_graph(None, "", "org-1")


async def test_create_graph_creates_the_graph_and_is_a_no_op_when_it_exists():
    # The symmetric partner of delete_graph(): both return None when there is
    # nothing to do, so the graph lifecycle is driven entirely through the service.
    from common.services.knowledge_base_service import KnowledgeBaseService

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
    from common.services.knowledge_base_service import KnowledgeBaseService

    service = KnowledgeBaseService(_RecordingAgeRepository())

    with pytest.raises(ValueError, match="graph_name is required"):
        await service.create_graph("")


async def test_age_graph_repository_search_relationships_matches_directed_pattern_by_label():
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.search_relationships("demo_graph", "DRIVES_FOR")

    query = connection.cursor_obj.last_query
    assert "demo_graph" in query
    assert "MATCH (a)-[r:DRIVES_FOR]->(b)" in query
    assert "RETURN a, r, b" in query


async def test_age_graph_repository_search_relationships_filters_by_endpoint_labels_and_ids():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

    connection = _RowsConnection()
    repository = AgeGraphRepository(connection)

    await repository.search_relationships(
        "demo_graph", "DRIVES_FOR", properties={"season": 2025}
    )

    assert "[r:DRIVES_FOR {season: 2025}]" in connection.cursor_obj.last_query


async def test_age_graph_repository_search_relationships_parses_agtype_rows():
    from common.repositories.age_graph_repository import AgeGraphRepository

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
    from common.repositories.age_graph_repository import AgeGraphRepository

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
