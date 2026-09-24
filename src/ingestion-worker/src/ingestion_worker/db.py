"""Async database resources for the ingestion worker.

Opens the pair every task needs: an Apache Age psycopg connection wrapped in an
`AgeGraphRepository` (the graph write), and a SQLAlchemy async engine/session
(the side-table and job-state writes). The two point at the same PostgreSQL
instance but are separate connections, mirroring the shared-library split.
"""

from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from common.database.connection import create_connection, database_url
from common.repositories.age_graph_repository import AgeGraphRepository


def create_engine() -> AsyncEngine:
    """Build the SQLAlchemy async engine from the shared environment config."""
    return create_async_engine(database_url())


@asynccontextmanager
async def open_job_resources():
    """Yield `(session, repository)` and close both on the way out.

    Usage:
        async with open_job_resources() as (session, repository):
            ...
    """
    connection = await create_connection()
    repository = AgeGraphRepository(connection)
    engine = create_engine()
    try:
        async with AsyncSession(engine) as session:
            yield session, repository
    finally:
        await engine.dispose()
        await connection.close()


__all__ = ["create_engine", "open_job_resources"]