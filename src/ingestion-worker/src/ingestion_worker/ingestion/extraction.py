"""Extraction of schema-registry and node-embedding records from a KnowledgeBase.

This is ingestion-only logic (ADR-0004 Decision 4): only the ingestion pipeline
builds these records, so it lives in the worker rather than in `common`. It is
the moved home of `KnowledgeBase.get_graph_schema_registry_records()` and
`KnowledgeBase.get_node_embedding_records()`.
"""

from common.models.graph_schema_registry import GraphSchemaRegistry, SchemaType
from common.models.node_embedding import NodeEmbedding
from common.schemas.knowledge_base import KnowledgeBase


def graph_schema_registry_records(
    knowledge_base: KnowledgeBase, graph_name: str, organization_id: str
) -> list[GraphSchemaRegistry]:
    """Extract schema registry records from a knowledge base.

    Groups nodes by label and relationships by label into one record each,
    unioning the property names seen. Relationship records get their
    source/target labels resolved from the endpoint nodes.
    """
    if not knowledge_base.id:
        raise ValueError(
            "id is required on the knowledge base when building graph schema "
            "registry records"
        )
    if not organization_id:
        raise ValueError(
            "organization_id is required when building graph schema registry records"
        )
    knowledge_base_id = knowledge_base.id

    grouped: dict[tuple[str, str, str], GraphSchemaRegistry] = {}

    for node in knowledge_base.nodes:
        key = (graph_name, SchemaType.NODE.value, node.label)
        row = grouped.setdefault(
            key,
            GraphSchemaRegistry(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_ids=[knowledge_base_id],
                type=SchemaType.NODE,
                name=node.label,
                description="",
                aliases=[],
                properties=list(node.properties.keys()),
                source_label=None,
                target_label=None,
            ),
        )
        row.properties = sorted(set(row.properties) | set(node.properties.keys()))

    for relationship in knowledge_base.relationships:
        source_label = next(
            (
                node.label
                for node in knowledge_base.nodes
                if node.id == relationship.source_id
            ),
            None,
        )
        target_label = next(
            (
                node.label
                for node in knowledge_base.nodes
                if node.id == relationship.target_id
            ),
            None,
        )
        key = (graph_name, SchemaType.RELATIONSHIP.value, relationship.label)
        row = grouped.setdefault(
            key,
            GraphSchemaRegistry(
                organization_id=organization_id,
                graph_name=graph_name,
                knowledge_base_ids=[knowledge_base_id],
                type=SchemaType.RELATIONSHIP,
                name=relationship.label,
                description="",
                aliases=[],
                properties=list(relationship.properties.keys()),
                source_label=source_label,
                target_label=target_label,
            ),
        )
        row.properties = sorted(
            set(row.properties) | set(relationship.properties.keys())
        )
        row.source_label = source_label or row.source_label
        row.target_label = target_label or row.target_label

    return list(grouped.values())


def node_embedding_records(
    knowledge_base: KnowledgeBase, graph_name: str, organization_id: str
) -> list[NodeEmbedding]:
    """Build one unsaved NodeEmbedding record per node in the knowledge base."""
    if not knowledge_base.id:
        raise ValueError(
            "id is required on the knowledge base when building node embedding records"
        )
    if not organization_id:
        raise ValueError(
            "organization_id is required when building node embedding records"
        )
    knowledge_base_id = knowledge_base.id

    return [
        NodeEmbedding(
            organization_id=organization_id,
            graph_name=graph_name,
            knowledge_base_id=knowledge_base_id,
            node_id=node.id,
            label=node.label,
            properties=dict(node.properties),
        )
        for node in knowledge_base.nodes
    ]


__all__ = ["graph_schema_registry_records", "node_embedding_records"]
