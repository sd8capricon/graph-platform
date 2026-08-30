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


def test_knowledge_base_parses_json_and_upserts_registry_rows():
    payload_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "graphrag_apacheage"
        / "dummy_data"
        / "f1_kb.json"
    )
    knowledge_base = KnowledgeBase.model_validate_json(payload_path.read_text())

    node_records = knowledge_base.get_graph_schem_registry_records()
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
