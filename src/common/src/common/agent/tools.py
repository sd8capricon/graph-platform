from langchain.tools import ToolRuntime, tool

from common.agent.context import AgentContext
from common.agent.models import NodeRef
from common.agent.serializers import AgentSerializer
from common.models.graph_schema_registry import (
    GraphSchemaRegistry,
    SchemaType,
)
from common.models.node_embedding import NodeEmbedding
from common.schemas.knowledge_base import KnowledgeNode


@tool(
    description=(
        "Vector-search the graph schema to discover node and relationship types. "
        "Use this first when you need to understand which labels, properties, "
        "aliases, or relationship types are available."
    )
)
async def search_schema_registry(query: str, runtime: ToolRuntime[AgentContext]):
    """Vector-search GraphSchemaRegistry, scoped to the run's attached knowledge bases."""
    if not query.strip():
        raise ValueError("query must not be empty")

    context = runtime.context
    records = await GraphSchemaRegistry.vector_search(
        context.session,
        query,
        context.graph_name,
        context.organization_id,
        context.model,
        knowledge_base_ids=context.attached_kb_ids,
    )
    return [
        AgentSerializer.schema_registry_record_to_dict(record) for record in records
    ]


@tool(
    description=(
        "Search knowledge graph entities (nodes) by similarity to a text "
        "query. Optionally restrict results to one or more node labels. "
        "Returns each matching node's id, label, and properties."
    )
)
async def search_entities(
    query: str, runtime: ToolRuntime[AgentContext], labels: list[str] | None = None
):
    """Vector-search NodeEmbedding for context.graph_name; not scoped to attached_kb_ids."""
    if not query.strip():
        raise ValueError("query must not be empty")

    context = runtime.context
    records = await NodeEmbedding.vector_search(
        context.session,
        query,
        context.graph_name,
        context.organization_id,
        context.model,
        labels=labels,
    )
    return [AgentSerializer.node_embedding_record_to_dict(record) for record in records]


@tool(
    description=(
        "Inspect the graph structure around a node label or specific node. "
        "Use this to plan a traversal and see available relationship types, "
        "directions, neighbour labels, properties, and counts. This does not "
        "return property values."
    )
)
async def get_node_schema(node: NodeRef, runtime: ToolRuntime[AgentContext]):
    """Get the graph structure for a node label or specific node. Use label mode (`node.label`) to plan a traversal before finding a node. Use node mode (`node.id`) to inspect the relationships of a specific node. Returns relationship types, directions, neighbour labels, properties, and counts, but no property values."""
    if node.id is not None and not node.id.strip():
        raise ValueError(
            "node.id must not be blank - omit it entirely for the label schema"
        )
    if not node.label.strip():
        raise ValueError("node.label is required to look up a schema")

    context = runtime.context
    entries = (
        await context.repository.get_node_schema(context.graph_name, node.id)
        if node.id
        else await context.repository.get_label_schema(context.graph_name, node.label)
    )

    relationship_labels = {
        relationship_label for relationship_label, _, _, _ in entries
    }
    neighbor_labels = {neighbor_label for _, _, neighbor_label, _ in entries}

    node_properties, relationship_properties, neighbor_properties = (
        await GraphSchemaRegistry.get_properties_by_name(
            context.session,
            context.graph_name,
            context.organization_id,
            [node.label],
            type=SchemaType.NODE,
        ),
        await GraphSchemaRegistry.get_properties_by_name(
            context.session,
            context.graph_name,
            context.organization_id,
            relationship_labels,
            type=SchemaType.RELATIONSHIP,
        ),
        await GraphSchemaRegistry.get_properties_by_name(
            context.session,
            context.graph_name,
            context.organization_id,
            neighbor_labels,
            type=SchemaType.NODE,
        ),
    )

    return AgentSerializer.node_schema_to_dict(
        node.id,
        node.label,
        entries,
        node_properties=node_properties.get(node.label, []),
        relationship_properties=relationship_properties,
        neighbor_properties=neighbor_properties,
    )


@tool(
    description=(
        "Get relationships and neighbouring nodes for a specific node. "
        "Use this to traverse the graph after finding an entity. "
        "Optionally filter by one or more relationship labels."
    )
)
async def get_node_neighbours(
    node: KnowledgeNode,
    runtime: ToolRuntime[AgentContext],
    relationships: list[str] | None = None,
):
    """Delegates to AgeGraphRepository.get_node_neighbours and reshapes the (source, relationship, target) triplets via AgentSerializer.node_neighbours_to_dict. Requires node.id."""
    if node.id is None:
        raise ValueError("node.id is required to look up its relationships")

    context = runtime.context
    triplets = await context.repository.get_node_neighbours(
        context.graph_name, node.id, relationships
    )
    return AgentSerializer.node_neighbours_to_dict(
        node.id, node.label, node.properties, triplets
    )


@tool(
    description=(
        "Search graph relationships by relationship type and optional property filters. "
        "Use this to find specific connections between nodes when you know the "
        "relationship type. You can filter by source/target labels, node IDs, "
        "or relationship properties."
    )
)
async def get_relationship(
    relationship: str,
    runtime: ToolRuntime[AgentContext],
    source_label: str | None = None,
    target_label: str | None = None,
    source_id: str | None = None,
    target_id: str | None = None,
    properties: dict | None = None,
):
    """Delegates to AgeGraphRepository.search_relationships and reshapes the (source, relationship, target) triplets via AgentSerializer.relationship_matches_to_dict. Requires a non-empty relationship label."""
    if not relationship.strip():
        raise ValueError("relationship must not be empty")

    context = runtime.context
    triplets = await context.repository.search_relationships(
        context.graph_name,
        relationship,
        source_label=source_label,
        target_label=target_label,
        source_id=source_id,
        target_id=target_id,
        properties=properties,
    )
    return AgentSerializer.relationship_matches_to_dict(triplets)


GRAPH_TOOLS = [
    search_schema_registry,
    search_entities,
    get_node_schema,
    get_node_neighbours,
    get_relationship,
]
"""The knowledge-graph tools handed to the agent, ordered as the system prompt
teaches them (schema discovery -> entity lookup -> neighborhood overview ->
neighbours -> relationship search). Defined here, in the leaf module that owns
the tools, rather than in an `agent/__init__.py`: `agent/` has no `__init__.py`
at all, on purpose (see the import-cycle note in CLAUDE.md), so the aggregate
has to live beside the tools it aggregates.
"""

__all__ = [
    "search_schema_registry",
    "search_entities",
    "get_node_schema",
    "get_node_neighbours",
    "get_relationship",
    "GRAPH_TOOLS",
]
