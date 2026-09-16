from typing import Any

from common.models.graph_schema_registry import GraphSchemaRegistry
from common.models.node_embedding import NodeEmbedding


class AgentSerializer:
    """ORM-record/agtype-to-plain-dict conversions shared by `agent_runtime/tools.py`.

    Grouped as staticmethods on one class (rather than left as module-level
    functions) purely for a single, discoverable import surface — none of them
    hold or need instance state. Kept in their own module, not prefixed with
    `_`, so they're importable/testable independent of any `@tool`-decorated
    function.
    """

    @staticmethod
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

    @staticmethod
    def node_embedding_record_to_dict(record: NodeEmbedding) -> dict:
        return {
            "node_id": record.node_id,
            "label": record.label,
            "properties": record.properties,
        }

    @staticmethod
    def _age_vertex_to_dict(vertex: dict[str, Any]) -> dict[str, Any]:
        properties = dict(vertex.get("properties", {}))
        node_id = properties.pop("id", None)
        return {"node_id": node_id, "label": vertex["label"], "properties": properties}

    @classmethod
    def node_neighbours_to_dict(
        cls,
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
            source_dict = cls._age_vertex_to_dict(source)
            target_dict = cls._age_vertex_to_dict(target)
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

    @classmethod
    def relationship_matches_to_dict(
        cls,
        triplets: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    ) -> list[dict]:
        """Reshape (source, relationship, target) triplets from a relationship search.

        Unlike `node_neighbours_to_dict`, there is no single queried node to
        group results under — `get_relationship` can match relationships
        between different node pairs in one call — so each triplet is returned
        as its own source/relationship/target dict.
        """
        return [
            {
                "source": cls._age_vertex_to_dict(source),
                "relationship": {
                    "label": relationship["label"],
                    "properties": relationship.get("properties", {}),
                },
                "target": cls._age_vertex_to_dict(target),
            }
            for source, relationship, target in triplets
        ]

    @staticmethod
    def node_schema_to_dict(
        node_id: str | None,
        label: str,
        entries: list[tuple[str, str, str, int]],
        node_properties: list[str] | None = None,
        relationship_properties: dict[str, list[str]] | None = None,
        neighbor_properties: dict[str, list[str]] | None = None,
    ) -> dict:
        """Group a node's or label's (relationship, direction, neighbor label, count) entries under it.

        The anchor (node or label) appears once rather than per entry,
        mirroring `node_neighbours_to_dict`. `node_properties`/
        `relationship_properties`/`neighbor_properties` are property-name lists
        (from `GraphSchemaRegistry`), not instance values — this is a summary of
        the neighborhood *shape*, not its data. `relationship_properties` and
        `neighbor_properties` are keyed by label since the same label can repeat
        across entries (once per direction, or for different neighbor labels).

        `node_id` is `None` in label mode (`get_node_schema` called without an
        id, via `AgeGraphRepository.get_label_schema`). The `node` block then
        omits the `node_id` key entirely rather than carrying a `null`,
        matching `schema_registry_record_to_dict`'s drop-None convention, so
        the model never sees a null it might echo back as a real id. In that
        mode each `count` is a total across *every* node carrying `label` —
        the label's aggregate traffic on that relationship, not any one node's
        degree — so it must not be read as "this node has N neighbours".
        """
        relationship_properties = relationship_properties or {}
        neighbor_properties = neighbor_properties or {}
        node: dict[str, Any] = {"label": label, "properties": node_properties or []}
        if node_id is not None:
            node = {"node_id": node_id, **node}
        return {
            "node": node,
            "relationships": [
                {
                    "label": relationship_label,
                    "properties": relationship_properties.get(relationship_label, []),
                    "direction": direction,
                    "neighbor_label": neighbor_label,
                    "neighbor_properties": neighbor_properties.get(neighbor_label, []),
                    "count": count,
                }
                for relationship_label, direction, neighbor_label, count in entries
            ],
        }


__all__ = ["AgentSerializer"]
