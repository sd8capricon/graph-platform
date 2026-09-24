"""The ingestion pipeline: a KnowledgeBase into the graph and both side-tables.

Replaces the previous `KnowledgeBaseService.upsert_knowledge_base()` (ADR-0004
Decision 4: ingestion orchestration belongs to the worker). The graph write is
idempotent (`MERGE`); the side-table writes are idempotent upserts. The graph
connection is committed here via the repository, while the SQLAlchemy `session`
is only flushed - committing it is the caller's job, so a whole job can be
finalized with its status write in one transaction.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from common.repositories.age_graph_repository import AgeGraphRepository
from common.schemas.knowledge_base import KnowledgeBase
from common.schemas.model import Model

from ingestion_worker.ingestion.extraction import (
    graph_schema_registry_records,
    node_embedding_records,
)
from ingestion_worker.ingestion.graph import merge_knowledge_base
from ingestion_worker.ingestion.writer import (
    upsert_node_embeddings,
    upsert_schema_registry,
)


async def ingest_knowledge_base(
    session: AsyncSession,
    repository: AgeGraphRepository,
    knowledge_base: KnowledgeBase,
    graph_name: str,
    organization_id: str,
    model: Model | None = None,
) -> list[str]:
    """Merge a knowledge base into the graph and upsert both side-tables.

    Args:
        session: Session for the schema-registry and node-embedding writes.
        repository: The Apache Age repository the graph write goes through.
        knowledge_base: The KB to ingest. Its `id` must be set.
        graph_name: The target graph. It must already exist.
        organization_id: Scopes every side-table row written.
        model: Embedding provider. When None, embeddings are skipped.

    Returns:
        The Cypher statements executed against the graph.
    """
    queries = await merge_knowledge_base(repository, knowledge_base, graph_name)

    schema_records = graph_schema_registry_records(
        knowledge_base, graph_name, organization_id
    )
    await upsert_schema_registry(session, schema_records, model=model)

    embedding_records = node_embedding_records(
        knowledge_base, graph_name, organization_id
    )
    await upsert_node_embeddings(session, embedding_records, model=model)

    return queries


__all__ = ["ingest_knowledge_base"]
