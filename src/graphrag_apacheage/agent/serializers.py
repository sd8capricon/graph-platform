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


def node_relationships_to_dict(
    node_id: str,
    label: str,
    properties: dict[str, Any],
    triplets: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
) -> dict:
    """Group (source, relationship, target) triplets under the queried node.

    Avoids repeating the queried node's dict once per relationship (as a flat
    triplet list would) — it appears once, with each relationship reduced to
    its label/properties, a direction ("outgoing" if the queried node is the
    relationship's source, "incoming" otherwise), and the other endpoint.
    """
    relationships = []
    for source, relationship, target in triplets:
        source_dict = _age_vertex_to_dict(source)
        target_dict = _age_vertex_to_dict(target)
        if source_dict["node_id"] == node_id:
            neighbor, direction = target_dict, "outgoing"
        else:
            neighbor, direction = source_dict, "incoming"
        relationships.append(
            {
                "label": relationship["label"],
                "properties": relationship.get("properties", {}),
                "direction": direction,
                "neighbor": neighbor,
            }
        )
    return {
        "node": {"node_id": node_id, "label": label, "properties": properties},
        "relationships": relationships,
    }


__all__ = [
    "schema_registry_record_to_dict",
    "node_embedding_record_to_dict",
    "node_relationships_to_dict",
]
