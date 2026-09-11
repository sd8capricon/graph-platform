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


__all__ = ["schema_registry_record_to_dict", "node_embedding_record_to_dict"]
