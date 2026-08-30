from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from graphrag_apacheage.models.graph_schema_regsitry import (
    Base,
    GraphSchemaRegistry,
    SchemaType,
)
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase


def test_graph_registry_table_exists_and_tracks_graph_name():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "graph_registry" in inspector.get_table_names()

    columns = {column["name"] for column in inspector.get_columns("graph_registry")}
    expected = {
        "id",
        "graph_name",
        "type",
        "name",
        "description",
        "aliases",
        "properties",
        "source_label",
        "target_label",
    }
    assert expected.issubset(columns)


def test_graph_registry_type_accepts_only_node_or_relationship():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO graph_registry (graph_name, type, name, description, aliases, properties) "
                "VALUES ('demo', 'node', 'Demo Node', 'Example', '[]', '[]')"
            )
        )

    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO graph_registry (graph_name, type, name, description, aliases, properties) "
                    "VALUES ('demo', 'edge', 'Bad Node', 'Example', '[]', '[]')"
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


def test_knowledge_base_parses_json_and_upserts_registry_rows():
    payload_path = Path(__file__).resolve().parents[1] / "dummy_data" / "f1_kb.json"
    knowledge_base = KnowledgeBase.model_validate_json(payload_path.read_text())

    # Pass graph_name to the method instead of storing it on model
    node_records = knowledge_base.get_graph_schema_registry_records("F1 kb")
    assert any(
        record.type == SchemaType.NODE and record.name == "Driver"
        for record in node_records
    )
    assert any(
        record.type == SchemaType.RELATIONSHIP and record.name == "RACED_FOR"
        for record in node_records
    )

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        GraphSchemaRegistry.upsert_records(session, node_records)
        session.commit()

        rows = (
            session.execute(
                select(GraphSchemaRegistry).where(
                    GraphSchemaRegistry.graph_name == "F1 kb"
                )
            )
            .scalars()
            .all()
        )

    assert any(row.type == SchemaType.NODE and row.name == "Driver" for row in rows)
    assert any(
        row.type == SchemaType.RELATIONSHIP and row.name == "RACED_FOR" for row in rows
    )


def test_knowledge_base_graph_name_is_provided_to_service_not_stored():
    knowledge_base = KnowledgeBase.model_validate(
        {
            "name": "custom_kb",
            "nodes": [{"label": "Driver", "properties": {"name": "Alice"}}],
        }
    )

    # graph_name is not stored on model, only passed to methods
    assert knowledge_base.name == "custom_kb"

    records = knowledge_base.get_graph_schema_registry_records("shared_age_graph")
    assert records[0].graph_name == "shared_age_graph"


def test_knowledge_base_service_raises_error_if_graph_name_not_provided():
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
        # Calling without graph_name should raise ValueError
        service.upsert_knowledge_base(knowledge_base)


def test_knowledge_base_service_raises_error_if_graph_does_not_exist():
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
        def graph_exists(self, graph_name):
            return False  # Graph does not exist

    service = KnowledgeBaseService(MockRepository())

    with pytest.raises(ValueError, match="does not exist in the database"):
        service.upsert_knowledge_base(knowledge_base, graph_name="nonexistent_graph")


def test_knowledge_base_can_write_nodes_and_relationships_to_age_graph():
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

        def execute(self, query, params=None):
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

        def graph_exists(self, graph_name):
            return True  # Mock graph exists

        def create_graph(self, graph_name):
            query = f"SELECT * FROM ag_catalog.create_graph('{graph_name}');"
            connection.cursor_obj.calls.append((query, None))
            return query

        def create_node(self, graph_name, label, properties):
            query = (
                f"SELECT * FROM cypher('{graph_name}', $$ CREATE (n:{label} {properties}) "
                "RETURN n $$) AS (v agtype);"
            )
            connection.cursor_obj.calls.append((query, None))
            return query

        def create_relationship(
            self, graph_name, source_node_id, target_node_id, label, properties
        ):
            query = (
                f'SELECT * FROM cypher(\'{graph_name}\', $$ MATCH (a {{"id":"{source_node_id}"}}), '
                f'(b {{"id":"{target_node_id}"}}) CREATE (a)-[:{label} {properties}]->(b) '
                "RETURN a, b $$) AS (v agtype);"
            )
            connection.cursor_obj.calls.append((query, None))
            return query

        def commit(self):
            return None

    service = KnowledgeBaseService(RecordingRepository(connection))
    service.upsert_knowledge_base(knowledge_base, graph_name="demo_graph")

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


def test_age_graph_repository_graph_exists_checks_if_graph_exists():
    from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository

    class MockCursor:
        def __init__(self, has_graph=False):
            self.has_graph = has_graph
            self.last_query = None

        def execute(self, query):
            self.last_query = query

        def fetchone(self):
            return (1,) if self.has_graph else None

    class MockConnection:
        def __init__(self, has_graph=False):
            self.cursor_obj = MockCursor(has_graph)

        def cursor(self):
            return self.cursor_obj

    # Test graph exists
    connection = MockConnection(has_graph=True)
    repository = AgeGraphRepository(connection)
    assert repository.graph_exists("existing_graph") is True
    assert "ag_catalog.ag_graph" in connection.cursor_obj.last_query
    assert "existing_graph" in connection.cursor_obj.last_query

    # Test graph does not exist
    connection = MockConnection(has_graph=False)
    repository = AgeGraphRepository(connection)
    assert repository.graph_exists("nonexistent_graph") is False
