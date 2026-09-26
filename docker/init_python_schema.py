"""Initialize the Python-owned graph/vector tables before Celery services start."""

import asyncio
import os

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from common.config import load_config, settings
from common.database.connection import create_connection, database_url
from common.models import graph_schema_registry, node_embedding, schema_embedding  # noqa: F401
from common.models.base import Base
from common.schemas.model import ModelType


async def initialize() -> None:
    """Create common-owned tables and per-model indexes, leaving API DDL alone."""
    load_config(os.environ.get("INGESTION_CONFIG_PATH", "/app/configs/local.yaml"))
    graph_connection = await create_connection()
    engine = create_async_engine(database_url())
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        embedding_model = next(
            (model for model in settings.models if ModelType.EMBEDDING in model.type), None
        )
        if embedding_model is not None:
            async with AsyncSession(engine) as session:
                await node_embedding.NodeEmbedding.ensure_embedding_index(session, embedding_model)
                await schema_embedding.SchemaEmbedding.ensure_embedding_index(
                    session, embedding_model
                )
                await session.commit()
    finally:
        await engine.dispose()
        await graph_connection.close()


if __name__ == "__main__":
    asyncio.run(initialize())
