"""Shared metadata for the ingestion job-state tables.

The counterpart of `common.models.base.Base`, but for SQLAlchemy **Core**
`Table`s. It is a dedicated `MetaData`, never `Base.metadata`, so the Python
services' `Base.metadata.create_all` never creates, alters or drops the
API-owned `index_job`/`index_file`/`knowledge_base` tables. That preserves the
existing "two owners, disjoint DDL" invariant: EF owns
`organization`/`user_organization`/`model_config`/`knowledge_base`/`index_*`,
Python owns the embedding/registry tables.
"""

from sqlalchemy import MetaData

IndexJobMetadata = MetaData()


def create_job_tables(bind, *, include_knowledge_base: bool = False) -> None:
    """Create the job-state tables on `bind` (a sync Engine or Connection).

    Test/dev helper only. In production the API's EF migration owns these tables,
    so no service entrypoint should call this. Pass
    `include_knowledge_base=True` when a test also needs a stand-in for the
    EF-owned `knowledge_base` table. For an async engine, call it via
    `await conn.run_sync(lambda c: create_job_tables(c, ...))`.
    """
    from ingestion_worker.models.index_file import index_file  # noqa: F401
    from ingestion_worker.models.index_job import index_job

    tables = [index_job, index_file]
    if include_knowledge_base:
        from ingestion_worker.models.knowledge_base import knowledge_base

        tables.append(knowledge_base)
    IndexJobMetadata.create_all(bind, tables=tables)


__all__ = ["IndexJobMetadata", "create_job_tables"]