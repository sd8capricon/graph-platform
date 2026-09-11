import asyncio
import os

from dotenv import load_dotenv
from psycopg import AsyncConnection

from graphrag_apacheage.config import load_config
from graphrag_apacheage.repositories.age_graph_repository import AgeGraphRepository
from graphrag_apacheage.schemas.knowledge_base import KnowledgeBase
from graphrag_apacheage.services.knowledge_base_service import KnowledgeBaseService


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
        await cursor.execute('SET search_path = ag_catalog, "$user", public;')
    return connection


async def create_knowledge_base(repository: AgeGraphRepository):
    if not await repository.graph_exists("kb_graph"):
        await repository.create_graph("kb_graph")
    knowledge_base = KnowledgeBase.from_json_file("dummy_data/f1_kb.json")
    knowledge_base_service = KnowledgeBaseService(repository)
    await knowledge_base_service.upsert_knowledge_base(knowledge_base, "kb_graph")


async def run():
    pg_connection = await create_connection()
    age_repository = AgeGraphRepository(pg_connection)


def main() -> None:
    load_dotenv()
    load_config()
    asyncio.run(run())
