from langchain.tools import ToolRuntime, tool

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.agent.serializers import (
    node_embedding_record_to_dict,
    schema_registry_record_to_dict,
)
from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry
from graphrag_apacheage.models.node_embedding import NodeEmbedding


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
