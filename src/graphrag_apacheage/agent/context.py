from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.model import Model


class AgentContext(BaseModel):
    """Static, per-run context passed to a LangChain agent via `context_schema`.

    Attributes:
        graph_name: Name of the Apache Age graph the agent's tools operate against.
        attached_kb_ids: IDs of the knowledge bases the agent's tools may operate
            against for this run (e.g. to scope schema/embedding lookups).
        session: SQLAlchemy async session tools use to query/persist data in the
            NodeEmbedding/GraphSchemaRegistry side-tables.
        repository: AgeGraphRepository tools use to query/persist data directly
            in the live Apache Age graph (e.g. relationship traversal).
        model: The embedding provider configuration used by tools that perform
            vector search. `None` if no embedding provider is configured, in
            which case such tools should raise (see `GraphSchemaRegistry.vector_search`).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    graph_name: str
    attached_kb_ids: list[str] = Field(default_factory=list)
    session: AsyncSession
    repository: AgeGraphRepository
    model: Model | None = None


__all__ = ["AgentContext"]
