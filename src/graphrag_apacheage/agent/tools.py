from langchain.tools import ToolRuntime, tool

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.serializers import AgentSerializer
from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry
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
        "Summarize how a node connects to the rest of the graph: the "
        "distinct relationship types on the node, each with its direction, "
        "the label of the node on the other end, and how many relationships "
        "match. Use this to understand a node's neighborhood before fetching "
        "the actual relationships with get_node_neighbours."
    )
)
async def get_node_schema(node: KnowledgeNode, runtime: ToolRuntime[AgentContext]):
    """Cheap overview counterpart to get_node_neighbours; delegates to AgeGraphRepository.get_node_schema. Requires node.id."""
    if node.id is None:
        raise ValueError("node.id is required to look up its schema")

    context = runtime.context
    entries = await context.repository.get_node_schema(context.graph_name, node.id)
    return AgentSerializer.node_schema_to_dict(node.id, node.label, entries)


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


GRAPH_TOOLS = [
    search_schema_registry,
    search_entities,
    get_node_schema,
    get_node_neighbours,
]
"""The knowledge-graph tools handed to the agent, ordered as the system prompt
teaches them (schema discovery -> entity lookup -> neighborhood overview ->
neighbours). Defined here, in the leaf module that owns the tools, rather than in
an `agent/__init__.py`: `agent/` has no `__init__.py` at all, on purpose (see the
import-cycle note in CLAUDE.md), so the aggregate has to live beside the tools it
aggregates.
"""

__all__ = [
    "search_schema_registry",
    "search_entities",
    "get_node_schema",
    "get_node_neighbours",
    "GRAPH_TOOLS",
]
