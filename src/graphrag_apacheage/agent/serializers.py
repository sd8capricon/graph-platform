from typing import Any

from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry
from graphrag_apacheage.models.node_embedding import NodeEmbedding


def schema_registry_record_to_dict(record: GraphSchemaRegistry) -> dict:
    return {
        key: value
        for key, value in {
            "type": record.type,
            "name": record.name,
            "description": record.description,
            "aliases": record.aliases,
            "properties": record.properties,
            "source_label": record.source_label,
            "target_label": record.target_label,
        }.items()
        if value is not None
    }


def node_embedding_record_to_dict(record: NodeEmbedding) -> dict:
    return {
        "node_id": record.node_id,
        "label": record.label,
        "properties": record.properties,
    }


def _age_vertex_to_dict(vertex: dict[str, Any]) -> dict[str, Any]:
    properties = dict(vertex.get("properties", {}))
    node_id = properties.pop("id", None)
    return {"node_id": node_id, "label": vertex["label"], "properties": properties}


def relationship_triplet_to_dict(
    source: dict[str, Any], relationship: dict[str, Any], target: dict[str, Any]
) -> dict:
    source_dict = _age_vertex_to_dict(source)
    target_dict = _age_vertex_to_dict(target)
    return {
        "source": source_dict,
        "relationship": {
            "source_id": source_dict["node_id"],
            "target_id": target_dict["node_id"],
            "label": relationship["label"],
            "properties": relationship.get("properties", {}),
        },
        "target": target_dict,
    }


__all__ = [
    "schema_registry_record_to_dict",
    "node_embedding_record_to_dict",
    "relationship_triplet_to_dict",
]
