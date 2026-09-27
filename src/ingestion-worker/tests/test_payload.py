"""Tests for the worker-owned pre-extracted upload envelope (`ingestion/payload.py`)."""

import json
from pathlib import Path

import pytest

from common.schemas.graph_schema_registry import SchemaType
from ingestion_worker.ingestion.payload import (
    parse_uploaded_file,
    to_knowledge_base,
    to_node_embedding_records,
    to_schema_registry_records,
)


def _minimal_bytes():
    return json.dumps(
        {
            "id": "file-kb-1",
            "name": "demo",
            "schema": {
                "labels": [
                    {"name": "Driver", "properties": {"name": {"type": "string"}}},
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


def test_parse_minimal_envelope_keeps_temp_schema_out_of_kb_contract():
    envelope = parse_uploaded_file(_minimal_bytes())

    assert envelope.schema_block is not None
    assert [label.name for label in envelope.schema_block.labels] == ["Driver"]

    kb = to_knowledge_base(envelope, "kb-1", "demo")
    assert kb.id == "kb-1"
    assert kb.name == "demo"
    # The shared KnowledgeBase contract has no `schema` field.
    assert "schema" not in kb.model_dump()


def test_schema_registry_records_come_from_temp_block_not_derivation():
    envelope = parse_uploaded_file(_minimal_bytes())
    records = to_schema_registry_records(envelope, "g", "org-1", "kb-1")

    by_name = {record.name: record for record in records}
    assert set(by_name) == {"Driver", "RACED_FOR"}
    assert by_name["Driver"].type == SchemaType.NODE
    assert by_name["Driver"].properties == ["name"]
    assert by_name["RACED_FOR"].type == SchemaType.RELATIONSHIP
    assert by_name["RACED_FOR"].source_label == "Driver"
    assert by_name["RACED_FOR"].target_label == "Team"
    assert all(record.knowledge_base_ids == ["kb-1"] for record in records)


def test_missing_schema_block_yields_no_registry_rows_without_deriving():
    envelope = parse_uploaded_file(
        json.dumps(
            {
                "id": "kb-1",
                "name": "demo",
                "nodes": [{"id": "d1", "label": "Driver", "properties": {}}],
                "relationships": [],
            }
        ).encode("utf-8")
    )
    assert to_schema_registry_records(envelope, "g", "org-1", "kb-1") == []
    assert len(to_node_embedding_records(envelope, "g", "org-1", "kb-1")) == 1


def test_job_kb_id_is_authoritative_over_file_id():
    envelope = parse_uploaded_file(_minimal_bytes())
    kb = to_knowledge_base(envelope, "job-kb-1", "demo")
    assert kb.id == "job-kb-1"
    records = to_node_embedding_records(envelope, "g", "org-1", "job-kb-1")
    assert all(record.knowledge_base_id == "job-kb-1" for record in records)


def test_blank_label_is_rejected():
    with pytest.raises(ValueError, match="blank label"):
        parse_uploaded_file(
            json.dumps(
                {
                    "id": "kb-1",
                    "name": "demo",
                    "nodes": [{"id": "d1", "label": " ", "properties": {}}],
                    "relationships": [],
                }
            ).encode("utf-8")
        )


def test_invalid_json_is_rejected():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_uploaded_file(b"{not json")


def test_missing_node_id_is_rejected_not_generated():
    with pytest.raises(ValueError, match="expected format|blank id|required"):
        parse_uploaded_file(
            json.dumps(
                {
                    "id": "kb-1",
                    "name": "demo",
                    "nodes": [{"label": "Driver", "properties": {}}],
                    "relationships": [],
                }
            ).encode("utf-8")
        )


def test_f1_reference_file_parses():
    path = Path(__file__).resolve().parents[3] / "dummy_data" / "f1_kb.json"
    envelope = parse_uploaded_file(path.read_bytes())

    assert envelope.schema_block is not None
    assert {label.name for label in envelope.schema_block.labels} == {"Driver", "Team"}
    records = to_schema_registry_records(envelope, "g", "org-1", "kb-1")
    assert {record.name for record in records} == {"Driver", "Team", "RACED_FOR"}
    nodes = to_node_embedding_records(envelope, "g", "org-1", "kb-1")
    assert len(nodes) == len(envelope.nodes)
    assert len(nodes) > 0
