"""ORM model for the API-owned `index_job` table.

One row per indexing request. Job lifecycle is management state: the API creates
the row (and owns the DDL via its EF migration), while the worker claims it and
advances its status through `ingestion_worker.job_store.IndexJobStore`. Column
names are snake_case per ADR-0005; the API's EF mapping must use explicit
`HasColumnName(...)` to match.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from ingestion_worker.models.base import IndexJobBase


class IndexJob(IndexJobBase):
    """One API-created ingestion request tracked by the worker."""

    __tablename__ = "index_job"

    id: Mapped[str] = mapped_column(String(255), primary_key=True)
    organization_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )
    graph_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    total_files: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    processed_files: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    failed_files: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    graph_dispatched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    embedding_model_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    requested_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


__all__ = ["IndexJob"]
