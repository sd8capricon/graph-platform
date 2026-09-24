"""Idempotent graph write for the ingestion pipeline.

Uses the repository's `merge_node`/`merge_relationship` (Cypher `MERGE` on the
app-level `id`) instead of `create_*`, so a retried or redelivered task does not
duplicate nodes or edges (ADR-0005, "Idempotency").
"""

from common.repositories.age_graph_repository import AgeGraphRepository
from common.schemas.knowledge_base import KnowledgeBase


async def merge_knowledge_base(
    repository: AgeGraphRepository,
    knowledge_base: KnowledgeBase,
    graph_name: str,
) -> list[str]:
    """Merge a knowledge base's nodes and relationships into the graph.

    Ensures each distinct vertex/edge label exists first (sidestepping Apache
    Age's racy auto-create), then issues one `MERGE` per node and relationship
    and commits the graph connection. Returns the executed Cypher strings.

    Raises:
        ValueError: If `graph_name` is missing or the graph does not exist.
    """
    if not graph_name:
        raise ValueError(
            "graph_name is required when merging a knowledge base into an Apache "
            "Age graph"
        )
    if not await repository.graph_exists(graph_name):
        raise ValueError(
            f"Apache Age graph '{graph_name}' does not exist in the database"
        )

    for label in dict.fromkeys(node.label for node in knowledge_base.nodes):
        await repository.ensure_vertex_label(graph_name, label)
    for label in dict.fromkeys(
        relationship.label for relationship in knowledge_base.relationships
    ):
        await repository.ensure_edge_label(graph_name, label)

    queries: list[str] = []
    for node in knowledge_base.nodes:
        node_properties = dict(node.properties)
        if node.id is not None:
            node_properties["id"] = node.id
        queries.append(await repository.merge_node(graph_name, node.label, node_properties))

    for relationship in knowledge_base.relationships:
        queries.append(
            await repository.merge_relationship(
                graph_name,
                relationship.source_id,
                relationship.target_id,
                relationship.label,
                relationship.properties,
            )
        )

    await repository.commit()
    return queries


__all__ = ["merge_knowledge_base"]
