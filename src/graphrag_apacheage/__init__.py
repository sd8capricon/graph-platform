import asyncio
import os

from dotenv import load_dotenv
from psycopg import AsyncConnection
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from graphrag_apacheage.config import load_config, settings
from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.model import Model, ModelType


def _database_url() -> str:
    return (
        f"postgresql+psycopg://{os.environ['PGUSER']}:{os.environ['PGPASSWORD']}"
        f"@{os.environ['PGHOST']}:{os.environ['PGPORT']}/{os.environ['PGDATABASE']}"
    )


def _embedding_model() -> Model | None:
    return next((m for m in settings.models if ModelType.EMBEDDING in m.type), None)


async def create_connection() -> AsyncConnection:
    host = os.environ["PGHOST"]
    connection = await AsyncConnection.connect(
        host=host,
        port=os.environ["PGPORT"],
        dbname=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )
    async with connection.cursor() as cursor:
        # Azure Postgres has AGE pre-loaded via server config; skip LOAD for Azure hosts
        is_azure = "database.azure.com" in host
        if not is_azure:
            await cursor.execute("LOAD 'age';")
        await cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")
        await cursor.execute('SET search_path = ag_catalog, "$user", public;')
    return connection


async def create_knowledge_base(repository: AgeGraphRepository, session: AsyncSession):
    # Deferred for the same reason as the imports in run(): must not run
    # before `main()` has called `load_config()`.
    from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    knowledge_base = KnowledgeBase.from_json_file("dummy_data/f1_kb.json")
    knowledge_base_service = KnowledgeBaseService(repository)
    # No-ops if the graph is already there.
    await knowledge_base_service.create_graph("kb_graph")
    # Writes the graph, the schema registry and the node embeddings in one call;
    # committing the SQLAlchemy session is left to us.
    await knowledge_base_service.upsert_knowledge_base(
        session, knowledge_base, "kb_graph", model=_embedding_model()
    )
    await session.commit()


async def run():
    # Deferred: importing these sizes the pgvector `Vector` column from
    # `settings.embedding_dimension`, so they must not be imported before
    # `main()` has called `load_config()`.
    # Unused by name: imported so their tables register on Base.metadata,
    # which is what create_all below actually reads.
    from graphrag_apacheage.models import (
        graph_schema_registry,  # noqa: F401
        node_embedding,
    )
    from graphrag_apacheage.models.base import Base
    from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService

    pg_connection = await create_connection()
    age_repository = AgeGraphRepository(pg_connection)
    engine = create_async_engine(_database_url())
    try:
        # The tables must exist before the graph is dropped: dropping it also
        # clears the graph's side-table rows, which would otherwise be left
        # orphaned from the previous run.
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncSession(engine) as session:
            await KnowledgeBaseService(age_repository).delete_graph(session, "kb_graph")
            await session.commit()
            await create_knowledge_base(age_repository, session)
    finally:
        await engine.dispose()
        await pg_connection.close()


def main() -> None:
    load_dotenv()
    settings = load_config()
    asyncio.run(run())
