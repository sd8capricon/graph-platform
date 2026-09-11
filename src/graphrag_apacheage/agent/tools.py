from langchain.tools import ToolRuntime, tool

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.serializers import (
    node_embedding_record_to_dict,
    node_relationships_to_dict,
    node_schema_to_dict,
    schema_registry_record_to_dict,
)
from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry
from graphrag_apacheage.models.node_embedding import NodeEmbedding
from graphrag_apacheage.schemas.knowledge_base import KnowledgeNode


@tool
async def search_schema_registry(query: str, runtime: ToolRuntime[AgentContext]):
    """Search the schema registry, scoped to the run's attached knowledge bases."""
    context = runtime.context
    records = await GraphSchemaRegistry.vector_search(
        context.session,
        query,
        context.graph_name,
        context.model,
        knowledge_base_ids=context.attached_kb_ids,
    )
    return [schema_registry_record_to_dict(record) for record in records]


@tool
async def search_entities(
    query: str, runtime: ToolRuntime[AgentContext], labels: list[str] | None = None
):
    """Search knowledge graph entities (nodes) by similarity to a text query.

    Optionally restrict results to one or more node labels (e.g. 'Driver').
    """
    context = runtime.context
    records = await NodeEmbedding.vector_search(
        context.session,
        query,
        context.graph_name,
        context.model,
        labels=labels,
    )
    return [node_embedding_record_to_dict(record) for record in records]


@tool
async def get_node_schema(node: KnowledgeNode, runtime: ToolRuntime[AgentContext]):
    """Summarize how a node connects to the rest of the graph.

    Returns the distinct relationship types on `node`, each with its direction,
    the label of the node on the other end, and how many relationships match.
    Use this to understand a node's neighborhood before fetching the actual
    relationships with `get_node_neighbours`.
    """
    if node.id is None:
        raise ValueError("node.id is required to look up its schema")

    context = runtime.context
    entries = await context.repository.get_node_schema(context.graph_name, node.id)
    return node_schema_to_dict(node.id, node.label, entries)


@tool
async def get_node_neighbours(
    node: KnowledgeNode,
    runtime: ToolRuntime[AgentContext],
    relationships: list[str] | None = None,
):
    """Get a knowledge graph node's neighbours.

    Returns every relationship incident to `node`, grouped under the node
    itself, regardless of direction and with no relationship repeated.
    Optionally restrict results to one or more relationship labels
    (e.g. 'DRIVES_FOR').
    """
    if node.id is None:
        raise ValueError("node.id is required to look up its relationships")

    context = runtime.context
    triplets = await context.repository.get_node_neighbours(
        context.graph_name, node.id, relationships
    )
    return node_relationships_to_dict(node.id, node.label, node.properties, triplets)
