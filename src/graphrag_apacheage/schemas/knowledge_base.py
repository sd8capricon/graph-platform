from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from graphrag_apacheage.models.graph_schema_regsitry import (
    GraphSchemaRegistry,
    SchemaType,
)


class KnowledgeNode(BaseModel):
    id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRelationship(BaseModel):
    source_id: str
    target_id: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class KnowledgeBase(BaseModel):
    name: str
    nodes: list[KnowledgeNode] = Field(default_factory=list)
    relationships: list[KnowledgeRelationship] = Field(default_factory=list)

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> "KnowledgeBase":
        return cls.model_validate_json(Path(file_path).read_text())

    def get_graph_schem_registry_records(self) -> list[GraphSchemaRegistry]:
        grouped: dict[tuple[str, str, str], GraphSchemaRegistry] = {}

        for node in self.nodes:
            key = (self.name, SchemaType.NODE.value, node.label)
            row = grouped.setdefault(
                key,
                GraphSchemaRegistry(
                    graph_name=self.name,
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
            key = (self.name, SchemaType.RELATIONSHIP.value, relationship.label)
            row = grouped.setdefault(
                key,
                GraphSchemaRegistry(
                    graph_name=self.name,
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

    def upsert_graph_registry(self, session) -> list[GraphSchemaRegistry]:
        records = self.get_graph_schem_registry_records()
        return GraphSchemaRegistry.upsert_records(session, records)


def upsert_knowledge_base(
    session, knowledge_base: KnowledgeBase
) -> list[GraphSchemaRegistry]:
    return knowledge_base.upsert_graph_registry(session)


__all__ = [
    "KnowledgeBase",
    "KnowledgeNode",
    "KnowledgeRelationship",
    "upsert_knowledge_base",
]
