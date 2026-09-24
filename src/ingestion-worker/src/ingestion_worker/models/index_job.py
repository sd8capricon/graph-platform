"""Core definition of the API-owned `index_job` table.

One row per indexing request. Job lifecycle is management state: the API creates
the row (and owns the DDL via its EF migration), while the worker claims it and
advances its status through `ingestion_worker.job_store.IndexJobStore`. Column
names are snake_case per ADR-0005; the API's EF mapping must use explicit
`HasColumnName(...)` to match.
"""

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    String,
    Table,
    Text,
    func,
)

from ingestion_worker.models.base import IndexJobMetadata

index_job = Table(
    "index_job",
    IndexJobMetadata,
    Column("id", String(255), primary_key=True),
    Column("organization_id", String(255), nullable=False, index=True),
    Column("knowledge_base_id", String(255), nullable=False, index=True),
    Column("graph_name", String(255), nullable=False),
    Column("status", String(32), nullable=False),
    Column("total_files", Integer, nullable=False, server_default="0"),
    Column("processed_files", Integer, nullable=False, server_default="0"),
    Column("failed_files", Integer, nullable=False, server_default="0"),
    Column("graph_dispatched", Boolean, nullable=False, server_default="false"),
    Column("embedding_model_id", String(255), nullable=True),
    Column("requested_by", String(255), nullable=True),
    Column("error", Text, nullable=True),
    Column(
        "created_at",
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    ),
    Column("started_at", DateTime(timezone=True), nullable=True),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

__all__ = ["index_job"]