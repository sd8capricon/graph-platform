from langchain.tools import ToolRuntime, tool

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.models import NodeRef
from graphrag_apacheage.agent.serializers import AgentSerializer
from graphrag_apacheage.models.graph_schema_registry import (
    GraphSchemaRegistry,
    SchemaType,
)
from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.schemas.knowledge_base import KnowledgeNode


@tool(
    description=(
        "Search the graph's schema for node and relationship types matching a "
        "text query. Each result describes a type (not an instance): its "
        "name, whether it is a node or relationship, a description, known "
        "aliases, its properties, and for relationships the source/target "
        "node labels. Use this to discover which labels and properties exist "
        "in the graph before querying actual data with search_entities or "
        "get_node_neighbours."
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
        context.model,
        labels=labels,
    )
    return [AgentSerializer.node_embedding_record_to_dict(record) for record in records]


@tool(
    description=(
        "Overview of how a node label, or one specific node, connects in the "
        "graph — cheap to call, returns shape not data. Two modes. Pass only "
        "`node.label` for the label-level schema: the label's property names, "
        "plus every relationship label that nodes of that label participate "
        "in, its direction, the neighbour labels on the other end, their "
        "property names, and a graph-wide count summed over all nodes of that "
        "label. Also pass `node.id` to get the same shape for that one node, "
        "where each count is that node's own degree. Use label mode to plan a "
        "traversal before you hold a concrete node; use id mode once "
        "`search_entities` has given you a real node id, to decide what to "
        "fetch with `get_node_neighbours`. Property names only, never values. "
        "An unknown label or id returns an empty neighborhood."
    )
)
async def get_node_schema(node: NodeRef, runtime: ToolRuntime[AgentContext]):
    """Cheap overview counterpart to get_node_neighbours, in two modes.

    With `node.id`, delegates to `AgeGraphRepository.get_node_schema()` for
    that one instance; without it, to `AgeGraphRepository.get_label_schema()`
    for every node carrying `node.label`. Both return the same
    `(relationship_label, direction, neighbor_label, count)` tuples, so the
    `GraphSchemaRegistry` property-name enrichment and the serializer call
    below are mode-independent — only `count`'s meaning differs (one node's
    degree vs. a total across every node of the label).

    A blank-but-present `node.id` is a malformed instance reference and
    raises, rather than silently degrading to label mode and answering a
    broader question. An unrecognized id or label is not an error: it matches
    no node and returns an empty neighborhood.
    """
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
            context.session, context.graph_name, [node.label], type=SchemaType.NODE
        ),
        await GraphSchemaRegistry.get_properties_by_name(
            context.session,
            context.graph_name,
            relationship_labels,
            type=SchemaType.RELATIONSHIP,
        ),
        await GraphSchemaRegistry.get_properties_by_name(
            context.session, context.graph_name, neighbor_labels, type=SchemaType.NODE
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
        "Get a knowledge graph node's neighbours. Returns every relationship "
        "incident to the node, grouped under the node itself, regardless of "
        "direction and with no relationship repeated. Optionally restrict "
        "results to one or more relationship labels."
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
        "Search graph relationships by relationship type and property filters. "
        "Can restrict the source and target node labels and optionally source/target "
        "node IDs. Returns source node, relationship properties, and target node."
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
