"""Private metadata for the ingestion job-state tables.

It is a dedicated `MetaData`, never `Base.metadata`, so the Python services'
`Base.metadata.create_all` never creates, alters or drops the API-owned
`index_job`/`index_file` tables. The shared `knowledge_base` mapping lives in
`common.models.knowledge_base` on its own API-owned metadata for the same reason.
"""

from sqlalchemy import MetaData

IndexJobMetadata = MetaData()


def create_job_tables(bind, *, include_knowledge_base: bool = False) -> None:
    """Create the job-state tables on `bind` (a sync Engine or Connection).

    Test/dev helper only. In production the API's EF migration owns these tables,
    so no service entrypoint should call this. Pass
    `include_knowledge_base=True` when a test also needs a stand-in for the
    API-owned `knowledge_base` table. For an async engine, call it via
    `await conn.run_sync(lambda c: create_job_tables(c, ...))`.
    """
    from ingestion_worker.models.index_file import index_file  # noqa: F401
    from ingestion_worker.models.index_job import index_job

    tables = [index_job, index_file]
    IndexJobMetadata.create_all(bind, tables=tables)
    if include_knowledge_base:
        from common.models.knowledge_base import KnowledgeBase

        KnowledgeBase.metadata.create_all(bind, tables=[KnowledgeBase.__table__])


__all__ = ["IndexJobMetadata", "create_job_tables"]
