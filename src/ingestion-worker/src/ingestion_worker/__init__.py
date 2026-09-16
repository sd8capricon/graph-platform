"""Ingestion worker entrypoint: read a knowledge base and write it to the graph.

Owns the ingestion workload of ADR-0004: `KnowledgeBase.from_json_file()` plus
`KnowledgeBaseService.upsert_knowledge_base()`, i.e. the graph write, the schema
registry write and the node-embedding write. The shared pieces it drives -
schemas, ORM models, the repository and the service - live in the `common`
project and are imported from there.
"""

import asyncio

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.config import load_config, settings
from common.database.connection import create_connection, database_url
from common.models import graph_schema_registry  # noqa: F401
from common.models import node_embedding, schema_embedding
from common.models.base import Base
from common.repositories.age_graph_repository import AgeGraphRepository
from common.schemas.knowledge_base import KnowledgeBase
from common.schemas.model import Model, ModelType
from common.services.knowledge_base_service import KnowledgeBaseService

# Placeholder until the Organization entity (ADR-0002) exists: every write/read
# path now requires an organization_id, and this demo has exactly one org.
DEMO_ORGANIZATION_ID = "demo-org"
DEMO_GRAPH_NAME = "kb_graph"
DEMO_KNOWLEDGE_BASE_PATH = "dummy_data/f1_kb.json"


def embedding_model() -> Model | None:
    """Return the configured embedding provider, or `None` when none is set."""
    return next((m for m in settings.models if ModelType.EMBEDDING in m.type), None)


async def create_knowledge_base(
    repository: AgeGraphRepository, session: AsyncSession
) -> None:
    """Ingest the demo knowledge base into the graph and both side-tables.

    Creates the graph if it does not exist (a no-op when it does), then calls
    `KnowledgeBaseService.upsert_knowledge_base()` - the single call that writes
    the graph, the schema registry and the node embeddings - and commits the
    SQLAlchemy session, which the service deliberately leaves to its caller.

    Args:
        repository: The Apache Age repository the graph writes go through.
        session: The SQLAlchemy session the side-table writes go through.
    """
    knowledge_base = KnowledgeBase.from_json_file(DEMO_KNOWLEDGE_BASE_PATH)
    knowledge_base_service = KnowledgeBaseService(repository)
    await knowledge_base_service.create_graph(DEMO_GRAPH_NAME)
    await knowledge_base_service.upsert_knowledge_base(
        session,
        knowledge_base,
        DEMO_GRAPH_NAME,
        DEMO_ORGANIZATION_ID,
        model=embedding_model(),
    )
    await session.commit()


async def run() -> None:
    """Run one ingestion pass: create tables/indexes, then ingest the demo KB.

    Opens the Apache Age connection, creates the ORM tables (their modules are
    imported above so they register on `Base.metadata`), creates the per-model
    partial ANN index when an embedding model is configured, and then ingests the
    demo knowledge base. Both the engine and the Age connection are closed on the
    way out.
    """
    pg_connection = await create_connection()
    age_repository = AgeGraphRepository(pg_connection)
    engine = create_async_engine(database_url())
    try:
        # The tables must exist before the graph is dropped: dropping it also
        # clears the graph's side-table rows, which would otherwise be left
        # orphaned from the previous run.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as session:
            # The embedding columns are dimensionless, so an ANN index has to be
            # created per embedding model rather than declared on the table - see
            # common/database/indexes.py. Cheap and idempotent.
            model = embedding_model()
            if model is not None:
                await node_embedding.NodeEmbedding.ensure_embedding_index(session, model)
                await schema_embedding.SchemaEmbedding.ensure_embedding_index(
                    session, model
                )
                await session.commit()
            # SETUP KB
            # await KnowledgeBaseService(age_repository).delete_graph(
            #     session, DEMO_GRAPH_NAME, DEMO_ORGANIZATION_ID
            # )
            # await session.commit()
            await create_knowledge_base(age_repository, session)
    finally:
        await engine.dispose()
        await pg_connection.close()


def main() -> None:
    """Load environment/config and run one ingestion pass."""
    load_dotenv()
    load_config()
    asyncio.run(run())


__all__ = ["main", "run", "create_knowledge_base", "embedding_model"]
