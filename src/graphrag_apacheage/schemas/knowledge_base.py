from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from graphrag_apacheage.models.graph_schema_regsitry import (
    GraphSchemaRegistry,
    SchemaType,
)


class KnowledgeNode(BaseModel):
    id: str | None = None
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def ensure_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data


class KnowledgeRelationship(BaseModel):
    source_id: str | None = None
    target_id: str | None = None
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def ensure_related_ids(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("source_id", str(uuid4()))
            data.setdefault("target_id", str(uuid4()))
        return data


class KnowledgeBase(BaseModel):
    id: str | None = None
    name: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    relationships: list[KnowledgeRelationship] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def ensure_knowledge_base_id(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data.setdefault("id", str(uuid4()))
        return data

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> "KnowledgeBase":
        return cls.model_validate_json(Path(file_path).read_text())

    def get_graph_schema_registry_records(
        self, graph_name: str
    ) -> list[GraphSchemaRegistry]:
        grouped: dict[tuple[str, str, str], GraphSchemaRegistry] = {}

        for node in self.nodes:
            key = (graph_name, SchemaType.NODE.value, node.label)
            row = grouped.setdefault(
                key,
                GraphSchemaRegistry(
                    graph_name=graph_name,
                    type=SchemaType.NODE,
                    name=node.label,
                    description="",
                    aliases=[node.label],
                    properties=list(node.properties.keys()),
                    source_label=None,
                    target_label=None,
                ),
            )
            row.aliases = sorted(set(row.aliases) | {node.label, node.id})
            row.properties = sorted(set(row.properties) | set(node.properties.keys()))

        for relationship in self.relationships:
            source_label = next(
                (
                    node.label
                    for node in self.nodes
                    if node.id == relationship.source_id
                ),
                None,
            )
            target_label = next(
                (
                    node.label
                    for node in self.nodes
                    if node.id == relationship.target_id
                ),
                None,
            )
            key = (graph_name, SchemaType.RELATIONSHIP.value, relationship.label)
            row = grouped.setdefault(
                key,
                GraphSchemaRegistry(
                    graph_name=graph_name,
                    type=SchemaType.RELATIONSHIP,
                    name=relationship.label,
                    description="",
                    aliases=[relationship.label],
                    properties=list(relationship.properties.keys()),
                    source_label=source_label,
                    target_label=target_label,
                ),
            )
            row.aliases = sorted(set(row.aliases) | {relationship.label})
            row.properties = sorted(
                set(row.properties) | set(relationship.properties.keys())
            )
            row.source_label = source_label or row.source_label
            row.target_label = target_label or row.target_label

        return list(grouped.values())


__all__ = [
    "KnowledgeBase",
    "KnowledgeNode",
    "KnowledgeRelationship",
]
