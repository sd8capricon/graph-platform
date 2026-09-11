from langchain.tools import ToolRuntime, tool

from graphrag_apacheage.agent.context import AgentContext
from graphrag_apacheage.models.graph_schema_registry import GraphSchemaRegistry


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
    return [
        {
            "type": record.type,
            "name": record.name,
            "description": record.description,
            "aliases": record.aliases,
            "properties": record.properties,
            "source_label": record.source_label,
            "target_label": record.target_label,
        }
        for record in records
    ]
