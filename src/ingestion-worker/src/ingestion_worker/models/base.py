"""Private declarative base for the ingestion job-state models.

It is separate from both `common.models.base.Base` and
`common.models.base.ApiOwnedBase`, so `Base.metadata.create_all()` only creates
Python-owned shared tables. The API owns DDL for `index_job`/`index_file` and
`knowledge_base`; the worker's class mappings only describe those tables.
"""

from sqlalchemy.orm import DeclarativeBase


class IndexJobBase(DeclarativeBase):
    """Declarative base for API-owned ingestion job-state tables."""

    pass


def create_job_tables(bind, *, include_knowledge_base: bool = False) -> None:
    """Create the job-state tables on `bind` (a sync Engine or Connection).

    Test/dev helper only. In production the API's EF migration owns these tables,
    so no service entrypoint should call this. Pass
    `include_knowledge_base=True` when a test also needs a stand-in for the
    API-owned `knowledge_base` table. For an async engine, call it via
    `await conn.run_sync(lambda c: create_job_tables(c, ...))`.
    """
    from ingestion_worker.models.index_file import IndexFile  # noqa: F401
    from ingestion_worker.models.index_job import IndexJob  # noqa: F401

    IndexJobBase.metadata.create_all(bind)
    if include_knowledge_base:
        from common.models.knowledge_base import KnowledgeBase

        KnowledgeBase.metadata.create_all(bind, tables=[KnowledgeBase.__table__])


__all__ = ["IndexJobBase", "create_job_tables"]
